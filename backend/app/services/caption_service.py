"""Speech caption generation for PromptCut AI.

Uses the existing local Faster-Whisper service and creates ASS karaoke
subtitles from word-level timestamps.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

FFMPEG_PATH = os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg")


def _require_ffmpeg() -> str:
    if not FFMPEG_PATH:
        raise RuntimeError("FFmpeg was not found. Install it or configure FFMPEG_PATH.")
    return FFMPEG_PATH


def _ass_time(seconds: float) -> str:
    """Convert seconds to ASS H:MM:SS.cc timestamp."""
    total_cs = max(0, round(float(seconds) * 100))
    hours, remainder = divmod(total_cs, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def _escape_ass_text(value: str) -> str:
    # ASS uses braces for override tags and backslashes for commands.
    return (
        str(value).replace("\\", "\\\\")
        .replace("{", "\\{").replace("}", "\\}")
        .replace("\n", " ").replace("\r", " ")
    )


def _map_time_to_edited_video(timestamp: float, operations: list[dict[str, Any]]) -> float | None:
    """Map an original-video timestamp through trim and speed operations."""
    current = float(timestamp)
    for operation in operations:
        kind = operation.get("type")
        if kind == "trim":
            start = float(operation.get("start", 0))
            end_value = operation.get("end")
            end = float(end_value) if end_value is not None else float("inf")
            if current < start or current > end:
                return None
            current -= start
        elif kind == "speed":
            current /= float(operation["factor"])
    return max(0.0, current)


def _build_karaoke_text(words: list[dict[str, Any]]) -> str:
    chunks = []
    for item in words:
        word = str(item.get("word", "")).strip()
        if not word:
            continue
        duration = max(
            1,
            round((float(item["end_time"]) - float(item["start_time"])) * 100),
        )
        chunks.append(f"{{\\k{duration}}}{_escape_ass_text(word)}")
    return " ".join(chunks)


def _write_ass_subtitles(
    transcription: dict[str, Any],
    output_path: Path,
    operations: list[dict[str, Any]] | None = None,
) -> int:
    operations = operations or []
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # Active word = yellow; upcoming words = white.
        "Style: Default,Arial,58,&H0000FFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,70,70,145,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    event_count = 0
    for segment in transcription.get("lyrics", []):
        raw_words = segment.get("words") or []
        mapped_words = []
        for word in raw_words:
            try:
                original_start = float(word["start_time"])
                original_end = float(word["end_time"])
            except (KeyError, TypeError, ValueError):
                continue
            mapped_start = _map_time_to_edited_video(original_start, operations)
            mapped_end = _map_time_to_edited_video(original_end, operations)
            if mapped_start is None or mapped_end is None or mapped_end <= mapped_start:
                continue
            mapped_words.append({
                "word": word.get("word", ""),
                "start_time": mapped_start,
                "end_time": mapped_end,
            })

        if mapped_words:
            start_time = mapped_words[0]["start_time"]
            end_time = mapped_words[-1]["end_time"]
            text = _build_karaoke_text(mapped_words)
        else:
            # Fallback for segments without word-level timestamps.
            try:
                start_time = _map_time_to_edited_video(float(segment["start_time"]), operations)
                end_time = _map_time_to_edited_video(float(segment["end_time"]), operations)
            except (KeyError, TypeError, ValueError):
                continue
            if start_time is None or end_time is None or end_time <= start_time:
                continue
            text = _escape_ass_text(segment.get("text", "").strip())

        if not text:
            continue
        lines.append(
            f"Dialogue: 0,{_ass_time(start_time)},{_ass_time(end_time)},"
            f"Default,,0,0,0,,{text}"
        )
        event_count += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return event_count


def generate_video_captions(
    video_path: str | Path,
    output_dir: str | Path,
    operations: list[dict[str, Any]] | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Extract original-video speech, transcribe it, and create ASS captions."""
    video_path = Path(video_path).resolve()
    output_dir = Path(output_dir).resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / f"{video_path.stem}_speech_for_captions.wav"
    subtitle_path = output_dir / f"{video_path.stem}_karaoke.ass"

    command = [
        _require_ffmpeg(), "-hide_banner", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(audio_path),
    ]
    extraction = subprocess.run(
        command, capture_output=True, text=True, timeout=600, check=False
    )
    if extraction.returncode != 0:
        raise RuntimeError(
            "Could not extract the video's original audio for captions: "
            + extraction.stderr[-2000:]
        )

    # Import lazily so the service can still be imported if Faster-Whisper
    # has not been installed/configured yet.
    from app.services.lyrics_transcriber import transcribe_audio

    transcription = transcribe_audio(audio_path, language=language)
    event_count = _write_ass_subtitles(
        transcription, subtitle_path, operations=operations
    )

    return {
        "subtitle_path": str(subtitle_path) if event_count else None,
        "transcription": transcription,
        "caption_count": event_count,
        "language": transcription.get("language"),
        "status": "completed" if event_count else "no_speech_detected",
    }


def generate_audio_captions(
    audio_path: str | Path,
    output_dir: str | Path,
    language: str | None = None,
    max_duration: float | None = None,
) -> dict[str, Any]:
    """Transcribe the selected background song and create karaoke ASS captions.

    The supplied audio should be the exact soundtrack passed to edit_video
    (including the assembled soundtrack when emotion matching is enabled),
    so word timestamps line up with the audible music.
    """
    audio_path = Path(audio_path).resolve()
    output_dir = Path(output_dir).resolve()
    if not audio_path.is_file():
        raise FileNotFoundError(f"Background song not found: {audio_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    subtitle_path = output_dir / f"{audio_path.stem}_song_karaoke.ass"

    # If max_duration is specified and shorter than full song, clip audio first
    # to avoid running Faster-Whisper on several minutes of unneeded audio.
    transcribe_target = audio_path
    if max_duration and max_duration > 0:
        clipped_audio = output_dir / f"{audio_path.stem}_clipped.wav"
        ffmpeg = _require_ffmpeg()
        subprocess.run(
            [
                ffmpeg, "-hide_banner", "-y",
                "-i", str(audio_path),
                "-t", str(max_duration),
                "-vn", "-c:a", "pcm_s16le",
                str(clipped_audio),
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if clipped_audio.is_file() and clipped_audio.stat().st_size > 0:
            transcribe_target = clipped_audio

    # Reuse the existing local Faster-Whisper model. Do not extract audio from
    # the video: captions must come from the selected background song.
    from app.services.lyrics_transcriber import transcribe_audio

    transcription = transcribe_audio(transcribe_target, language=language)
    event_count = _write_ass_subtitles(transcription, subtitle_path)

    return {
        "subtitle_path": str(subtitle_path) if event_count else None,
        "transcription": transcription,
        "caption_count": event_count,
        "language": transcription.get("language"),
        "status": "completed" if event_count else "no_lyrics_detected",
        "caption_source": "background_music",
        "note": (
            "Automatic song lyric recognition can be inaccurate, especially "
            "for instrumental music, overlapping vocals, or heavily processed singing."
        ),
    }
