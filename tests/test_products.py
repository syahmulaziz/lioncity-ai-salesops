"""
Unit tests for trusted product discovery (Task 16, Batch 2).

Tests run against the REAL demo catalogue in data/lioncity.db:
    CBL-210  Industrial Cable    (Electrical)
    ADP-120  Industrial Adapter  (Electrical)
    TIE-100  Heavy Duty Cable Tie (Accessories)

Covers exact SKU / name lookups, case-insensitivity, substring matching,
description matching, MULTIPLE_MATCHES (no silent first pick), NO_MATCH /
no invented SKU, DB-sourced identity, and the separation from
inventory / pricing / delivery.

All tests are offline (local SQLite only), deterministic, assertion-based.
"""

from app.tools.products import (
    find_product,
    list_products,
    STATUS_UNIQUE_MATCH,
    STATUS_MULTIPLE_MATCHES,
    STATUS_NO_MATCH,
)


# ----------------------------------------------------------------------
# 1. Exact SKU lookup
# ----------------------------------------------------------------------

def test_exact_sku_lookup():
    result = find_product("CBL-210")
    assert result["status"] == STATUS_UNIQUE_MATCH
    assert result["product"]["sku"] == "CBL-210"
    assert result["product"]["product_name"] == "Industrial Cable"


# ----------------------------------------------------------------------
# 2. SKU matching is case-insensitive
# ----------------------------------------------------------------------

def test_sku_lookup_case_insensitive():
    result = find_product("cbl-210")
    assert result["status"] == STATUS_UNIQUE_MATCH
    assert result["product"]["sku"] == "CBL-210"


# ----------------------------------------------------------------------
# 3. Exact product-name lookup
# ----------------------------------------------------------------------

def test_exact_product_name_lookup():
    result = find_product("Heavy Duty Cable Tie")
    assert result["status"] == STATUS_UNIQUE_MATCH
    assert result["product"]["sku"] == "TIE-100"


# ----------------------------------------------------------------------
# 4. Product-name lookup is case-insensitive
# ----------------------------------------------------------------------

def test_product_name_lookup_case_insensitive():
    result = find_product("industrial adapter")
    assert result["status"] == STATUS_UNIQUE_MATCH
    assert result["product"]["sku"] == "ADP-120"


# ----------------------------------------------------------------------
# 5. Unique substring query returns the correct trusted product
# ----------------------------------------------------------------------

def test_unique_substring_match():
    # "adapter" appears only in ADP-120.
    result = find_product("adapter")
    assert result["status"] == STATUS_UNIQUE_MATCH
    assert result["product"]["sku"] == "ADP-120"


# ----------------------------------------------------------------------
# 6. Description matching works (description exists in the real schema)
# ----------------------------------------------------------------------

def test_description_matching():
    # "electrical" appears in CBL-210's description ("...electrical cable")
    # but NOT in ADP-120's description ("Industrial power adapter").
    # It does appear in both categories ("Electrical"), so this also
    # exercises category matching -> expect multiple matches here.
    result = find_product("electrical")
    assert result["status"] == STATUS_MULTIPLE_MATCHES
    skus = {c["sku"] for c in result["candidates"]}
    assert skus == {"CBL-210", "ADP-120"}


# ----------------------------------------------------------------------
# 7. Multiple plausible matches return MULTIPLE_MATCHES
# ----------------------------------------------------------------------

def test_multiple_matches():
    # "industrial" appears in both "Industrial Cable" and "Industrial
    # Adapter" names (and TIE-100's description "...industrial use").
    result = find_product("industrial")
    assert result["status"] == STATUS_MULTIPLE_MATCHES
    assert len(result["candidates"]) >= 2


# ----------------------------------------------------------------------
# 8. Multiple matches are not silently reduced to the first result
# ----------------------------------------------------------------------

def test_multiple_matches_not_reduced_to_first():
    result = find_product("industrial")
    assert result["status"] == STATUS_MULTIPLE_MATCHES
    # No single "product" key when it's ambiguous.
    assert "product" not in result
    assert "candidates" in result
    skus = {c["sku"] for c in result["candidates"]}
    # At least the two "Industrial ..." named products are present.
    assert {"CBL-210", "ADP-120"}.issubset(skus)


# ----------------------------------------------------------------------
# 9. Unknown product returns NO_MATCH
# ----------------------------------------------------------------------

def test_unknown_product_no_match():
    result = find_product("Super Mega Drill X9000")
    assert result["success"] is False
    assert result["status"] == STATUS_NO_MATCH


# ----------------------------------------------------------------------
# 10. Unknown product does not generate an SKU
# ----------------------------------------------------------------------

def test_unknown_product_generates_no_sku():
    result = find_product("Super Mega Drill X9000")
    assert "product" not in result
    assert "candidates" not in result
    assert "sku" not in result


# ----------------------------------------------------------------------
# 11. Returned unique product identity comes from the database
# ----------------------------------------------------------------------

def test_unique_identity_comes_from_database():
    # Compare against the authoritative catalogue via list_products.
    catalogue = list_products()["products"]
    catalogue_skus = {p["sku"] for p in catalogue}

    result = find_product("Industrial Cable")
    assert result["status"] == STATUS_UNIQUE_MATCH
    assert result["product"]["sku"] in catalogue_skus


# ----------------------------------------------------------------------
# 12-14. Discovery does NOT expose stock / customer price / delivery
# ----------------------------------------------------------------------

def test_discovery_does_not_return_inventory():
    result = find_product("CBL-210")
    product = result["product"]
    assert "available_quantity" not in product
    assert "stock" not in product
    assert "can_fulfil" not in product


def test_discovery_does_not_return_customer_price():
    result = find_product("CBL-210")
    product = result["product"]
    # list_price is descriptive catalogue metadata only; a customer/contract
    # price must never appear here.
    assert "unit_price" not in product
    assert "customer_price" not in product
    assert "price_source" not in product
    assert "subtotal" not in product


def test_discovery_does_not_return_delivery_info():
    result = find_product("CBL-210")
    product = result["product"]
    assert "delivery_fee" not in product
    assert "delivery_area" not in product
    assert "remaining_capacity" not in product


# ----------------------------------------------------------------------
# 15. Product search uses authoritative DB data, not a duplicated catalogue
# ----------------------------------------------------------------------

def test_uses_authoritative_data_not_hardcoded():
    catalogue = list_products()
    # The tool reflects exactly the 3 seeded demo products from the DB.
    assert catalogue["count"] == 3
    skus = {p["sku"] for p in catalogue["products"]}
    assert skus == {"CBL-210", "ADP-120", "TIE-100"}
