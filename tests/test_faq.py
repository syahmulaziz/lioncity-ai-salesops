"""
Unit tests for the trusted FAQ provider (Task 15, Batch 2).

Covers confirmed/unconfirmed/not-found behaviour, alias resolution,
case-insensitivity, the no-network guarantee, the no-fabricated-facts
guarantee, and the rule that dynamic business questions (stock / pricing /
delivery availability) are NOT answered as static FAQ.

All tests are pure, offline, assertion-based (no LLM / network).
"""

import json
import os

from app.tools import faq
from app.tools.faq import (
    lookup_faq,
    STATUS_FOUND_CONFIRMED,
    STATUS_FOUND_UNCONFIRMED,
    STATUS_NOT_FOUND,
)


# ----------------------------------------------------------------------
# Helper: temporarily inject a confirmed topic by monkeypatching the loader.
# (We do NOT edit faq.json, so we don't fabricate real business facts on disk.)
# ----------------------------------------------------------------------

def _with_topics(monkeypatch, topics):
    monkeypatch.setattr(faq, "_load_faq", lambda: topics)


# ----------------------------------------------------------------------
# 1. Known confirmed FAQ returns confirmed answer
# ----------------------------------------------------------------------

def test_confirmed_faq_returns_answer(monkeypatch):
    _with_topics(monkeypatch, {
        "operating_hours": {
            "confirmed": True,
            "answer": "We are open Monday to Friday.",
            "aliases": ["opening hours", "what time do you close"],
        }
    })
    result = lookup_faq("What time do you close?")
    assert result["success"] is True
    assert result["status"] == STATUS_FOUND_CONFIRMED
    assert result["topic"] == "operating_hours"
    assert result["answer"] == "We are open Monday to Friday."


# ----------------------------------------------------------------------
# 2. Known unconfirmed FAQ -> UNCONFIRMED status, placeholder NOT exposed
# ----------------------------------------------------------------------

def test_unconfirmed_faq_hides_placeholder():
    # Uses the real faq.json, where operating_hours is unconfirmed.
    result = lookup_faq("What are your opening hours?")
    assert result["success"] is False
    assert result["status"] == STATUS_FOUND_UNCONFIRMED
    assert result["topic"] == "operating_hours"
    # The placeholder answer must NOT be present in the result at all.
    assert "answer" not in result


# ----------------------------------------------------------------------
# 3. Unknown FAQ returns NOT_FOUND
# ----------------------------------------------------------------------

def test_unknown_faq_returns_not_found():
    result = lookup_faq("Do you sponsor local football teams?")
    assert result["success"] is False
    assert result["status"] == STATUS_NOT_FOUND


# ----------------------------------------------------------------------
# 4. Operating-hours alias resolves correctly
# ----------------------------------------------------------------------

def test_operating_hours_aliases_resolve():
    for phrase in [
        "What time do you close?",
        "What are your opening hours?",
        "Are you open today?",
    ]:
        result = lookup_faq(phrase)
        assert result["topic"] == "operating_hours", phrase


# ----------------------------------------------------------------------
# 5. Location/address alias resolves correctly
# ----------------------------------------------------------------------

def test_location_aliases_resolve():
    for phrase in [
        "Where are you located?",
        "What's your address?",
    ]:
        result = lookup_faq(phrase)
        assert result["topic"] == "location", phrase


# ----------------------------------------------------------------------
# 6. Matching is case-insensitive
# ----------------------------------------------------------------------

def test_matching_is_case_insensitive():
    lower = lookup_faq("where are you located")
    upper = lookup_faq("WHERE ARE YOU LOCATED")
    assert lower["topic"] == "location"
    assert upper["topic"] == "location"


# ----------------------------------------------------------------------
# 7. FAQ provider does not require network access
# ----------------------------------------------------------------------

def test_faq_provider_offline(monkeypatch):
    # Any accidental network use would fail; simulate by banning socket.
    import socket

    def _no_network(*args, **kwargs):
        raise AssertionError("FAQ provider attempted network access")

    monkeypatch.setattr(socket, "socket", _no_network)
    result = lookup_faq("opening hours")
    assert result["topic"] == "operating_hours"


# ----------------------------------------------------------------------
# 8. FAQ data contains no fabricated CONFIRMED business facts
# ----------------------------------------------------------------------

def test_no_fabricated_confirmed_facts_on_disk():
    faq_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "app", "data", "faq.json"
    )
    with open(faq_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    for topic_id, topic in data["topics"].items():
        # Until the team confirms real values, everything must be unconfirmed.
        assert topic["confirmed"] is False, topic_id
        # Placeholder answers must be clearly marked, not realistic facts.
        assert "UNCONFIRMED" in topic["answer"], topic_id


# ----------------------------------------------------------------------
# 9-11. Dynamic business questions must NOT resolve to a static FAQ topic
# ----------------------------------------------------------------------

def test_dynamic_stock_question_not_faq():
    result = lookup_faq("Do you have 100 drills?")
    assert result["status"] == STATUS_NOT_FOUND


def test_dynamic_pricing_question_not_faq():
    result = lookup_faq("How much are 100 drills?")
    assert result["status"] == STATUS_NOT_FOUND


def test_dynamic_delivery_availability_not_faq():
    result = lookup_faq("Can you deliver to Jurong on Tuesday?")
    assert result["status"] == STATUS_NOT_FOUND
