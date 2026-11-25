
from pathlib import Path

from app.services.video_editor import (
    edit_video,
    get_video_info,
)


# --------------------------------------------------
# 1. Input video path
# --------------------------------------------------

input_video = Path(
    r"C:\Users\harih\Downloads\ai\backend\uploads\nanban.mp4"
)

# Optional: Background music path.
# Keep None for testing without background music.
background_music = Path(
    r"C:\Users\harih\Downloads\ai\backend\uploads\tamil_vinay_bgm.mp3"
)

# Change to None if you want to test without music.
USE_BACKGROUND_MUSIC = True


# --------------------------------------------------
# 2. Check input video
# --------------------------------------------------

if not input_video.is_file():
    raise FileNotFoundError(
        f"Test video not found: {input_video}"
    )

print("\n========== INPUT VIDEO ==========")

info = get_video_info(input_video)

print("Duration:", info["duration_seconds"])
print("Width:", info["width"])
print("Height:", info["height"])
print("Audio available:", info["has_audio"])


# --------------------------------------------------
# 3. Editing plan
# --------------------------------------------------

plan = {
    "operations": [
        {
            "type": "trim",
            "start": 0,
            "end": 10,
        },
        {
            "type": "resize",
            "aspect_ratio": "9:16",
        },
    ]
}


# --------------------------------------------------
# 4. Background music settings
# --------------------------------------------------

music_path = None

if USE_BACKGROUND_MUSIC:

    if not background_music.is_file():
        raise FileNotFoundError(
            f"Background music not found: {background_music}"
        )

    music_path = background_music

    print("\nBackground music:", music_path.name)


# --------------------------------------------------
# 5. Execute video editing
# --------------------------------------------------

print("\n========== STARTING VIDEO EDITING ==========")

result = edit_video(
    input_path=input_video,
    plan=plan,
    background_music_path=music_path,
    music_volume=0.20,
    music_fade_in=2.0,
    music_fade_out=2.0,
)


# --------------------------------------------------
# 6. Display output
# --------------------------------------------------

print("\n========== EDITING SUCCESS ==========")

print("Message:", result["message"])
print("Output video:", result["output_path"])
print("Background music added:", result["background_music_added"])

print("\nOutput metadata:")

for key, value in result["output_info"].items():
    print(f"{key}: {value}")

print("\nOperations applied:")

for operation in result["operations_applied"]:
    print(operation)

print("\nVideo editing test completed successfully!")
