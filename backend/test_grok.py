
from app.services.grok_client import generate_text


def main():
    print("Testing Grok API...")

    prompt = """
    You are an AI assistant for PromptCut AI.

    Explain how AI can understand emotions
    in video scenes in three simple points.
    """

    try:
        result = generate_text(prompt)

        print("\nGrok response:")
        print(result)

        print("\nGrok API connection successful!")

    except Exception as error:
        print("\nGrok API test failed:")
        print(type(error).__name__, str(error))


if __name__ == "__main__":
    main()
