
from app.services.music_timeline_assembler import (
    assemble_music_timeline,
)

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

matching_json = (
    BASE_DIR / "outputs" / "stage78_matching.json"
)

music_path = (
    BASE_DIR / "music" / "tamil"
    / "Sidu Sidu Endralum.mp3"
)

output_path = (
    BASE_DIR / "outputs" / "stage79_assembled.wav"
)


result = assemble_music_timeline(
    matching_json=str(matching_json),
    music_path=str(music_path),
    output_path=str(output_path),
)

print("\nAssembly result:")
print(result)
