
import json
from pathlib import Path

from app.services.music_timeline import build_music_timeline
from app.services.music_segment_preparation import prepare_music_segments

audio_path = Path(
    "backend/music/tamil/Sidu Sidu Endralum.mp3"
)

separated_dir = Path(
    "C:\\Users\\harih\\Downloads\\ai\\outputs\\separated\\htdemucs\\Sidu Sidu Endralum"
)

result = build_music_timeline(
    audio_path,
    separated_dir,
    music_id="c3b22f1980864d178d2be37da2523b50"
)


prepared = prepare_music_segments(result)

print("\nSTAGE 7.7 - MUSIC SEGMENTS")
print("Total segments:", prepared["segment_count"])
print("Segment types:", prepared["segment_type_counts"])

for segment in prepared["segments"]:
    print(
        segment["segment_id"],
        segment["start_time"],
        segment["end_time"],
        segment["segment_type"],
        "Lyrics:", len(segment["lyrics"]),
        "Boundary lyrics:", len(segment["boundary_lyrics"])
    )

print(json.dumps(result, indent=4, ensure_ascii=False))
