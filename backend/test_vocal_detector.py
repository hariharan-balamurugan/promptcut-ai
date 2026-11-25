
import json
from pathlib import Path

from app.services.lyrics_transcriber import transcribe_audio
from app.services.vocal_detector import detect_vocal_sections

audio_path = Path(
    "backend/music/tamil/Sidu Sidu Endralum.mp3"
)

transcription = transcribe_audio(audio_path)

result = detect_vocal_sections(transcription)

print(json.dumps(result, indent=4, ensure_ascii=False))
