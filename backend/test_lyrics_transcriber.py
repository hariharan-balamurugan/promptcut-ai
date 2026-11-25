
import json
from pathlib import Path

from app.services.lyrics_transcriber import transcribe_audio

music_folder = Path("backend/music/tamil")

audio_files = [
    file for file in music_folder.iterdir()
    if file.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg", ".aac"}
]

if not audio_files:
    print("No music files found!")
else:
    audio_path = audio_files[0]

    print(f"Transcribing: {audio_path.name}")

    result = transcribe_audio(audio_path)

    print(json.dumps(result, indent=4, ensure_ascii=False))
