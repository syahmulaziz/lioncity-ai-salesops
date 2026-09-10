import boto3


AWS_REGION = "us-east-1"

MODEL_ID = (
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
)


def get_bedrock_client():
    """
    Create the Amazon Bedrock Runtime client.
    """
    return boto3.client(
        "bedrock-runtime",
        region_name=AWS_REGION
    )