
from pathlib import Path

from app.services.video_analysis import extract_video_frames

video_path = Path(
    r"C:\Users\harih\Downloads\ai\backend\uploads\nanban.mp4"
)

frames = extract_video_frames(video_path, max_frames=5)

print("\n========== VIDEO FRAME ANALYSIS ==========")

for frame in frames:
    print(
        "Timestamp:",
        frame["timestamp_seconds"],
        "seconds",
        "| Image size:",
        len(frame["image_base64"]),
    )

print("\nTotal frames extracted:", len(frames))
print("Frame extraction test completed!")
