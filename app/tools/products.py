"""
Trusted product-discovery tool for LionCity.

WHY THIS MODULE EXISTS
----------------------
Customers speak in product names ("I need Product A" / "industrial cable"),
but stock/price tools need a verified SKU. Product discovery answers ONE
question only: "which catalogue product does the customer mean?" It maps a
free-text query onto VERIFIED product identity using the existing
authoritative ``products`` table. There is no separate/duplicated catalogue.

Actual products schema (verified against data/lioncity.db):
    sku           TEXT PRIMARY KEY
    product_name  TEXT
    description   TEXT
    category      TEXT
    list_price    REAL

TRUST RULES (enforced here)
---------------------------
1. Verified identity only. A SKU/name returned here always comes from the
   database. The LLM/customer text can never manufacture a SKU.
2. No invention. An unknown query returns NO_MATCH; we never substitute an
   unrelated product or fabricate one.
3. No silent first-row pick. If several products plausibly match, we return
   all candidates (MULTIPLE_MATCHES) for the agent to clarify later.
4. Separation of concerns. Product discovery must NOT return stock,
   availability, customer price, contract price, or delivery info. Those
   remain owned by check_inventory / get_customer_price / check_delivery.
   We expose list_price only as descriptive catalogue metadata; it is NOT a
   customer quotation.
5. Deterministic result contract via an explicit ``status`` field:
        UNIQUE_MATCH     -> exactly one verified product
        MULTIPLE_MATCHES -> several candidates
        NO_MATCH         -> nothing matched
   Callers never parse natural-language messages to determine state.

MATCHING (lightweight, deterministic, case-insensitive)
-------------------------------------------------------
Strongest match wins:
  1. Exact SKU match           (whole query equals a SKU) -> unique.
  2. Exact product-name match  (whole query equals a name) -> unique.
  3. Explicit SKU-token match  (a word in the query equals a real SKU, e.g.
     "Industrial Cable CBL-210" or "10 units of CBL-210") -> unique (or
     multiple if several distinct real SKUs are named). The token must equal
     an ACTUAL catalogue SKU, so nothing is invented and a nonexistent SKU
     never resolves.
  4. Substring match across name/description/category (may be multiple).
"""

from app.database import get_connection


# Deterministic status constants (the result contract).
STATUS_UNIQUE_MATCH = "UNIQUE_MATCH"
STATUS_MULTIPLE_MATCHES = "MULTIPLE_MATCHES"
STATUS_NO_MATCH = "NO_MATCH"

# Punctuation stripped from the EDGES of each query token before comparing it
# to a real SKU (so "CBL-210," or "(CBL-210)" still matches the SKU "CBL-210").
# Internal hyphens are preserved because they are part of the SKU itself.
_SKU_TOKEN_STRIP = " \t\r\n.,;:!?()[]{}\"'"


def _row_to_product(row):
    """
    Convert a products row into a trusted product dict.

    Includes descriptive catalogue fields only. list_price is catalogue
    metadata, NOT a customer quotation (pricing stays with get_customer_price).
    """
    return {
        "sku": row["sku"],
        "product_name": row["product_name"],
        "description": row["description"],
        "category": row["category"],
        "list_price": row["list_price"],
    }


def _fetch_all_products():
    """Read all products from the authoritative products table."""
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        "SELECT sku, product_name, description, category, list_price "
        "FROM products"
    )
    rows = cursor.fetchall()
    connection.close()
    return rows


def find_product(query):
    """
    Resolve a customer/LLM product query to VERIFIED catalogue product(s).

    Parameters
    ----------
    query : str
        Free text (e.g. "industrial cable") or an SKU (e.g. "CBL-210").

    Returns
    -------
    dict with a deterministic contract:

        NO MATCH:
            {"success": False, "status": "NO_MATCH", "query": <query>}

        UNIQUE MATCH:
            {"success": True, "status": "UNIQUE_MATCH", "product": {...}}

        MULTIPLE MATCHES:
            {"success": True, "status": "MULTIPLE_MATCHES",
             "candidates": [ {...}, {...} ]}
    """
    if not isinstance(query, str) or query.strip() == "":
        return {"success": False, "status": STATUS_NO_MATCH, "query": query}

    needle = query.strip().lower()
    rows = _fetch_all_products()

    # 1. Exact SKU match (case-insensitive) -> unique.
    for row in rows:
        if row["sku"].lower() == needle:
            return {
                "success": True,
                "status": STATUS_UNIQUE_MATCH,
                "product": _row_to_product(row),
            }

    # 2. Exact product-name match (case-insensitive) -> unique.
    for row in rows:
        if row["product_name"].lower() == needle:
            return {
                "success": True,
                "status": STATUS_UNIQUE_MATCH,
                "product": _row_to_product(row),
            }

    # 3. EXPLICIT SKU-token match: the customer phrase contains an SKU as one
    #    of its words (e.g. "10 units of Industrial Cable CBL-210"). An
    #    explicit, valid SKU is the strongest signal of intent, so if any
    #    whitespace-delimited token EXACTLY equals a real catalogue SKU
    #    (case-insensitive, ignoring surrounding punctuation), resolve to that
    #    trusted product. This is NOT fuzzy matching: the token must equal an
    #    actual SKU from the authoritative products table, so an unknown or
    #    "valid-looking" but nonexistent SKU (e.g. "ZZZ-999") never resolves
    #    and no product/SKU is ever invented. Natural-language wording around
    #    the SKU therefore cannot prevent a valid SKU from resolving.
    query_tokens = {
        token.strip(_SKU_TOKEN_STRIP).lower()
        for token in needle.split()
    }
    query_tokens.discard("")
    sku_token_matches = [
        row for row in rows if row["sku"].lower() in query_tokens
    ]
    if len(sku_token_matches) == 1:
        return {
            "success": True,
            "status": STATUS_UNIQUE_MATCH,
            "product": _row_to_product(sku_token_matches[0]),
        }
    if len(sku_token_matches) > 1:
        # Multiple distinct valid SKUs named in one phrase: never guess.
        return {
            "success": True,
            "status": STATUS_MULTIPLE_MATCHES,
            "candidates": [_row_to_product(row) for row in sku_token_matches],
        }

    # 4. Substring match across name / description / category.
    matches = []
    for row in rows:
        haystacks = [
            (row["product_name"] or "").lower(),
            (row["description"] or "").lower(),
            (row["category"] or "").lower(),
        ]
        if any(needle in field for field in haystacks):
            matches.append(row)

    if not matches:
        return {"success": False, "status": STATUS_NO_MATCH, "query": query}

    if len(matches) == 1:
        return {
            "success": True,
            "status": STATUS_UNIQUE_MATCH,
            "product": _row_to_product(matches[0]),
        }

    # Several plausible matches: return candidates, never a silent first pick.
    return {
        "success": True,
        "status": STATUS_MULTIPLE_MATCHES,
        "candidates": [_row_to_product(row) for row in matches],
    }


def list_products():
    """
    Return the full catalogue as descriptive metadata (names/categories).

    This is for "what do you sell?"-style discovery. It does NOT include
    stock/availability; that remains owned by check_inventory.
    """
    rows = _fetch_all_products()
    return {
        "success": True,
        "count": len(rows),
        "products": [_row_to_product(row) for row in rows],
    }


def list_catalogue():
    """
    Trusted broad-catalogue listing for customer-facing "what do you sell?"
    style enquiries.

    Returns ONLY the customer-safe catalogue fields sourced from the
    authoritative products table: sku and product_name. It deliberately does
    NOT include category, list_price, or any stock/availability figure -
    category could encourage invented grouping wording, and stock stays with
    check_inventory. Neither is exposed in a broad catalogue response.

    The response the agent gives must be grounded ONLY in what this returns;
    the LLM must not add products or categories that are not present here.
    """
    rows = _fetch_all_products()
    products = [
        {
            "sku": row["sku"],
            "product_name": row["product_name"],
        }
        for row in rows
    ]
    return {
        "success": True,
        "count": len(products),
        "products": products,
    }
