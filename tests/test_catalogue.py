"""
ISSUE 2 regression - broad product-catalogue grounding, plus the G05
Person 1 grounding-fix regressions.

Broad "what do you sell?" enquiries must use the trusted list_products tool
(backed by the authoritative products table), must NOT invent generic
categories, and must NOT expose stock quantities. Specific-product questions
must still go through find_product -> check_inventory.

G05 hardens this further: the CUSTOMER-FACING final reply itself (not just
the tool-result payload) is now rendered DETERMINISTICALLY from the trusted
list_catalogue() result via SalesAgent._finalize_customer_response(). A
hostile/careless model draft that adds products, categories, stock
quantities or other unverified catalogue facts must never have those
additions reach the customer - only the trusted SKU/product_name pairs may
appear.

Offline, scripted mock Claude. Product data comes from the seeded runtime DB
(CBL-210 Industrial Cable, ADP-120 Industrial Adapter, TIE-100 Heavy Duty
Cable Tie) - the tests assert against whatever the DB returns, not a hard-coded
list, so a data change flows through without prompt/test edits to the values.
"""

import json

import pytest

from tests._agent_harness import build_agent
from app.tools.products import list_catalogue, list_products
from app.tools import faq as faq_module


# ----------------------------------------------------------------------
# list_catalogue: customer-safe fields only (sku, name, category) - no
# price, no stock. Sourced from the authoritative products table.
# ----------------------------------------------------------------------

def test_list_catalogue_returns_trusted_products():
    result = list_catalogue()
    assert result["success"] is True
    skus = {p["sku"] for p in result["products"]}
    # Current seeded catalogue (asserted from the DB, not hard-coded in code).
    assert {"CBL-210", "ADP-120", "TIE-100"}.issubset(skus)
    names = {p["product_name"] for p in result["products"]}
    assert "Industrial Cable" in names
    assert "Industrial Adapter" in names
    assert "Heavy Duty Cable Tie" in names


def test_list_catalogue_exposes_only_sku_and_name():
    # Customer-safe minimum: exactly sku + product_name. No category, price,
    # or stock.
    for p in list_catalogue()["products"]:
        assert set(p.keys()) == {"sku", "product_name"}
        assert "category" not in p
        assert "list_price" not in p
        assert "available_quantity" not in p
        assert "stock" not in p


def test_list_catalogue_matches_authoritative_source_count():
    # Same authoritative source as the rest of product tooling.
    assert list_catalogue()["count"] == list_products()["count"]


# ----------------------------------------------------------------------
# Agent-level: broad catalogue enquiry uses list_products and grounds the
# reply in returned data (no invented categories, no stock).
# ----------------------------------------------------------------------

def _catalogue_payloads(agent):
    out = []
    for m in agent.messages:
        if m["role"] == "user" and isinstance(m["content"], list):
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    try:
                        p = json.loads(b["content"])
                    except Exception:
                        continue
                    if isinstance(p, dict) and "products" in p and "count" in p:
                        out.append(p)
    return out


# 1. broad enquiry invokes trusted catalogue tool
def test_broad_enquiry_uses_list_products(monkeypatch):
    script = [
        [("list_products", {})],
        "We stock Industrial Cable (CBL-210), Industrial Adapter (ADP-120) "
        "and Heavy Duty Cable Tie (TIE-100).",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Hi, what products do you sell?")
    assert "list_products" in tools
    payloads = _catalogue_payloads(agent)
    assert payloads
    skus = {p["sku"] for p in payloads[-1]["products"]}
    assert {"CBL-210", "ADP-120", "TIE-100"}.issubset(skus)


# 2. tool result carries the current trusted products/SKUs
def test_catalogue_tool_result_contains_seeded_products(monkeypatch):
    script = [[("list_products", {})], "Here's what we carry."]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("What do you carry?")
    payload = _catalogue_payloads(agent)[-1]
    pairs = {(p["sku"], p["product_name"]) for p in payload["products"]}
    assert ("CBL-210", "Industrial Cable") in pairs
    assert ("ADP-120", "Industrial Adapter") in pairs
    assert ("TIE-100", "Heavy Duty Cable Tie") in pairs


# 3. trusted catalogue does NOT contain invented generic categories
def test_catalogue_has_no_invented_categories(monkeypatch):
    script = [[("list_products", {})], "Listing products."]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("What products are available?")
    payload = _catalogue_payloads(agent)[-1]
    blob = json.dumps(payload).lower()
    for invented in ["construction materials", "safety equipment",
                     "hardware and tools", "packaging materials",
                     "industrial supplies"]:
        assert invented not in blob


# 4. broad catalogue response does NOT expose exact stock quantities
def test_catalogue_tool_result_has_no_stock(monkeypatch):
    script = [[("list_products", {})], "Listing."]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("Show me your products.")
    payload = _catalogue_payloads(agent)[-1]
    for p in payload["products"]:
        assert "available_quantity" not in p
        assert "stock" not in p
        assert "list_price" not in p
        assert "category" not in p          # category no longer exposed


# 5. specific product availability still follows find_product -> check_inventory
def test_specific_product_uses_find_then_inventory(monkeypatch):
    script = [
        [("find_product", {"query": "Industrial Cable"})],
        [("check_inventory", {"sku": "CBL-210", "requested_quantity": 10})],
        "Yes, available.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("Do you have 10 industrial cable?")
    assert tools.index("find_product") < tools.index("check_inventory")
    assert "list_products" not in tools


# 6. unknown/specific product behaviour remains safe (no invented SKU)
def test_unknown_specific_product_safe(monkeypatch):
    script = [
        [("find_product", {"query": "Super Mega Drill X9000"})],
        "I couldn't find that product.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("Do you sell the Super Mega Drill X9000?")
    assert agent.enquiry.product_sku is None
    assert "check_inventory" not in tools


# 7. catalogue is data-driven: changing the DB changes the tool output with
#    no code/prompt edit. Prove by asserting list_catalogue reflects a live
#    DB read (temporarily via monkeypatching the fetch layer - does NOT touch
#    the real DB file).
def test_catalogue_is_data_driven(monkeypatch):
    import app.tools.products as products_mod

    class _Row(dict):
        def __getitem__(self, k):
            return dict.__getitem__(self, k)

    fake_rows = [
        _Row(sku="NEW-001", product_name="New Widget", description="d",
             category="Widgets", list_price=9.99),
    ]
    monkeypatch.setattr(products_mod, "_fetch_all_products", lambda: fake_rows)
    result = products_mod.list_catalogue()
    assert result["count"] == 1
    assert result["products"][0]["sku"] == "NEW-001"
    assert result["products"][0]["product_name"] == "New Widget"
    # still customer-safe (no price/category leaked even for the new row)
    assert "list_price" not in result["products"][0]
    assert "category" not in result["products"][0]


# ----------------------------------------------------------------------
# G05. DETERMINISTIC BROAD-CATALOGUE FINAL OUTPUT: the CUSTOMER-FACING
# reply, not just the tool payload, must be grounded in the trusted
# list_catalogue() result. A hostile/careless draft's invented additions
# must never reach the customer.
# ----------------------------------------------------------------------

def test_hostile_catalogue_invented_product_removed(monkeypatch):
    script = [
        [("list_products", {})],
        # Hostile draft adds a product that was never in the trusted result.
        "We sell industrial cables, adapters, cable ties, generators "
        "and power tools.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("What products do you sell?")
    reply = result["response"].lower()
    assert "generators" not in reply
    assert "power tools" not in reply
    # Trusted products are still represented (by SKU/name).
    assert "cbl-210" in reply
    assert "adp-120" in reply
    assert "tie-100" in reply


def test_hostile_catalogue_invented_category_removed(monkeypatch):
    script = [
        [("list_products", {})],
        "We carry a range of hardware and tools, safety equipment, "
        "and packaging materials.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("What do you carry?")
    reply = result["response"].lower()
    for invented in ["hardware and tools", "safety equipment",
                     "packaging materials"]:
        assert invented not in reply


def test_hostile_catalogue_invented_stock_removed(monkeypatch):
    script = [
        [("list_products", {})],
        "We have 486 units of Industrial Cable and 121 Industrial Adapters "
        "in stock right now.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Show me your products.")
    reply = result["response"]
    assert "486" not in reply
    assert "121" not in reply


def test_legitimate_catalogue_reply_contains_all_trusted_pairs(monkeypatch):
    script = [
        [("list_products", {})],
        "Here's our full range of quality industrial products for you!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("What products do you sell?")
    reply = result["response"]
    assert "CBL-210" in reply and "Industrial Cable" in reply
    assert "ADP-120" in reply and "Industrial Adapter" in reply
    assert "TIE-100" in reply and "Heavy Duty Cable Tie" in reply


def test_specific_product_response_not_replaced_by_catalogue_renderer(
    monkeypatch,
):
    # find_product / check_inventory must NEVER trigger the broad-catalogue
    # renderer - the specific-product reply must be Claude's own text,
    # unmodified by this patch.
    script = [
        [("find_product", {"query": "Industrial Cable"})],
        [("check_inventory", {"sku": "CBL-210", "requested_quantity": 10})],
        "Yes, we can fulfil 10 units of Industrial Cable.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Do you have 10 industrial cable?")
    assert result["response"] == (
        "Yes, we can fulfil 10 units of Industrial Cable."
    )
    assert "list_products" not in tools
    assert agent._catalogue_result_this_cycle is None


def test_next_unrelated_turn_not_replaced_by_stale_catalogue(monkeypatch):
    # A broad catalogue lookup in turn 1 must NOT leak into an unrelated
    # turn 2 response (response-cycle grounding is reset every send()).
    script = [
        [("list_products", {})],
        "Here you go!",
        "Thanks for your interest - anything else I can help with?",
    ]
    agent, tools = build_agent(monkeypatch, script)
    r1 = agent.send("What products do you sell?")
    assert "CBL-210" in r1["response"]

    r2 = agent.send("Actually, never mind, thanks.")
    assert r2["response"] == (
        "Thanks for your interest - anything else I can help with?"
    )
    assert "CBL-210" not in r2["response"]



# ======================================================================
# MULTI-INTENT SAFETY (pre-commit review follow-up).
#
# The shared finalizer discards Claude's ENTIRE draft whenever the broad
# catalogue section is rendered (G05), which previously also silently
# dropped any OTHER legitimate intent covered in that same draft (a
# specific-product lookup, an FAQ answer). These regressions restore that
# legitimate secondary information from ITS OWN trusted per-cycle snapshot
# - never by re-including Claude's discarded draft text (which could carry
# invented categories/stock/products, exactly what G05 removes).
# ======================================================================

def _last_assistant_text(agent):
    """Flatten the final stored assistant message to plain text."""
    for m in reversed(agent.messages):
        if m["role"] != "assistant":
            continue
        content = m["content"]
        if isinstance(content, str):
            return content
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif getattr(b, "type", None) == "text":
                parts.append(getattr(b, "text", ""))
        return "\n".join(parts)
    return None


def _with_faq_topics(monkeypatch, topics):
    monkeypatch.setattr(faq_module, "_load_faq", lambda: topics)


# Scenario C: CATALOGUE + SPECIFIC PRODUCT - the specific-product answer
# must survive even though the catalogue section is being rendered from
# trusted state.
def test_multi_intent_catalogue_and_specific_product_both_present(
    monkeypatch,
):
    script = [
        [
            ("list_products", {}),
            ("find_product", {"query": "Industrial Cable"}),
        ],
        # Hostile/careless draft adds unrequested category/stock facts for
        # the specific product - these must never reach the customer.
        "Here's our catalogue! The Industrial Cable (Electrical category) "
        "has 486 units in stock at S$12 each.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send(
        "What do you sell, and do you have Industrial Cable?"
    )
    reply = result["response"]
    # Trusted catalogue grounding still applies (G05 unaffected).
    assert "CBL-210" in reply and "Industrial Cable" in reply
    assert "ADP-120" in reply
    assert "TIE-100" in reply
    # The LEGITIMATE specific-product answer (trusted sku/name only) is
    # restored...
    assert "That matches Industrial Cable (CBL-210)" in reply
    # ...but unrequested category/stock/price facts never appear.
    assert "Electrical" not in reply
    assert "486" not in reply
    assert "S$12" not in reply
    stored = _last_assistant_text(agent)
    assert stored == reply


# Scenario C (tool-order independence): find_product called BEFORE
# list_products must produce the identical composed result.
def test_multi_intent_catalogue_and_specific_product_reverse_tool_order(
    monkeypatch,
):
    script = [
        [
            ("find_product", {"query": "Industrial Cable"}),
            ("list_products", {}),
        ],
        "The Industrial Cable is great, and here's our full catalogue.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send(
        "Do you have Industrial Cable, and what else do you sell?"
    )
    reply = result["response"]
    assert "CBL-210" in reply
    assert "That matches Industrial Cable (CBL-210)" in reply


# Negative control: a MULTIPLE_MATCHES / NO_MATCH find_product result must
# NOT trigger the specific-product renderer (no unique product to name).
def test_multi_intent_catalogue_with_no_match_specific_product(monkeypatch):
    script = [
        [
            ("list_products", {}),
            ("find_product", {"query": "Super Mega Drill X9000"}),
        ],
        "Here's our catalogue. I couldn't find that specific product.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send(
        "What do you sell, and do you have a Super Mega Drill X9000?"
    )
    reply = result["response"]
    assert "CBL-210" in reply
    assert "That matches" not in reply


# Scenario D: CATALOGUE + CONFIRMED FAQ - the FAQ answer must survive
# alongside the grounded catalogue section.
def test_multi_intent_catalogue_and_confirmed_faq(monkeypatch):
    _with_faq_topics(monkeypatch, {
        "operating_hours": {
            "confirmed": True,
            "answer": "We are open Monday to Friday, 9am to 6pm.",
            "aliases": ["operating hours", "what time do you open"],
        }
    })
    script = [
        [
            ("list_products", {}),
            ("lookup_faq", {"query": "operating hours"}),
        ],
        # Hostile/careless draft invents a different (wrong) confirmed hours
        # claim - this must never reach the customer.
        "Here's our catalogue! We're open 24/7, every day of the year.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("What do you sell, and what are your hours?")
    reply = result["response"]
    assert "CBL-210" in reply
    # The LEGITIMATE confirmed FAQ answer (trusted) is restored...
    assert "Monday to Friday, 9am to 6pm" in reply
    # ...but the model's invented (wrong) hours claim never appears.
    assert "24/7" not in reply
    stored = _last_assistant_text(agent)
    assert stored == reply


# Scenario E: CATALOGUE + UNCONFIRMED FAQ - safe withholding must be
# preserved; the unconfirmed placeholder must never be surfaced as fact,
# and the model's own invented answer must not survive either.
def test_multi_intent_catalogue_and_unconfirmed_faq_withholds(monkeypatch):
    script = [
        [
            ("list_products", {}),
            ("lookup_faq", {"query": "operating hours"}),
        ],
        # operating_hours is UNCONFIRMED in the real faq.json; model
        # nonetheless invents a specific answer.
        "Here's our catalogue! We're open 9am to 5pm daily.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("What do you sell, and what are your hours?")
    reply = result["response"]
    assert "CBL-210" in reply
    # Model-invented hours must not appear.
    assert "9am to 5pm" not in reply
    # No placeholder/UNCONFIRMED text leaks either.
    assert "UNCONFIRMED" not in reply


# Negative control: an FAQ NOT_FOUND result must not add any FAQ section.
def test_multi_intent_catalogue_and_faq_not_found(monkeypatch):
    script = [
        [
            ("list_products", {}),
            ("lookup_faq", {"query": "totally unknown topic xyz"}),
        ],
        "Here's our catalogue. Sorry, I don't have that information.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("What do you sell, and some unrelated question?")
    reply = result["response"]
    assert "CBL-210" in reply


# Tool-order independence for catalogue + FAQ.
def test_multi_intent_catalogue_and_confirmed_faq_reverse_tool_order(
    monkeypatch,
):
    _with_faq_topics(monkeypatch, {
        "operating_hours": {
            "confirmed": True,
            "answer": "We are open Monday to Friday, 9am to 6pm.",
            "aliases": ["operating hours"],
        }
    })
    script = [
        [
            ("lookup_faq", {"query": "operating hours"}),
            ("list_products", {}),
        ],
        "We're open Monday to Friday, and here's our catalogue.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("What are your hours, and what do you sell?")
    reply = result["response"]
    assert "CBL-210" in reply
    assert "Monday to Friday, 9am to 6pm" in reply


# G05 regression guard: re-running a prior hostile catalogue test with an
# ADDITIONAL specific-product lookup in the SAME cycle must still block the
# invented product/category/stock claims exactly as before.
def test_hostile_catalogue_invented_product_still_removed_with_specific_product(
    monkeypatch,
):
    script = [
        [
            ("list_products", {}),
            ("find_product", {"query": "Industrial Cable"}),
        ],
        "We sell industrial cables, adapters, cable ties, generators and "
        "power tools. The cable is in the Electrical category.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send(
        "What do you sell, and do you have Industrial Cable?"
    )
    reply = result["response"].lower()
    assert "generators" not in reply
    assert "power tools" not in reply
    assert "electrical" not in reply
    assert "cbl-210" in reply
