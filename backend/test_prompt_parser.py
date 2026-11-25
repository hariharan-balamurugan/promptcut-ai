from app.services.prompt_parser import parse_with_ollama

prompts = [
    "Apply smooth 0.5x slow motion to the entire video.",
    "Apply slow motion from 5 seconds to 10 seconds.",
    "Apply cinematic 0.25x slow motion from 3 to 8 seconds.",
    "Make the entire video 2x faster.",
    "Make the video vertical and apply 0.5x slow motion.",
]

for prompt in prompts:
    print("\nPROMPT:", prompt)

    try:
        result = parse_with_ollama(prompt)
        print("PLAN:", result)

    except Exception as error:
        print("ERROR:", error)