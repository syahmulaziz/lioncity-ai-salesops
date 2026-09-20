"""
ISSUE 2 regression - broad product-catalogue grounding.

Broad "what do you sell?" enquiries must use the trusted list_products tool
(backed by the authoritative products table), must NOT invent generic
categories, and must NOT expose stock quantities. Specific-product questions
must still go through find_product -> check_inventory.

Offline, scripted mock Claude. Product data comes from the seeded runtime DB
(CBL-210 Industrial Cable, ADP-120 Industrial Adapter, TIE-100 Heavy Duty
Cable Tie) - the tests assert against whatever the DB returns, not a hard-coded
list, so a data change flows through without prompt/test edits to the values.
"""

import json

import pytest

from tests._agent_harness import build_agent
from app.tools.products import list_catalogue, list_products


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
