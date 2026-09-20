"""
Trusted static FAQ provider for LionCity general enquiries.

WHY THIS MODULE EXISTS
----------------------
General/static questions (opening hours, location, payment methods, basic
delivery policy, quotation process, contact/company info) should be answered
from a controlled source, NOT invented by the LLM. This provider reads a
small static JSON file and returns a deterministic, structured result.

TRUST RULES (enforced here)
---------------------------
1. No fabricated business facts. If a real LionCity value is not yet known,
   its topic is flagged ``confirmed = false`` in faq.json and this provider
   returns a FOUND_UNCONFIRMED status. The placeholder text is NEVER returned
   as a trusted customer answer (the caller must not send it as fact).
2. Deterministic result contract via an explicit ``status`` field, so later
   SalesAgent integration never has to parse natural-language error strings:
        FOUND_CONFIRMED    -> a real answer is available
        FOUND_UNCONFIRMED  -> topic exists but value is not confirmed
        NOT_FOUND          -> no topic matched
3. Offline only. No network, embeddings, RAG, vector DB, or ML classifier.
4. FAQ is for general/static policy only. It must NOT be used to answer
   dynamic business questions (stock, price, delivery availability); those
   remain owned by the existing tools (check_inventory, get_customer_price,
   check_delivery). This provider simply has no such topics, and its keyword
   matcher deliberately does not resolve those questions to a topic.

MATCHING
--------
Lightweight and deterministic:
- an exact topic id (e.g. "operating_hours") matches directly;
- otherwise the free-text query is normalised and matched against each
  topic's alias list (longest alias first, so more specific phrases win).
No fuzzy/semantic matching.
"""

import json
import os
import re


# Deterministic status constants (the result contract).
STATUS_FOUND_CONFIRMED = "FOUND_CONFIRMED"
STATUS_FOUND_UNCONFIRMED = "FOUND_UNCONFIRMED"
STATUS_NOT_FOUND = "NOT_FOUND"


# Path to the static FAQ data (app/data/faq.json).
_FAQ_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "faq.json",
)


def _load_faq():
    """Load the static FAQ topics from disk. Pure file read, no network."""
    with open(_FAQ_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("topics", {})


def _normalise(text):
    """
    Lowercase, strip punctuation, and collapse whitespace so that
    "What time do you close?" and "what time do you close" match the same
    alias. Deterministic and simple.
    """
    if not isinstance(text, str):
        return ""
    lowered = text.lower()
    # Replace any non-alphanumeric run with a single space.
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    return cleaned.strip()


def _resolve_topic(query, topics):
    """
    Resolve a query string to a topic id, or None.

    Order of resolution:
    1. Exact topic id (e.g. the caller passed "operating_hours").
    2. Alias match: the normalised query equals or contains a normalised
       alias. Longer aliases are tried first so specific phrases beat generic
       single words (e.g. "opening hours" before "hours").
    """
    if not isinstance(query, str):
        return None

    raw = query.strip()

    # 1. Exact topic id.
    if raw in topics:
        return raw

    normalised_query = _normalise(raw)
    if not normalised_query:
        return None

    # Build (alias, topic_id) pairs, longest alias first.
    alias_pairs = []
    for topic_id, topic in topics.items():
        for alias in topic.get("aliases", []):
            alias_pairs.append((_normalise(alias), topic_id))
    alias_pairs.sort(key=lambda pair: len(pair[0]), reverse=True)

    for normalised_alias, topic_id in alias_pairs:
        if not normalised_alias:
            continue
        # Exact match, or the alias phrase appears within the query.
        if normalised_query == normalised_alias:
            return topic_id
        if normalised_alias in normalised_query:
            return topic_id

    return None


def lookup_faq(query):
    """
    Look up a general FAQ topic.

    Parameters
    ----------
    query : str
        A topic id (e.g. "operating_hours") or a free-text question
        (e.g. "What time do you close?").

    Returns
    -------
    dict with a deterministic contract:

        NOT FOUND:
            {"success": False, "status": "NOT_FOUND", "query": <query>}

        FOUND but UNCONFIRMED (placeholder value withheld):
            {"success": False, "status": "FOUND_UNCONFIRMED",
             "topic": <topic_id>}
            -> NOTE: 'answer' is intentionally NOT included, so the
               placeholder can never be sent to a customer as a fact.

        FOUND and CONFIRMED:
            {"success": True, "status": "FOUND_CONFIRMED",
             "topic": <topic_id>, "answer": <trusted answer>}
    """
    topics = _load_faq()
    topic_id = _resolve_topic(query, topics)

    if topic_id is None:
        return {
            "success": False,
            "status": STATUS_NOT_FOUND,
            "query": query,
        }

    topic = topics[topic_id]

    if topic.get("confirmed") is True:
        return {
            "success": True,
            "status": STATUS_FOUND_CONFIRMED,
            "topic": topic_id,
            "answer": topic.get("answer"),
        }

    # Found, but the value is not a confirmed business fact. Deliberately do
    # NOT return the placeholder text as an answer.
    return {
        "success": False,
        "status": STATUS_FOUND_UNCONFIRMED,
        "topic": topic_id,
    }
