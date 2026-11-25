
from pathlib import Path
from app.services.lyrics_transcriber import transcribe_audio

audio_path = Path(
    r"outputs/separated/htdemucs/Sidu Sidu Endralum/vocals.wav"
)

result = transcribe_audio(
    audio_path,
    language="ta"
)

print("Detected language:", result["language"])
print("Language probability:", result["language_probability"])
print("Total lyric segments:", len(result["lyrics"]))

for segment in result["lyrics"]:
    print("\nText:", segment["text"])
    print("Words:", segment["words"])
