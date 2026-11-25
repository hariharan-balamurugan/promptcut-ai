
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Locate project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Load .env
load_dotenv(PROJECT_ROOT / ".env")

API_KEY = os.getenv("XAI_API_KEY")
MODEL_NAME = os.getenv("GROK_MODEL", "grok-4.7")

if not API_KEY:
    raise ValueError("XAI_API_KEY is missing in .env")

# Initialize Grok client
client = OpenAI(
    api_key=API_KEY,
    base_url="https://api.x.ai/v1",
    timeout=120.0
)


def generate_text(prompt: str) -> str:
    if not prompt or not prompt.strip():
        raise ValueError("Prompt cannot be empty")

    response = client.responses.create(
        model=MODEL_NAME,
        input=prompt
    )

    result = response.output_text

    if not result:
        raise RuntimeError("Grok returned an empty response")

    return result.strip()
