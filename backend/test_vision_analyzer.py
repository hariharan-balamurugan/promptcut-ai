
from pathlib import Path

from app.services.video_analysis import extract_video_frames
from app.services.vision_analyzer import analyze_video_frames


video_path = Path(
    r"C:\Users\harih\Downloads\ai\backend\uploads\nanban.mp4"
)

print("Extracting video frames...")

frames = extract_video_frames(
    video_path,
    max_frames=5,
)

print("Extracted frames:", len(frames))
print("Sending frames to Vision AI...")

analysis = analyze_video_frames(frames)

print("\n========== AI VIDEO ANALYSIS ==========")

for key, value in analysis.items():
    print(f"{key}: {value}")

print("\nVision AI test completed!")
