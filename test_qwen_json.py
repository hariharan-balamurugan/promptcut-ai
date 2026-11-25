import time
import json
import ollama

client = ollama.Client(
    host="http://localhost:11434",
    timeout=300.0,
)

print("Testing Qwen JSON generation...", flush=True)

start_time = time.time()

try:
    response = client.chat(
        model="qwen3.5:4b",
        messages=[
            {
                "role": "system",
                "content": (
                    "You convert video-editing instructions into JSON. "
                    "Return only a JSON object with an operations array. "
                    "Do not explain your answer."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Trim the first 5 seconds. "
                    'Return {"operations":[{"type":"trim",'
                    '"start":5,"end":null}]}'
                ),
            },
        ],
        format="json",
        think=False,
        options={
            "temperature": 0,
            "num_predict": 300,
        },
        stream=False,
    )

    content = response["message"]["content"]

    print("Elapsed seconds:", round(time.time() - start_time, 2))
    print("Finish reason:", response.get("done_reason"))
    print("Raw response:", repr(content))

    if not content.strip():
        print("ERROR: Qwen returned empty content.")
    else:
        result = json.loads(content)
        print("Parsed JSON:")
        print(json.dumps(result, indent=2))

except Exception as error:
    print("ERROR:", repr(error))