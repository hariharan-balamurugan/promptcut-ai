
import json
import os
import shutil
import subprocess
import uuid
from fractions import Fraction
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

FFMPEG_PATH = os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg")
FFPROBE_PATH = os.getenv("FFPROBE_PATH") or shutil.which("ffprobe")

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_OPERATIONS = {"trim", "resize", "speed", "mute", "transition"}
SUPPORTED_TRANSITIONS = {
    "fade_in", "fade_out", "zoom_in", "zoom_out",
    "slide_left_to_right", "slide_right_to_left",
    "slide_top_to_bottom", "slide_bottom_to_top",
}
SUPPORTED_RATIOS = {"9:16", "16:9", "1:1"}


def _require_executable(path: str | None, name: str) -> str:
    if not path:
        raise RuntimeError(
            f"{name} was not found. Install FFmpeg and add its bin folder "
            "to PATH, or configure its executable path in .env."
        )
    return path


def _parse_frame_rate(value: str | None) -> float:
    """Convert an FFprobe frame-rate fraction to a usable FPS value."""
    try:
        rate = float(Fraction(value)) if value and value != "0/0" else 30.0
        return rate if 1.0 <= rate <= 120.0 else 30.0
    except (ValueError, ZeroDivisionError):
        return 30.0


def get_video_info(input_path: str | Path) -> dict[str, Any]:
    input_path = Path(input_path).resolve()

    if not input_path.is_file():
        raise FileNotFoundError(f"Video file not found: {input_path}")

    ffprobe = _require_executable(FFPROBE_PATH, "FFprobe")

    command = [
        ffprobe,
        "-v", "error",
        "-show_entries",
        "format=duration,format_name:stream=codec_type,width,height,avg_frame_rate,r_frame_rate",
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
        "frame_rate": _parse_frame_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")),
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
    """Validate editing operations against the original video duration."""

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
            item["start"], item["end"] = start, end

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
                or float(factor) == 1.0
            ):
                raise ValueError(
                    "Speed factor must be between 0.25 and 4, excluding 1."
                )
            item["factor"] = float(factor)

            start, end = item.get("start"), item.get("end")
            if start is None and end is None:
                pass  # Entire video
            elif start is None or end is None:
                raise ValueError(
                    "Speed start and end must both be provided for "
                    "selected-range speed changes."
                )
            else:
                if (
                    isinstance(start, bool) or not isinstance(start, (int, float))
                    or isinstance(end, bool) or not isinstance(end, (int, float))
                ):
                    raise ValueError("Speed start and end must be numbers.")
                start, end = float(start), float(end)
                if start < 0 or end <= start or end > duration:
                    raise ValueError(
                        f"Invalid speed range {start}–{end} seconds "
                        f"for a {duration:.2f}-second video."
                    )
                item["start"], item["end"] = start, end

        elif kind == "transition":
            transition = item.get("transition")
            transition_duration = item.get("duration", 1.0)

            if transition not in SUPPORTED_TRANSITIONS:
                raise ValueError(
                    "Unsupported transition. Use fade, zoom, or a directional slide transition."
                )

            if (
                isinstance(transition_duration, bool)
                or not isinstance(transition_duration, (int, float))
                or not 0.1 <= float(transition_duration) <= 5.0
            ):
                raise ValueError(
                    "Transition duration must be between 0.1 and 5 seconds."
                )

            item["duration"] = float(transition_duration)

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
        factor = operation["factor"]
        start = operation.get("start")
        end = operation.get("end")

        interpolation = (
            "minterpolate=fps=60:"
            "mi_mode=mci:"
            "mc_mode=aobmc:"
            "me_mode=bidir:"
            "vsbmc=1"
        )

        if start is None and end is None:
            # Slow down the entire video.
            return (
                f"setpts=PTS/{factor},"
                f"{interpolation}"
            )

        # Slow down only the selected section.
        expression = (
            f"if(lt(T\\,{start})\\,PTS\\,"
            f"if(lt(T\\,{end})\\,"
            f"({start}+(T-{start})/{factor})/TB\\,"
            f"({start}+({end}-{start})/{factor}"
            f"+(T-{end}))/TB))"
        )

        return (
            f"setpts='{expression}',"
            f"{interpolation}"
        )

    return ""


def _get_output_duration(
    operations: list[dict[str, Any]],
    original_duration: float,
) -> float:
    """Estimate output duration for the supported trim/speed operation sequence."""

    duration = original_duration
    source_start = 0.0
    source_end = original_duration

    for operation in operations:
        if operation["type"] == "trim":
            source_start = operation["start"]
            source_end = operation["end"]
            duration = source_end - source_start

        elif operation["type"] == "speed":
            factor = operation["factor"]
            start = operation.get("start")
            end = operation.get("end")

            if start is None and end is None:
                duration /= factor
            else:
                # Speed ranges are expressed against the original input timeline.
                # Account for an earlier trim by intersecting with the kept range.
                kept_start = max(start, source_start)
                kept_end = min(end, source_end)
                if kept_end <= kept_start:
                    continue
                duration += (kept_end - kept_start) * (1.0 / factor - 1.0)

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
                if operation.get("start") is None and operation.get("end") is None:
                    audio_filters.append(f"atempo={operation['factor']}")
                # Selected-range audio time-stretching is not applied here.
                # PromptCut's background-music mode mutes source audio, so this
                # does not affect the selected-song/karaoke workflow.

        elif kind == "mute":
            remove_original_audio = True

        elif kind == "transition":
            # Added after output duration is calculated below.
            continue

    output_duration = _get_output_duration(
        operations,
        info["duration_seconds"],
    )

    for operation in operations:
        if operation["type"] != "transition":
            continue

        transition = operation["transition"]
        transition_duration = min(operation["duration"], output_duration)

        if transition == "fade_in":
            video_filters.append(
                f"fade=t=in:st=0:d={transition_duration}"
            )
        elif transition == "fade_out":
            fade_start = max(0.0, output_duration - transition_duration)
            video_filters.append(
                f"fade=t=out:st={fade_start}:d={transition_duration}"
            )
        elif transition in {"zoom_in", "zoom_out"}:
            width = int(info["width"])
            height = int(info["height"])
            fps = info.get("frame_rate", 30.0)
            total_frames = max(1, round(output_duration * fps))
            transition_frames = max(1, round(transition_duration * fps))

            if transition == "zoom_in":
                zoom_expression = (
                    f"if(lte(on,{transition_frames}),"
                    f"1+0.18*on/{transition_frames},1.18)"
                )
            else:
                start_frame = max(0, total_frames - transition_frames)
                zoom_expression = (
                    f"if(gte(on,{start_frame}),"
                    f"1.18-0.18*(on-{start_frame})/{transition_frames},1.18)"
                )

            video_filters.append(
                "zoompan="
                f"z='{zoom_expression}':"
                "x='iw/2-(iw/zoom/2)':"
                "y='ih/2-(ih/zoom/2)':"
                f"d=1:s={width}x{height}:fps={fps:.6f}"
            )
        elif transition in {
            "slide_left_to_right", "slide_right_to_left",
            "slide_top_to_bottom", "slide_bottom_to_top",
        }:
            # Move the complete frame from outside the canvas into place.
            # The padded area is black; crop evaluates its position on every frame.
            if transition == "slide_left_to_right":
                video_filters.append(
                    "pad=2*iw:ih:color=black:x=0:y=0,"
                    f"crop=iw/2:ih:x='(iw/2)*(1-min(t/{transition_duration},1))':y=0"
                )
            elif transition == "slide_right_to_left":
                video_filters.append(
                    "pad=2*iw:ih:color=black:x=iw:y=0,"
                    f"crop=iw/2:ih:x='(iw/2)*min(t/{transition_duration},1)':y=0"
                )
            elif transition == "slide_top_to_bottom":
                video_filters.append(
                    "pad=iw:2*ih:color=black:x=0:y=0,"
                    f"crop=iw:ih/2:x=0:y='(ih/2)*(1-min(t/{transition_duration},1))'"
                )
            else:
                video_filters.append(
                    "pad=iw:2*ih:color=black:x=0:y=ih,"
                    f"crop=iw:ih/2:x=0:y='(ih/2)*min(t/{transition_duration},1)'"
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
        "-preset", "ultrafast",
        "-crf", "23",
        "-threads", "0",
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
        "transitions_applied": [
            op for op in operations if op["type"] == "transition"
        ],
        "selected_range_original_audio_speed_adjusted": not any(
            op["type"] == "speed" and op.get("start") is not None
            for op in operations
        ),
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


def merge_video_clips(
    input_paths: list[str | Path],
    output_path: str | Path | None = None,
    target_width: int | None = None,
    target_height: int | None = None,
    target_fps: float = 30.0,
) -> dict[str, Any]:
    """
    Concatenate multiple video files (2 or more) into a single cohesive video.
    Handles videos of differing dimensions, aspect ratios, and frame rates by
    normalizing each clip with letterboxing/pillarboxing to a unified canvas.
    Handles videos with or without audio tracks by synthesizing silence when needed.
    """
    if not input_paths or len(input_paths) < 2:
        raise ValueError("At least 2 video files are required to merge.")

    resolved_paths = [Path(p).resolve() for p in input_paths]
    for p in resolved_paths:
        if not p.is_file():
            raise FileNotFoundError(f"Video file not found: {p}")

    ffmpeg = _require_executable(FFMPEG_PATH, "FFmpeg")

    # Inspect all clips
    infos = [get_video_info(p) for p in resolved_paths]

    # Determine canvas resolution if not explicitly specified
    if not target_width or not target_height:
        portrait_count = sum(1 for info in infos if (info.get("height") or 0) > (info.get("width") or 0))
        is_mostly_portrait = portrait_count > len(infos) / 2
        if is_mostly_portrait:
            target_width = target_width or 1080
            target_height = target_height or 1920
        else:
            target_width = target_width or 1920
            target_height = target_height or 1080

    if output_path is None:
        output_path = OUTPUT_DIR / f"merged_{uuid.uuid4().hex[:12]}.mp4"
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [ffmpeg, "-hide_banner", "-y"]
    for p in resolved_paths:
        command.extend(["-i", str(p)])

    filter_complex_parts = []
    n = len(resolved_paths)

    for i, (p, info) in enumerate(zip(resolved_paths, infos)):
        # Video stream standardization
        filter_complex_parts.append(
            f"[{i}:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={target_fps}[v{i}]"
        )
        # Audio stream standardization
        dur = info.get("duration_seconds", 1.0)
        if info.get("has_audio"):
            filter_complex_parts.append(
                f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo[a{i}]"
            )
        else:
            filter_complex_parts.append(
                f"aevalsrc=0:d={dur}:c=stereo:s=44100[a{i}]"
            )

    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_complex_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[vout][aout]")

    filter_complex_str = ";".join(filter_complex_parts)

    command.extend([
        "-filter_complex", filter_complex_str,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
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
        raise RuntimeError(f"FFmpeg video merge failed: {result.stderr[-3000:]}")

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg merge did not produce a valid output video.")

    merged_info = get_video_info(output_path)
    return {
        "output_path": str(output_path),
        "merged_clips_count": n,
        "total_duration": merged_info.get("duration_seconds", 0.0),
        "output_info": merged_info,
        "clips": [
            {
                "filename": p.name,
                "duration_seconds": info.get("duration_seconds", 0.0),
                "width": info.get("width"),
                "height": info.get("height"),
            }
            for p, info in zip(resolved_paths, infos)
        ],
    }

