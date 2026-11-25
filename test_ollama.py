
import ollama

print("Sending request to Qwen...")

try:
    response = ollama.chat(
        model="qwen3.5:4b",
        messages=[
            {
                "role": "user",
                "content": "Reply with exactly: READY"
            }
        ],
        options={"temperature": 0}
    )

    print("Model response:")
    print(response["message"]["content"])

except Exception as error:
    print("Error:", error)