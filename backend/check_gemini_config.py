
from pathlib import Path
import os
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]

env_path = PROJECT_ROOT / ".env"

print("Project root:", PROJECT_ROOT)
print(".env exists:", env_path.exists())

load_dotenv(env_path, override=True)

api_key = os.getenv("GEMINI_API_KEY")

print("API key loaded:", bool(api_key))
print("API key length:", len(api_key) if api_key else 0)
print("Model:", os.getenv("GEMINI_MODEL"))
