import os
import uuid
from types import SimpleNamespace

import requests
from dotenv import load_dotenv


load_dotenv()


# ============================================================
# Helpers
# ============================================================

def _make_text_block(text):
    """
    Create an Anthropic-like text content block.

    agent.py expects:
        block.type == "text"
        block.text
    """
    return SimpleNamespace(
        type="text",
        text=text
    )


def _make_tool_use_block(
    tool_name,
    arguments,
    tool_use_id=None
):
    """
    Create an Anthropic-like tool_use content block.

    agent.py expects:
        block.type == "tool_use"
        block.id
        block.name
        block.input
    """

    if tool_use_id is None:
        tool_use_id = f"toolu_{uuid.uuid4().hex}"

    return SimpleNamespace(
        type="tool_use",
        id=tool_use_id,
        name=tool_name,
        input=arguments or {}
    )


# ============================================================
# Gateway adapter
# ============================================================

class GatewayMessages:
    """
    Implements the subset of the Anthropic messages API
    currently used by LionCity.

    Existing agent code can continue calling:

        client.messages.create(...)

    This class translates that request into the hackathon
    gateway's Ollama-style /api/chat request.
    """

    def __init__(
        self,
        gateway_url,
        api_key,
        default_model
    ):
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model

    # --------------------------------------------------------
    # Tool conversion
    # --------------------------------------------------------

    def _convert_tools(self, tools):
        """
        Convert Anthropic-style tool definitions:

            {
                "name": "...",
                "description": "...",
                "input_schema": {...}
            }

        into Ollama-style tool definitions:

            {
                "type": "function",
                "function": {
                    "name": "...",
                    "description": "...",
                    "parameters": {...}
                }
            }
        """

        converted = []

        for tool in tools or []:

            converted.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get(
                        "description",
                        ""
                    ),
                    "parameters": tool.get(
                        "input_schema",
                        {
                            "type": "object",
                            "properties": {}
                        }
                    )
                }
            })

        return converted

    # --------------------------------------------------------
    # Conversation-history conversion
    # --------------------------------------------------------

    def _convert_messages(
        self,
        system,
        messages
    ):
        """
        Convert LionCity's existing Anthropic-style conversation
        history into the Ollama-style messages expected by the
        gateway.

        LionCity currently stores:

        Normal user messages:
            {
                "role": "user",
                "content": "..."
            }

        Assistant responses:
            {
                "role": "assistant",
                "content": [text/tool_use blocks]
            }

        Tool results:
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "...",
                        "content": "..."
                    }
                ]
            }

        The gateway instead expects tool results as:
            {
                "role": "tool",
                "name": "...",
                "content": "..."
            }
        """

        converted = []

        if system:

            converted.append({
                "role": "system",
                "content": system
            })

        # Maps LionCity's generated tool-use IDs back to the
        # function name when we later encounter tool_result.
        tool_id_to_name = {}

        for message in messages:

            role = message.get("role")
            content = message.get("content")

            # =================================================
            # Plain string message
            # =================================================

            if isinstance(content, str):

                converted.append({
                    "role": role,
                    "content": content
                })

                continue

            # =================================================
            # Assistant content blocks
            # =================================================

            if role == "assistant" and isinstance(
                content,
                list
            ):

                text_parts = []
                tool_calls = []

                for block in content:

                    block_type = getattr(
                        block,
                        "type",
                        None
                    )

                    if block_type == "text":

                        text_parts.append(
                            getattr(
                                block,
                                "text",
                                ""
                            )
                        )

                    elif block_type == "tool_use":

                        tool_id = getattr(
                            block,
                            "id",
                            None
                        )

                        tool_name = getattr(
                            block,
                            "name",
                            None
                        )

                        tool_input = getattr(
                            block,
                            "input",
                            {}
                        )

                        if tool_id and tool_name:
                            tool_id_to_name[
                                tool_id
                            ] = tool_name

                        tool_calls.append({
                            "function": {
                                "name": tool_name,
                                "arguments": (
                                    tool_input or {}
                                )
                            }
                        })

                assistant_message = {
                    "role": "assistant",
                    "content": "\n".join(
                        part
                        for part in text_parts
                        if part
                    )
                }

                if tool_calls:
                    assistant_message[
                        "tool_calls"
                    ] = tool_calls

                converted.append(
                    assistant_message
                )

                continue

            # =================================================
            # Tool-result blocks
            # =================================================

            if role == "user" and isinstance(
                content,
                list
            ):

                handled_as_tool_results = False

                for item in content:

                    if not isinstance(item, dict):
                        continue

                    if item.get(
                        "type"
                    ) != "tool_result":
                        continue

                    handled_as_tool_results = True

                    tool_use_id = item.get(
                        "tool_use_id"
                    )

                    tool_name = (
                        tool_id_to_name.get(
                            tool_use_id
                        )
                    )

                    if not tool_name:
                        raise ValueError(
                            "Could not resolve tool name "
                            f"for tool_use_id "
                            f"{tool_use_id}"
                        )

                    converted.append({
                        "role": "tool",
                        "name": tool_name,
                        "content": str(
                            item.get(
                                "content",
                                ""
                            )
                        )
                    })

                if handled_as_tool_results:
                    continue

            # =================================================
            # Unsupported history shape
            # =================================================

            raise ValueError(
                "Unsupported conversation message "
                f"format: role={role}, "
                f"content_type="
                f"{type(content).__name__}"
            )

        return converted

    # --------------------------------------------------------
    # Gateway response conversion
    # --------------------------------------------------------

    def _convert_response(self, payload):
        """
        Convert the gateway response into the subset of the
        Anthropic response object used by agent.py.

        agent.py expects:

            response.stop_reason
            response.content

        where response.content contains blocks with:

            text:
                block.type
                block.text

            tool:
                block.type
                block.id
                block.name
                block.input
        """

        gateway_message = payload.get(
            "message",
            {}
        )

        content_blocks = []

        text = gateway_message.get(
            "content",
            ""
        )

        if text:

            content_blocks.append(
                _make_text_block(text)
            )

        gateway_tool_calls = (
            gateway_message.get(
                "tool_calls",
                []
            )
            or []
        )

        for tool_call in gateway_tool_calls:

            function = tool_call.get(
                "function",
                {}
            )

            content_blocks.append(
                _make_tool_use_block(
                    tool_name=function.get(
                        "name"
                    ),
                    arguments=function.get(
                        "arguments",
                        {}
                    )
                )
            )

        gateway_done_reason = payload.get(
            "done_reason"
        )

        # LionCity's agent specifically checks for
        # stop_reason == "tool_use".
        if gateway_tool_calls:

            stop_reason = "tool_use"

        elif gateway_done_reason in (
            "stop",
            "end_turn",
            None
        ):

            stop_reason = "end_turn"

        else:

            # Preserve unusual termination reasons such
            # as length limits for observability.
            stop_reason = gateway_done_reason

        return SimpleNamespace(
            stop_reason=stop_reason,
            content=content_blocks,
            model=payload.get("model"),
            raw_response=payload
        )

    # --------------------------------------------------------
    # Anthropic-compatible entry point
    # --------------------------------------------------------

    def create(
        self,
        model=None,
        max_tokens=1200,
        system=None,
        tools=None,
        messages=None,
        **kwargs
    ):
        """
        Anthropic-compatible messages.create() adapter.

        IMPORTANT:
        The model argument supplied by the existing agent is
        intentionally NOT trusted as the gateway model.

        LionCity currently passes:
            claude-sonnet-4-5

        The hackathon organizer supplied:
            LLM_MODEL=
            global.anthropic.claude-sonnet-4-5-20250929-v1:0

        Therefore the environment-configured gateway model is
        used instead.
        """

        gateway_messages = self._convert_messages(
            system=system,
            messages=messages or []
        )

        payload = {
            "model": self.default_model,
            "messages": gateway_messages,
            "stream": False
        }

        converted_tools = self._convert_tools(
            tools
        )

        if converted_tools:

            payload["tools"] = converted_tools

        # Ollama-compatible option. If the organizer's proxy
        # supports it, this corresponds approximately to the
        # existing max_tokens value.
        if max_tokens is not None:

            payload["options"] = {
                "num_predict": max_tokens
            }

        headers = {
            "Authorization": (
                f"Bearer {self.api_key}"
            ),
            "Content-Type": "application/json"
        }

        response = requests.post(
            f"{self.gateway_url}/api/chat",
            headers=headers,
            json=payload,
            timeout=120
        )

        if not response.ok:

            request_id = response.headers.get(
                "X-Request-ID"
            )

            # Do NOT include the API key in this error.
            raise RuntimeError(
                "LLM gateway request failed: "
                f"HTTP {response.status_code}; "
                f"request_id={request_id}; "
                f"response={response.text}"
            )

        gateway_payload = response.json()

        return self._convert_response(
            gateway_payload
        )


class GatewayClaudeClient:
    """
    Anthropic-like client wrapper.

    This preserves the interface already used by agent.py:

        client.messages.create(...)
    """

    def __init__(
        self,
        gateway_url,
        api_key,
        model
    ):

        self.messages = GatewayMessages(
            gateway_url=gateway_url,
            api_key=api_key,
            default_model=model
        )


# ============================================================
# Public factory used by agent.py
# ============================================================

def get_claude_client():
    """
    Create the LionCity LLM client using the hackathon
    organizer's LLM gateway.

    Required .env variables:

        LLM_GATEWAY_URL
        LLM_GATEWAY_API_KEY
        LLM_MODEL
    """

    gateway_url = os.getenv(
        "LLM_GATEWAY_URL"
    )

    api_key = os.getenv(
        "LLM_GATEWAY_API_KEY"
    )

    model = os.getenv(
        "LLM_MODEL"
    )

    missing = []

    if not gateway_url:
        missing.append(
            "LLM_GATEWAY_URL"
        )

    if not api_key:
        missing.append(
            "LLM_GATEWAY_API_KEY"
        )

    if not model:
        missing.append(
            "LLM_MODEL"
        )

    if missing:

        raise ValueError(
            "Missing required LLM gateway "
            "environment variable(s): "
            + ", ".join(missing)
        )

    return GatewayClaudeClient(
        gateway_url=gateway_url,
        api_key=api_key,
        model=model
    )