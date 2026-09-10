from app.bedrock_client import (
    get_bedrock_client,
    MODEL_ID
)


client = get_bedrock_client()

print("Connecting to Amazon Bedrock...")
print("Model:", MODEL_ID)


response = client.converse(
    modelId=MODEL_ID,

    messages=[
        {
            "role": "user",
            "content": [
                {
                    "text": (
                        "Reply with exactly this text "
                        "and nothing else: "
                        "BEDROCK_CONNECTED"
                    )
                }
            ]
        }
    ],

    inferenceConfig={
        "maxTokens": 30,
        "temperature": 0
    }
)


reply = response["output"]["message"]["content"][0]["text"]

print("\nClaude response:")
print(reply)


print("\nUsage:")
print(response.get("usage", {}))