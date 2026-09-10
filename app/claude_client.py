import os

from anthropic import Anthropic
from dotenv import load_dotenv


load_dotenv()


def get_claude_client():
    """
    Create the Anthropic client using the API key
    stored in our .env file.
    """

    api_key = os.getenv("ANTHROPIC_API_KEY")

    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY was not found in .env"
        )

    return Anthropic(api_key=api_key)