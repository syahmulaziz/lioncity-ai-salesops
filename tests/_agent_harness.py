"""
Shared offline test harness for SalesAgent orchestration tests (Batch 4).

Provides a scripted mock Claude client that returns predetermined tool_use
sequences and a final text response, plus a SalesAgent factory that records
exactly which tools were invoked. No live Claude / WhatsApp / network.

This is a TEST-ONLY helper. It registers stub `anthropic` / `dotenv` modules
(absent in this offline sandbox) before importing app.agent, so no application
code needs changing.
"""

import sys
import types

# --- Offline stubs for packages not installed in the sandbox. ---
# app.agent -> app.claude_client imports these third-party packages at module
# load. They are not installed in this offline sandbox and these tests never
# make a real LLM/HTTP call, so we register minimal stubs BEFORE importing
# app.agent. This is TEST-ONLY scaffolding; no application code is modified.
if "anthropic" not in sys.modules:
    _a = types.ModuleType("anthropic")
    _a.Anthropic = object
    sys.modules["anthropic"] = _a
if "dotenv" not in sys.modules:
    _d = types.ModuleType("dotenv")
    _d.load_dotenv = lambda *a, **k: False
    sys.modules["dotenv"] = _d
if "requests" not in sys.modules:
    # Staging's new LLM gateway client (app/claude_client.py) imports
    # `requests` at module load. Stub it so the module imports offline; the
    # scripted mock client is used instead of any real HTTP client.
    _r = types.ModuleType("requests")

    def _no_http(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("Live HTTP call attempted in an offline test")

    _r.get = _no_http
    _r.post = _no_http
    _r.request = _no_http

    class _RequestException(Exception):
        pass

    _r.RequestException = _RequestException
    _r.exceptions = types.SimpleNamespace(RequestException=_RequestException)
    sys.modules["requests"] = _r

from app import agent as agent_module  # noqa: E402
from app.agent import SalesAgent  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal block/response shapes matching what SalesAgent.send() consumes.
# ---------------------------------------------------------------------------

class TextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class ToolUseBlock:
    _counter = 0

    def __init__(self, name, input):
        ToolUseBlock._counter += 1
        self.type = "tool_use"
        self.name = name
        self.input = input
        self.id = f"tu_{ToolUseBlock._counter}"


class _Response:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class ScriptedClaudeClient:
    """
    Returns a predetermined sequence of "turns".

    Each scripted turn is either:
      - a list of (tool_name, tool_input) tuples  -> a tool_use response, OR
      - a string                                  -> a final text response.

    The harness records every tool name the agent asked to run.
    """

    def __init__(self, script, tool_calls_sink):
        self._script = list(script)
        self._i = 0
        self._tool_calls = tool_calls_sink
        self.messages = self  # so client.messages.create(...) works

    def create(self, *args, **kwargs):
        if self._i >= len(self._script):
            # Safety net: end the conversation.
            return _Response([TextBlock("(end)")], "end_turn")

        step = self._script[self._i]
        self._i += 1

        if isinstance(step, str):
            return _Response([TextBlock(step)], "end_turn")

        # step is a list of (name, input) tool calls.
        blocks = []
        for name, tool_input in step:
            self._tool_calls.append(name)
            blocks.append(ToolUseBlock(name, tool_input))
        return _Response(blocks, "tool_use")


def build_agent(monkeypatch, script, phone="+6580000000"):
    """
    Create a SalesAgent whose Claude client is the scripted mock.

    Returns (agent, tool_calls) where tool_calls is a list that accumulates
    every tool name the agent invoked, in order.
    """
    tool_calls = []

    def _fake_client():
        return ScriptedClaudeClient(script, tool_calls)

    monkeypatch.setattr(agent_module, "get_claude_client", _fake_client)

    # DB SAFETY: agent flows may now trigger an automatic HIGH_PRIORITY sales
    # handoff, which calls app.handoff.log_sales_event -> writes to the shared
    # SQLite DB. Default the logger to a no-op so offline agent tests never
    # mutate the committed data/lioncity.db. Tests that need to COUNT handoff
    # events re-patch app.handoff.log_sales_event AFTER calling build_agent.
    monkeypatch.setattr("app.handoff.log_sales_event", lambda **kw: {"success": True})

    agent = SalesAgent(phone=phone)
    return agent, tool_calls


# Default commercial-policy values, matching PR #2's seed_commercial_policies()
# defaults in app/database.py. Tests exercise the REAL PR #2 authority logic
# against these controlled values.
DEFAULT_TEST_COMMERCIAL_POLICIES = [
    {"policy_key": "MAX_QUANTITY_PER_SKU", "policy_value": 500,
     "description": "Maximum quantity per SKU the AI can approve"},
    {"policy_key": "MAX_ORDER_VALUE", "policy_value": 10000,
     "description": "Maximum order value the AI can approve without human approval"},
    {"policy_key": "MAX_DISCOUNT_PERCENT", "policy_value": 5,
     "description": "Maximum discount percentage the AI can approve"},
]


def patch_commercial_policies(monkeypatch, policies=None):
    """
    Provide controlled commercial-policy state to the PR #2 authority path
    WITHOUT touching the shared runtime DB (data/lioncity.db).

    PR #2's app/tools/discount.py and app/tools/commercial_policy.py both
    resolve limits via app.database.get_commercial_policies(). The existing
    runtime test DB predates PR #2 and has no commercial_policies table, so
    that lookup raises. We patch the lookup AT THE LOCATIONS WHERE THE CODE
    UNDER TEST ACTUALLY CALLS IT (each module imported the symbol by name),
    returning controlled data. The real _get_discount_limit() /
    check_discount_authority() / evaluate_commercial_authority() decision
    logic still runs — we do NOT bypass the authority decision.
    """
    data = list(policies) if policies is not None else list(
        DEFAULT_TEST_COMMERCIAL_POLICIES
    )

    def _fake_get_commercial_policies():
        return [dict(p) for p in data]

    # discount.py does `from app.database import get_commercial_policies`,
    # so the bound name lives in app.tools.discount.
    monkeypatch.setattr(
        "app.tools.discount.get_commercial_policies",
        _fake_get_commercial_policies,
    )
    # commercial_policy.py binds it the same way (used by quantity/value
    # authority + evaluate_commercial_authority).
    monkeypatch.setattr(
        "app.tools.commercial_policy.get_commercial_policies",
        _fake_get_commercial_policies,
    )
    return data
