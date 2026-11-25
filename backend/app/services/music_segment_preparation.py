"""
Stage 7.7 - Prepare analyzed music into editor-ready segments.

Input: the dictionary returned by build_music_timeline().
This module does not modify the source timeline or write to SQLite.
"""

from typing import Any, Dict, List, Optional

ENERGY_KEYS = (
    "relative_energy", "energy", "rms", "rms_energy", "average_rms"
)


def _as_float(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _word_record(word: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "text": str(word.get("word", "")).strip(),
        "start_time": round(float(word["start_time"]), 3),
        "end_time": round(float(word["end_time"]), 3),
        "activity_status": word.get("lyric_activity_status", "uncertain"),
    }


def _overlap_seconds(start_a: float, end_a: float,
                     start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def _energy_for_interval(
    energy_windows: List[Dict[str, Any]],
    start_time: float,
    end_time: float,
) -> Dict[str, Any]:
    """Duration-weighted average; returns None if no numeric energy is available."""
    weighted_total = 0.0
    covered_seconds = 0.0
    used_key = None

    for window in energy_windows:
        window_start = _as_float(window.get("start_time"))
        window_end = _as_float(window.get("end_time"))
        if window_start is None or window_end is None or window_end <= window_start:
            continue

        overlap = _overlap_seconds(start_time, end_time, window_start, window_end)
        if overlap <= 0:
            continue

        value = None
        for key in ENERGY_KEYS:
            candidate = _as_float(window.get(key))
            if candidate is not None:
                value = candidate
                used_key = key
                break

        if value is not None:
            weighted_total += value * overlap
            covered_seconds += overlap

    if covered_seconds <= 0:
        return {
            "average_energy": None,
            "energy_source_field": None,
            "energy_coverage_seconds": 0.0,
        }

    return {
        "average_energy": round(weighted_total / covered_seconds, 6),
        "energy_source_field": used_key,
        "energy_coverage_seconds": round(covered_seconds, 3),
    }


def prepare_music_segments(
    timeline_result: Dict[str, Any],
    min_segment_duration: float = 0.5,
    include_uncertain: bool = True,
) -> Dict[str, Any]:
    """
    Convert build_music_timeline() output into editor-ready segments.

    Detected section boundaries and word timestamps are preserved.
    Likely-vocal words are attached only to likely-vocal sections.
    Boundary-conflict and uncertain words remain separately visible.
    """
    if not isinstance(timeline_result, dict):
        raise TypeError("timeline_result must be the dictionary returned by build_music_timeline().")

    combined = timeline_result.get("combined_timeline") or {}
    sections = combined.get("sections") or []
    features = timeline_result.get("audio_features") or {}
    energy_windows = features.get("energy_windows") or []
    bpm = _as_float(features.get("estimated_bpm"))

    if not sections:
        raise ValueError(
            "No combined timeline sections were found. "
            "Run build_music_timeline() successfully before Stage 7.7."
        )
    if min_segment_duration < 0:
        raise ValueError("min_segment_duration cannot be negative.")

    segments = []
    skipped_short_segments = 0

    for section in sections:
        start = _as_float(section.get("start_time"))
        end = _as_float(section.get("end_time"))
        if start is None or end is None or end <= start:
            continue

        duration = end - start
        if duration < min_segment_duration:
            skipped_short_segments += 1
            continue

        activity_type = str(section.get("type", "uncertain")).lower()
        if activity_type not in {"likely_vocal", "likely_instrumental", "uncertain"}:
            activity_type = "uncertain"

        vocal_lyrics = []
        boundary_lyrics = []
        uncertain_lyrics = []

        # Use the complete word list from Stage 7.6 as the source of truth.
        # Section-level "lyrics" lists may be incomplete or differently shaped.
        all_words = combined.get("words") or section.get("lyrics", [])

        for word in all_words:
            if not isinstance(word, dict) or not str(word.get("word", "")).strip():
                continue

            word_start = _as_float(word.get("start_time"))
            word_end = _as_float(word.get("end_time"))
            if word_start is None or word_end is None or word_end <= word_start:
                continue

            # Attach a word only to segments whose time interval it overlaps.
            if _overlap_seconds(start, end, word_start, word_end) <= 0:
                continue

            status = word.get("lyric_activity_status", "uncertain")
            record = _word_record(word)

            if status == "boundary_conflict":
                boundary_lyrics.append(record)
            elif status == "uncertain":
                uncertain_lyrics.append(record)
            elif status == "likely_vocal" and activity_type == "likely_vocal":
                vocal_lyrics.append(record)

        if not include_uncertain and activity_type == "uncertain":
            continue

        energy = _energy_for_interval(energy_windows, start, end)
        segments.append({
            "segment_id": f"segment_{len(segments) + 1:03d}",
            "start_time": round(start, 3),
            "end_time": round(end, 3),
            "duration_seconds": round(duration, 3),
            "segment_type": activity_type,
            "bpm": bpm,
            "average_energy": energy["average_energy"],
            "energy_source_field": energy["energy_source_field"],
            "energy_coverage_seconds": energy["energy_coverage_seconds"],
            "lyrics": vocal_lyrics,
            "boundary_lyrics": boundary_lyrics,
            "uncertain_lyrics": uncertain_lyrics,
            "detection_reason": section.get("reason"),
            "vocal_score_max": section.get("vocal_score_max"),
        })

    type_counts = {
        "likely_vocal": 0,
        "likely_instrumental": 0,
        "uncertain": 0,
    }
    for segment in segments:
        type_counts[segment["segment_type"]] += 1

    return {
        "file_name": timeline_result.get("file_name"),
        "music_id": timeline_result.get("music_id"),
        "duration_seconds": timeline_result.get("duration_seconds"),
        "estimated_bpm": bpm,
        "segment_count": len(segments),
        "segment_type_counts": type_counts,
        "skipped_short_segments": skipped_short_segments,
        "segments": segments,
        "notes": [
            "Segment boundaries are inherited from Stage 7.6 activity sections.",
            "Vocal activity is estimated from Demucs stem-energy comparison.",
            "Lyrics and word timestamps are estimated from Faster-Whisper.",
            "Boundary-conflict and uncertain lyrics are retained separately.",
            "Energy is None if no recognized numeric energy field is available.",
            "This stage prepares segments in memory; it does not modify SQLite.",
        ],
    }
