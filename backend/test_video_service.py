
from pathlib import Path
import sys

# Add backend folder to Python path.
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"

sys.path.insert(0, str(BACKEND_DIR))

from app.services.video_service import process_video_prompt


INPUT_VIDEO = BACKEND_DIR / "uploads" / "nanban.mp4"
OUTPUT_VIDEO = BACKEND_DIR / "outputs" / "prompt_test_output.mp4"

prompt = (
    "Trim the video to the first 10 seconds, "
    "make it vertical 9:16, and remove the audio."
)

print("User prompt:", prompt)

if not INPUT_VIDEO.is_file():
    raise FileNotFoundError(
        f"Input video not found: {INPUT_VIDEO}"
    )

OUTPUT_VIDEO.parent.mkdir(parents=True, exist_ok=True)

print("\nProcessing video...")

try:
    result = process_video_prompt(
        input_video=str(INPUT_VIDEO),
        prompt=prompt,
        output_video=str(OUTPUT_VIDEO),
        provider="ollama",
    )

    print("\n========== EDITING RESULTS ==========")
    print("Editing completed successfully!")
    print("Generated plan:", result["plan"])
    print("Output path:", result["output_path"])
    print("Output metadata:", result["output_info"])
    print("Applied operations:", result["operations_applied"])

    print("\n========== VIDEO ANALYSIS ==========")
    print("Analysis:", result["video_analysis"])

    print("\n========== BACKGROUND MUSIC ==========")
    print("Music:", result["background_music"])

    print("=====================================\n")

except Exception as exc:
    print(f"\nEditing failed: {exc}")
    raise
