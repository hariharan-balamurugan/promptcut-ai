from pathlib import Path
import json

from app.services.music_analysis import analyze_audio

MUSIC_FOLDER = Path("backend/music/tamil")

audio_files = [
    file for file in MUSIC_FOLDER.iterdir()
    if file.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg", ".aac"}
]

if not audio_files:
    print("No music files found!")
else:
    audio_path = audio_files[0]

    print(f"Analyzing: {audio_path.name}")

    result = analyze_audio(audio_path)

    print(json.dumps(result, indent=4))