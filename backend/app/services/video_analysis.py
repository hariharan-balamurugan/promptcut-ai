
import base64
import os
import shutil
import subprocess
import tempfile

from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

FFMPEG_PATH = os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg")
FFPROBE_PATH = os.getenv("FFPROBE_PATH") or shutil.which("ffprobe")

DEFAULT_INTERVAL_SECONDS = 2.0
MAX_FRAMES = 300


def get_video_duration(video_path: str | Path) -> float:
    """Get video duration using FFprobe."""

    video_path = Path(video_path).resolve()

    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")

    if not FFPROBE_PATH:
        raise RuntimeError("FFprobe executable not found.")

    command = [
        FFPROBE_PATH,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"FFprobe failed: {result.stderr.strip()}"
        )

    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("Invalid video duration.") from exc

    if duration <= 0:
        raise ValueError("Video duration is invalid.")

    return duration


def extract_video_frames(
    video_path: str | Path,
    max_frames: int | None = None,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
) -> list[dict]:
    """
    Extract video frames at regular intervals.

    Default: one frame every 2 seconds.

    Returns:
        [
            {
                "timestamp_seconds": 0.0,
                "image_base64": "..."
            }
        ]
    """

    video_path = Path(video_path).resolve()

    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")

    if not FFMPEG_PATH:
        raise RuntimeError("FFmpeg executable not found.")

    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero.")

    if max_frames is not None and max_frames < 1:
        raise ValueError("max_frames must be at least 1.")

    duration = get_video_duration(video_path)

    timestamps = []
    timestamp = 0.0

    while timestamp < duration:
        timestamps.append(round(timestamp, 2))
        timestamp += interval_seconds

    frame_limit = min(
        max_frames if max_frames is not None else MAX_FRAMES,
        MAX_FRAMES,
    )
   
    if len(timestamps) > frame_limit:
      print(
        f"Video requires {len(timestamps)} frames. "
        f"Sampling {frame_limit} frames across the full video."
    )

    if frame_limit == 1:
        timestamps = [0.0]
    else:
        last_timestamp = max(0.0, duration - 0.01)

        timestamps = [
            round(
                last_timestamp * index / (frame_limit - 1),
                2,
            )
            for index in range(frame_limit)
        ]

        # Remove duplicate timestamps caused by rounding.
        timestamps = list(dict.fromkeys(timestamps))


    extracted_frames = []

    with tempfile.TemporaryDirectory(
        prefix="promptcut_frames_"
    ) as temp_dir:

        for index, timestamp in enumerate(timestamps):

            frame_path = (
                Path(temp_dir) / f"frame_{index + 1}.jpg"
            )

            command = [
                FFMPEG_PATH,
                "-hide_banner",
                "-loglevel", "error",
                "-ss", str(timestamp),
                "-i", str(video_path),
                "-frames:v", "1",
                "-vf", "scale=512:-2",
                "-q:v", "3",
                "-y",
                str(frame_path),
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

            if result.returncode != 0 or not frame_path.is_file():
                print(
                    f"Could not extract frame at {timestamp}s: "
                    f"{result.stderr[-500:]}"
                )
                continue

            image_data = base64.b64encode(
                frame_path.read_bytes()
            ).decode("utf-8")

            extracted_frames.append({
                "timestamp_seconds": timestamp,
                "image_base64": image_data,
            })

            print(f"Extracted frame at {timestamp}s")

    if not extracted_frames:
        raise RuntimeError("Could not extract any video frames.")

    print(
        f"Total extracted frames: {len(extracted_frames)}"
    )

    return extracted_frames
