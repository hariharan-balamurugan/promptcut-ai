
import json
from pathlib import Path

from app.services.music_timeline import build_music_timeline
from app.services.music_segment_preparation import prepare_music_segments


# Project paths
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent

AUDIO_PATH = (
    BACKEND_DIR
    / "music"
    / "tamil"
    / "Sidu Sidu Endralum.mp3"
)

SEPARATED_DIR = (
    BACKEND_DIR
    / "outputs"
    / "separated"
    / "htdemucs"
    / "Sidu Sidu Endralum"
)

MUSIC_ID = "c3b22f1980864d178d2be37da2523b50"


def main():

    print("\n========== STAGE 7.7 TEST ==========\n")

    # Check required files
    if not AUDIO_PATH.exists():
        raise FileNotFoundError(f"Audio file not found: {AUDIO_PATH}")

    if not (SEPARATED_DIR / "vocals.wav").exists():
        raise FileNotFoundError("vocals.wav not found")

    if not (SEPARATED_DIR / "no_vocals.wav").exists():
        raise FileNotFoundError("no_vocals.wav not found")

    # Step 1: Build music timeline
    print("Step 1: Building music timeline...")

    timeline_result = build_music_timeline(
        audio_path=AUDIO_PATH,
        separated_dir=SEPARATED_DIR,
        music_id=MUSIC_ID
    )

    print("Music timeline completed!")

    # Step 2: Prepare music segments
    print("\nStep 2: Preparing music segments...")

    prepared_result = prepare_music_segments(
        timeline_result=timeline_result,
        min_segment_duration=0.5,
        include_uncertain=True
    )

    print("Music segment preparation completed!")

    # Step 3: Display summary
    print("\n========== SEGMENT SUMMARY ==========")

    print("Total segments:", prepared_result.get("total_segments", 0))

    print(
        "Type counts:",
        json.dumps(
            prepared_result.get("type_counts", {}),
            ensure_ascii=False
        )
    )

    print(
        "Total lyrics:",
        prepared_result.get("total_lyrics", 0)
    )

    # Step 4: Display individual segments
    print("\n========== INDIVIDUAL SEGMENTS ==========")

    for index, segment in enumerate(
        prepared_result.get("segments", []),
        start=1
    ):
        print(f"\nSegment {index}")
        print("ID:", segment.get("segment_id"))
        print("Start:", segment.get("start_time"))
        print("End:", segment.get("end_time"))
        print("Duration:", segment.get("duration_seconds"))
        print("Type:", segment.get("segment_type"))
        print("BPM:", segment.get("bpm"))
        print("Energy:", segment.get("average_energy"))

        print("Lyrics:", segment.get("lyrics", []))
        print("Boundary lyrics:", segment.get("boundary_lyrics", []))
        print("Uncertain lyrics:", segment.get("uncertain_lyrics", []))

    # Step 5: Save output JSON
    output_path = BACKEND_DIR / "outputs" / "stage77_segments.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(
            prepared_result,
            file,
            indent=4,
            ensure_ascii=False
        )

    print("\n====================================")
    print("Stage 7.7 test completed!")
    print("JSON saved at:", output_path)


if __name__ == "__main__":
    main()
