
import json
from pathlib import Path

from app.services.emotion_music_matcher import (
    match_emotion_to_music,
)

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"

music_json_path = OUTPUT_DIR / "stage77_segments.json"

with music_json_path.open("r", encoding="utf-8") as file:
    prepared_music = json.load(file)


# Temporary sample timeline for testing the matching engine.
# Later, replace this with actual output from analyze_video_frames().

video_analysis = {
    "interval_seconds": 2,
    "emotion_timeline": [
        {
            "timestamp_seconds": 0.0,
            "primary_emotion": "sad",
            "confidence": 0.91,
            "scene": "A person sitting alone",
            "visual_evidence": ["Downcast eyes"],
        },
        {
            "timestamp_seconds": 2.0,
            "primary_emotion": "happy",
            "confidence": 0.88,
            "scene": "People smiling",
            "visual_evidence": ["Visible smiles"],
        },
        {
            "timestamp_seconds": 4.0,
            "primary_emotion": "romantic",
            "confidence": 0.82,
            "scene": "Two people together",
            "visual_evidence": ["Affectionate interaction"],
        },
    ],
}

result = match_emotion_to_music(
    video_analysis=video_analysis,
    prepared_music=prepared_music,
    top_k=3,
    min_segment_duration=1.0,
)

output_path = OUTPUT_DIR / "stage78_matching.json"

with output_path.open("w", encoding="utf-8") as file:
    json.dump(
        result,
        file,
        ensure_ascii=False,
        indent=4,
    )

print("\nStage 7.8 matching completed.")
print("Video intervals:", result["video_interval_count"])
print(
    "Music segments considered:",
    result["music_segments_considered"],
)

for item in result["matching_plan"]:

    print("\n----------------------------------")
    print("Video time:", item["video_start_time"], "-", item["video_end_time"])
    print("Emotion:", item["emotion"])
    print("Confidence:", item["confidence"])

    for match in item["top_matches"]:
        print(
            "  ",
            match["segment_id"],
            "| Type:", match["segment_type"],
            "| Score:", match["score"],
        )

print("\nSaved:", output_path)
