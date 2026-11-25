
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

FFMPEG_PATH = os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg")
FFPROBE_PATH = os.getenv("FFPROBE_PATH") or shutil.which("ffprobe")

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_OPERATIONS = {"trim", "resize", "speed", "mute"}
SUPPORTED_RATIOS = {"9:16", "16:9", "1:1"}


def _require_executable(path: str | None, name: str) -> str:
    if not path:
        raise RuntimeError(
            f"{name} was not found. Install FFmpeg and add its bin folder "
            "to PATH, or configure its executable path in .env."
        )
    return path


def get_video_info(input_path: str | Path) -> dict[str, Any]:
    input_path = Path(input_path).resolve()

    if not input_path.is_file():
        raise FileNotFoundError(f"Video file not found: {input_path}")

    ffprobe = _require_executable(FFPROBE_PATH, "FFprobe")

    command = [
        ffprobe,
        "-v", "error",
        "-show_entries",
        "format=duration,format_name:stream=codec_type,width,height",
        "-of", "json",
        str(input_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(f"FFprobe failed: {result.stderr.strip()}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("FFprobe returned invalid JSON.") from exc

    video_stream = next(
        (
            stream for stream in data.get("streams", [])
            if stream.get("codec_type") == "video"
        ),
        None,
    )

    if not video_stream:
        raise ValueError("The input file does not contain a video stream.")

    duration = float(data.get("format", {}).get("duration", 0))

    return {
        "duration_seconds": duration,
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "format": data.get("format", {}).get("format_name"),
        "has_audio": any(
            stream.get("codec_type") == "audio"
            for stream in data.get("streams", [])
        ),
    }


def validate_plan(
    plan: dict[str, Any],
    duration: float,
    allow_empty: bool = False,
) -> list[dict[str, Any]]:

    if not isinstance(plan, dict):
        raise ValueError("Editing plan must be a JSON object.")

    operations = plan.get("operations")

    if not isinstance(operations, list):
     raise ValueError("The editing plan contains an invalid operations list.")

    if not operations and not allow_empty:
       raise ValueError("The editing plan contains no operations.")
    validated = []

    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("Each editing operation must be an object.")

        kind = operation.get("type")

        if kind not in SUPPORTED_OPERATIONS:
            raise ValueError(f"Unsupported operation: {kind}")

        item = dict(operation)

        if kind == "trim":
            start = item.get("start", 0)
            end = item.get("end")

            if isinstance(start, bool) or not isinstance(start, (int, float)):
                raise ValueError("Trim start must be a number.")

            if end is not None and (
                isinstance(end, bool) or not isinstance(end, (int, float))
            ):
                raise ValueError("Trim end must be a number or null.")

            start = float(start)
            end = duration if end is None else float(end)

            if start < 0 or end <= start or end > duration:
                raise ValueError(
                    f"Invalid trim range {start}–{end} seconds "
                    f"for a {duration:.2f}-second video."
                )

            item["start"] = start
            item["end"] = end

        elif kind == "resize":
            if item.get("aspect_ratio") not in SUPPORTED_RATIOS:
                raise ValueError(
                    "Resize aspect_ratio must be 9:16, 16:9, or 1:1."
                )

        elif kind == "speed":
            factor = item.get("factor")

            if (
                isinstance(factor, bool)
                or not isinstance(factor, (int, float))
                or not 0.25 <= float(factor) <= 4.0
            ):
                raise ValueError("Speed factor must be between 0.25 and 4.")

            item["factor"] = float(factor)

        validated.append(item)

    return validated


def _build_video_filter(operation: dict[str, Any]) -> str:
    kind = operation["type"]

    if kind == "resize":
        ratio = operation["aspect_ratio"]

        if ratio == "9:16":
            return (
                "scale=720:1280:force_original_aspect_ratio=increase,"
                "crop=720:1280"
            )

        if ratio == "16:9":
            return (
                "scale=1280:720:force_original_aspect_ratio=increase,"
                "crop=1280:720"
            )

        return (
            "scale=1080:1080:force_original_aspect_ratio=increase,"
            "crop=1080:1080"
        )

    if kind == "speed":
        return f"setpts=PTS/{operation['factor']}"

    return ""


def _get_output_duration(
    operations: list[dict[str, Any]],
    original_duration: float,
) -> float:
    """Calculate approximate final duration after trim and speed edits."""

    duration = original_duration

    for operation in operations:
        if operation["type"] == "trim":
            duration = operation["end"] - operation["start"]

        elif operation["type"] == "speed":
            duration /= operation["factor"]

    if duration <= 0:
        raise ValueError("Calculated output duration is invalid.")

    return duration



def _escape_subtitle_filter_path(path: Path) -> str:
    """Escape a path for FFmpeg's subtitles filter (including Windows paths)."""
    value = path.resolve().as_posix()
    value = value.replace("\\", "/")
    value = value.replace(":", r"\:")
    value = value.replace("'", r"\'")
    value = value.replace(",", r"\,")
    value = value.replace("[", r"\[").replace("]", r"\]")
    return value


def edit_video(
    input_path: str | Path,
    plan: dict[str, Any],
    output_path: str | Path | None = None,
    background_music_path: str | Path | None = None,
    subtitle_path: str | Path | None = None,
    original_audio_volume: float = 1.0,
    music_volume: float = 0.90,
    music_fade_in: float = 2.0,
    music_fade_out: float = 2.0,
    smart_audio_mix: bool = True,
    ducking_threshold: float = 0.03,
    ducking_ratio: float = 8.0,
    ducking_attack: float = 20.0,
    ducking_release: float = 500.0,
) -> dict[str, Any]:
    """
    Apply video edits and optionally mix background music.

    Music settings:
      music_volume: 0.0 to 1.0
      music_fade_in: seconds
      music_fade_out: seconds
      smart_audio_mix: automatically duck music when original audio is loud
      ducking_threshold: sidechain threshold (0.0 to 1.0)
      ducking_ratio: compression ratio (1.0 or greater)
      ducking_attack: compressor attack in milliseconds
      ducking_release: compressor release in milliseconds
    """

    input_path = Path(input_path).resolve()

    if not input_path.is_file():
        raise FileNotFoundError(f"Video file not found: {input_path}")

    ffmpeg = _require_executable(FFMPEG_PATH, "FFmpeg")

    info = get_video_info(input_path)

    operations = validate_plan(
    plan,
    info["duration_seconds"],
    allow_empty=background_music_path is not None,
)

    if not 0 <= music_volume <= 1:
        raise ValueError("Music volume must be between 0 and 1.")
    if not 0 <= original_audio_volume <= 1:
        raise ValueError("Original audio volume must be between 0 and 1.")

    if music_fade_in < 0 or music_fade_out < 0:
        raise ValueError("Music fade durations cannot be negative.")

    if not 0 <= ducking_threshold <= 1:
        raise ValueError("Ducking threshold must be between 0 and 1.")
    if ducking_ratio < 1:
        raise ValueError("Ducking ratio must be at least 1.")
    if ducking_attack <= 0 or ducking_release <= 0:
        raise ValueError("Ducking attack and release must be positive.")

    music_path = None

    if background_music_path is not None:
        music_path = Path(background_music_path).resolve()

        if not music_path.is_file():
            raise FileNotFoundError(
                f"Background music file not found: {music_path}"
            )

    if output_path is None:
        output_path = OUTPUT_DIR / f"{input_path.stem}_edited.mp4"

    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path == input_path:
        raise ValueError("Output path must differ from input path.")

    video_filters = []
    audio_filters = []

    subtitles_file = None
    if subtitle_path is not None:
        subtitles_file = Path(subtitle_path).resolve()
        if not subtitles_file.is_file():
            raise FileNotFoundError(f"Subtitle file not found: {subtitles_file}")

    # PromptCut karaoke mode: when a background song is supplied, mute the
    # video's original audio completely. The song is the only audible track.
    # An explicit "mute" operation also mutes original audio when no song exists.
    remove_original_audio = music_path is not None

    for operation in operations:
        kind = operation["type"]

        if kind == "trim":
            video_filters.extend([
                f"trim=start={operation['start']}:end={operation['end']}",
                "setpts=PTS-STARTPTS",
            ])

            if info["has_audio"]:
                audio_filters.extend([
                    f"atrim=start={operation['start']}:end={operation['end']}",
                    "asetpts=PTS-STARTPTS",
                ])

        elif kind == "resize":
            video_filters.append(_build_video_filter(operation))

        elif kind == "speed":
            video_filters.append(_build_video_filter(operation))

            if info["has_audio"]:
                audio_filters.append(
                    f"atempo={operation['factor']}"
                )

        elif kind == "mute":
            remove_original_audio = True

    output_duration = _get_output_duration(
        operations,
        info["duration_seconds"],
    )

    command = [ffmpeg, "-hide_banner", "-y", "-i", str(input_path)]

    if music_path is not None:
        # Loop music when it is shorter than the edited video.
        command.extend([
            "-stream_loop", "-1",
            "-i", str(music_path),
        ])

    if subtitles_file is not None:
        subtitle_filter = (
            "subtitles=filename='"
            + _escape_subtitle_filter_path(subtitles_file)
            + "'"
        )
        video_filters.append(subtitle_filter)

    if video_filters:
        command.extend(["-vf", ",".join(video_filters)])

    if music_path is None:
        # Original audio only: preserve existing behavior.
        if info["has_audio"] and not remove_original_audio and audio_filters:
            command.extend(["-af", ",".join(audio_filters)])

        if remove_original_audio:
            command.append("-an")

        if info["has_audio"] and not remove_original_audio:
            command.extend(["-map", "0:a?"])

    else:
        # Background music mixing.
        music_filters = [
            f"atrim=duration={output_duration}",
            "asetpts=PTS-STARTPTS",
            f"volume={music_volume}",
        ]

        if music_fade_in > 0:
            music_filters.append(
                f"afade=t=in:st=0:d={min(music_fade_in, output_duration)}"
            )

        if music_fade_out > 0:
            fade_start = max(0, output_duration - music_fade_out)

            music_filters.append(
                f"afade=t=out:st={fade_start}:d="
                f"{min(music_fade_out, output_duration)}"
            )

        filter_parts = []

        if info["has_audio"] and not remove_original_audio:
            original_audio = (
                ",".join(audio_filters) if audio_filters else "anull"
            )
            original_audio += f",volume={original_audio_volume}"

            if smart_audio_mix:
                # Split the original audio: one copy is preserved in the
                # final mix, and the other controls background-music ducking.
                filter_parts.append(
                    f"[0:a]{original_audio},asplit=2[voice][sidechain]"
                )
                filter_parts.append(
                    f"[1:a]{','.join(music_filters)}[music]"
                )
                filter_parts.append(
                    "[music][sidechain]"
                    f"sidechaincompress=threshold={ducking_threshold}:"
                    f"ratio={ducking_ratio}:"
                    f"attack={ducking_attack}:"
                    f"release={ducking_release}[ducked]"
                )
                filter_parts.append(
                    "[voice][ducked]"
                    "amix=inputs=2:duration=first:dropout_transition=0[aout]"
                )
            else:
                filter_parts.append(
                    f"[0:a]{original_audio}[original]"
                )
                filter_parts.append(
                    f"[1:a]{','.join(music_filters)}[music]"
                )
                filter_parts.append(
                    "[original][music]"
                    "amix=inputs=2:duration=first:dropout_transition=0[aout]"
                )
        else:
            filter_parts.append(
                f"[1:a]{','.join(music_filters)}[aout]"
            )

        command.extend([
            "-filter_complex", ";".join(filter_parts),
            "-map", "[aout]",
        ])

    command.extend(["-map", "0:v:0"])

    command.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-t", str(output_duration),
        "-movflags", "+faststart",
        str(output_path),
    ])

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )

    if result.returncode != 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"FFmpeg editing failed: {result.stderr[-3000:]}"
        )

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg did not produce a valid output file.")

    output_info = get_video_info(output_path)

    return {
        "message": "Video edited successfully.",
        "output_path": str(output_path),
        "output_info": output_info,
        "operations_applied": operations,
        "background_music_added": music_path is not None,
        "original_audio_muted": bool(music_path is not None or remove_original_audio),
        "captions_added": subtitles_file is not None,
        "subtitle_path": str(subtitles_file) if subtitles_file else None,
        "smart_audio_mix_enabled": bool(
            music_path is not None
            and info["has_audio"]
            and not remove_original_audio
            and smart_audio_mix
        ),
    }
