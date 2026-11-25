
import requests
from pathlib import Path

url = "https://huggingface.co/Systran/faster-whisper-small/resolve/main/model.bin"

output = Path("backend/models/faster-whisper-small/model.bin")
output.parent.mkdir(parents=True, exist_ok=True)

print("Downloading Faster-Whisper model...")
print("Model size: approximately 461 MB")

with requests.get(url, stream=True, timeout=(30, 120)) as response:
    response.raise_for_status()

    with output.open("wb") as file:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                file.write(chunk)
                print(f"Downloaded: {output.stat().st_size / (1024 * 1024):.1f} MB")

print("Download completed!")
print(f"Model saved at: {output}")
