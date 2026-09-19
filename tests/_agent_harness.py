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
