from app.claude_client import get_claude_client


TEST_TOOL = {
    "name": "get_weather",
    "description": (
        "Get the current weather for a city."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string"
            }
        },
        "required": [
            "city"
        ]
    }
}


def print_response(response):

    print("\nSTOP REASON:")
    print(response.stop_reason)

    print("\nCONTENT BLOCKS:")

    for block in response.content:

        print(
            "\nTYPE:",
            block.type
        )

        if block.type == "text":

            print(
                "TEXT:",
                block.text
            )

        elif block.type == "tool_use":

            print(
                "ID:",
                block.id
            )

            print(
                "NAME:",
                block.name
            )

            print(
                "INPUT:",
                block.input
            )


def main():

    client = get_claude_client()

    # ========================================================
    # TEST 1
    # Basic text generation
    # ========================================================

    print("\n" + "=" * 60)
    print("TEST 1 - BASIC CHAT")
    print("=" * 60)

    response = client.messages.create(
        model="ignored-by-gateway-adapter",
        max_tokens=100,
        system=(
            "Follow the user's instruction exactly."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    "Reply with exactly: "
                    "ADAPTER_CHAT_OK"
                )
            }
        ]
    )

    print_response(response)

    assert response.stop_reason == "end_turn"

    assert any(
        block.type == "text"
        and "ADAPTER_CHAT_OK" in block.text
        for block in response.content
    )

    print("\nPASS: Basic chat")


    # ========================================================
    # TEST 2
    # Tool request
    # ========================================================

    print("\n" + "=" * 60)
    print("TEST 2 - TOOL REQUEST")
    print("=" * 60)

    messages = [
        {
            "role": "user",
            "content": (
                "What is the weather in Singapore? "
                "You must use the weather tool."
            )
        }
    ]

    response = client.messages.create(
        model="ignored-by-gateway-adapter",
        max_tokens=200,
        system=(
            "Use the supplied tool when required."
        ),
        tools=[
            TEST_TOOL
        ],
        messages=messages
    )

    print_response(response)

    assert response.stop_reason == "tool_use"

    tool_blocks = [
        block
        for block in response.content
        if block.type == "tool_use"
    ]

    assert len(tool_blocks) >= 1

    tool_block = tool_blocks[0]

    assert tool_block.name == "get_weather"

    assert (
        tool_block.input.get("city")
        == "Singapore"
    )

    print("\nPASS: Tool request")


    # ========================================================
    # TEST 3
    # Tool result -> final response
    #
    # IMPORTANT:
    # This uses the SAME conversation-history structure
    # already used by agent.py.
    # ========================================================

    print("\n" + "=" * 60)
    print("TEST 3 - TOOL RESULT CONTINUATION")
    print("=" * 60)

    messages.append({
        "role": "assistant",
        "content": response.content
    })

    messages.append({
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_block.id,
                "content": (
                    "Singapore: 31 degrees Celsius, "
                    "partly cloudy."
                )
            }
        ]
    })

    response = client.messages.create(
        model="ignored-by-gateway-adapter",
        max_tokens=200,
        system=(
            "Use the supplied tool when required. "
            "After receiving the tool result, "
            "answer the user's question."
        ),
        tools=[
            TEST_TOOL
        ],
        messages=messages
    )

    print_response(response)

    assert response.stop_reason == "end_turn"

    final_text = "\n".join(
        block.text
        for block in response.content
        if block.type == "text"
    )

    assert "31" in final_text

    assert (
        "Singapore" in final_text
        or "singapore" in final_text.lower()
    )

    print("\nPASS: Tool result continuation")


    # ========================================================
    # FINAL
    # ========================================================

    print("\n" + "=" * 60)
    print("ALL LLM GATEWAY ADAPTER TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()