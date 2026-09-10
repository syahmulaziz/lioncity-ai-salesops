from app.claude_client import get_claude_client


client = get_claude_client()

print("Connecting to Claude...")


response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=30,
    messages=[
        {
            "role": "user",
            "content": (
                "Reply with exactly this text "
                "and nothing else: "
                "CLAUDE_CONNECTED"
            )
        }
    ]
)


print("\nClaude response:")
print(response.content[0].text)


print("\nUsage:")
print(response.usage)