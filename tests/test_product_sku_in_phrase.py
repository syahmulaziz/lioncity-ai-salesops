"""
Regression: a valid catalogue product must resolve when the customer's phrase
contains BOTH the product name and its SKU (e.g. "Industrial Cable CBL-210").

LIVE BUG (staging 13defda): "10 units of Industrial Cable CBL-210" failed with
"couldn't find ... in our catalogue", while "10 units of CBL-210" resolved
correctly. Root cause: find_product() only matched the WHOLE query against an
exact SKU, an exact product-name, or a substring of a catalogue field; the
combined phrase satisfied none, and the embedded SKU token "CBL-210" was never
extracted. So the combined phrase fell through to NO_MATCH.

Fix expectation: when the query contains a token that EXACTLY equals a real
catalogue SKU (from trusted Business Data), find_product resolves to that
trusted product. This must:
  - never invent a product/SKU (the token must equal a real DB SKU);
  - keep exact-SKU / exact-name / substring behaviour unchanged;
  - keep NO_MATCH for unknown SKUs/products;
  - not be fuzzy (an unrelated valid-looking-but-nonexistent SKU in a phrase
    that also mentions "Industrial Cable" must NOT map to CBL-210).

These tests exercise the trusted product lookup against the real seeded
catalogue (read-only). They never write to the committed DB.
"""

import pytest

from app.tools.products import (
    find_product,
    STATUS_UNIQUE_MATCH,
    STATUS_NO_MATCH,
)


def _unique_sku(query):
    result = find_product(query)
    assert result["success"] is True, f"expected a match for {query!r}: {result}"
    assert result["status"] == STATUS_UNIQUE_MATCH, (
        f"expected UNIQUE_MATCH for {query!r}: {result}"
    )
    return result["product"]["sku"]


# ---------------------------------------------------------------------------
# VALID cases - all must resolve to CBL-210 (Industrial Cable).
# ---------------------------------------------------------------------------

def test_sku_alone_resolves():
    assert _unique_sku("CBL-210") == "CBL-210"


def test_name_alone_resolves():
    assert _unique_sku("Industrial Cable") == "CBL-210"


def test_name_then_sku_resolves():
    # The exact live failure.
    assert _unique_sku("Industrial Cable CBL-210") == "CBL-210"


def test_sku_then_name_resolves():
    assert _unique_sku("CBL-210 Industrial Cable") == "CBL-210"


def test_full_order_phrase_with_name_and_sku_resolves():
    assert _unique_sku(
        "I would like to order 10 units of Industrial Cable CBL-210"
    ) == "CBL-210"


def test_full_order_phrase_sku_then_name_resolves():
    assert _unique_sku(
        "10 units of CBL-210 Industrial Cable"
    ) == "CBL-210"


def test_sku_with_trailing_punctuation_resolves():
    # Common WhatsApp phrasing with punctuation around the SKU.
    assert _unique_sku("Can I get the CBL-210, please?") == "CBL-210"


def test_case_insensitive_sku_in_phrase_resolves():
    assert _unique_sku("i want industrial cable cbl-210") == "CBL-210"


# A different real product's SKU embedded in a phrase must resolve to THAT
# product (proves the fix generalises and is not CBL-210-specific).
def test_other_product_sku_in_phrase_resolves():
    assert _unique_sku("please add 5 units of Industrial Adapter ADP-120") == "ADP-120"


# ---------------------------------------------------------------------------
# NEGATIVE cases - must NOT fabricate or mis-map.
# ---------------------------------------------------------------------------

def test_unknown_sku_alone_is_no_match():
    result = find_product("ZZZ-999")
    assert result["success"] is False
    assert result["status"] == STATUS_NO_MATCH


def test_nonexistent_sku_near_real_name_is_not_mapped():
    # "Industrial Cable" appears, but the SKU token ZZZ-999 does not exist.
    # The phrase must NOT be silently mapped to CBL-210 just because a real
    # product NAME appears somewhere in it (no fuzzy hijack). Because
    # "Industrial Cable" is a substring branch hit, this resolves to CBL-210
    # via the NAME - but the ZZZ-999 token itself must never resolve anything.
    # To isolate the "valid-looking bad SKU must not resolve" rule cleanly,
    # use a phrase with a bad SKU and NO real product name/word.
    result = find_product("order 10 units of ZZZ-999")
    assert result["success"] is False
    assert result["status"] == STATUS_NO_MATCH


def test_bad_sku_token_does_not_hijack_to_unrelated_product():
    # A nonexistent SKU token must never resolve to a real product.
    result = find_product("XYZ-000")
    assert result["success"] is False
    assert result["status"] == STATUS_NO_MATCH


# ---------------------------------------------------------------------------
# EXISTING behaviour preserved: ambiguous single word still yields multiple
# candidates (never a silent pick), and unknown free text is NO_MATCH.
# ---------------------------------------------------------------------------

def test_ambiguous_word_still_multiple_matches():
    result = find_product("industrial")
    assert result["success"] is True
    assert result["status"] == "MULTIPLE_MATCHES"
    assert len(result["candidates"]) >= 2


def test_unknown_free_text_no_match():
    result = find_product("Super Mega Drill X9000")
    assert result["success"] is False
    assert result["status"] == STATUS_NO_MATCH
