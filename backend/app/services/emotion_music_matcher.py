
"""
Stage 7.8 - Emotion-based music segment matching.

Inputs:
1. Video emotion analysis returned by analyze_video_frames().
2. Music segments returned by prepare_music_segments().

This module ranks music segments for each video emotion interval.
It does not modify the source files, database, or original timeline.
"""

from typing import Any


# Heuristic preferences. These are initial configurable rules,
# not scientifically validated emotion-to-music mappings.

EMOTION_RULES = {
    "sad": {
        "preferred_types": ["likely_instrumental"],
        "target_energy": 0.25,
        "bpm_range": (60, 110),
    },
    "happy": {
        "preferred_types": ["likely_vocal", "likely_instrumental"],
        "target_energy": 0.75,
        "bpm_range": (100, 160),
    },
    "romantic": {
        "preferred_types": ["likely_vocal", "likely_instrumental"],
        "target_energy": 0.45,
        "bpm_range": (65, 125),
    },
    "angry": {
        "preferred_types": ["likely_instrumental", "likely_vocal"],
        "target_energy": 0.85,
        "bpm_range": (100, 180),
    },
    "fear": {
        "preferred_types": ["likely_instrumental"],
        "target_energy": 0.35,
        "bpm_range": (50, 120),
    },
    "peaceful": {
        "preferred_types": ["likely_instrumental"],
        "target_energy": 0.25,
        "bpm_range": (50, 105),
    },
    "devotional": {
        "preferred_types": ["likely_vocal", "likely_instrumental"],
        "target_energy": 0.50,
        "bpm_range": (60, 130),
    },
    "epic": {
        "preferred_types": ["likely_instrumental", "likely_vocal"],
        "target_energy": 0.85,
        "bpm_range": (100, 180),
    },
    "mystery": {
        "preferred_types": ["likely_instrumental"],
        "target_energy": 0.35,
        "bpm_range": (50, 120),
    },
    "neutral": {
        "preferred_types": ["likely_instrumental", "likely_vocal"],
        "target_energy": 0.50,
        "bpm_range": (60, 140),
    },
    "uncertain": {
        "preferred_types": ["likely_instrumental", "likely_vocal"],
        "target_energy": 0.50,
        "bpm_range": (60, 140),
    },
}


def _number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_video_intervals(
    video_analysis: dict,
) -> list[dict]:
    """Convert frame-level emotions into time intervals."""

    frames = video_analysis.get("emotion_timeline") or []

    if not frames:
        raise ValueError(
            "No emotion_timeline found in video analysis."
        )

    frames = sorted(
        frames,
        key=lambda item: float(
            item.get("timestamp_seconds", 0)
        ),
    )

    default_interval = _number(
        video_analysis.get("interval_seconds")
    ) or 2.0

    video_duration = _number(
        video_analysis.get("video_duration_seconds")
    )

    intervals = []

    for index, frame in enumerate(frames):

        start = _number(frame.get("timestamp_seconds"))

        if start is None or start < 0:
            continue

        if index + 1 < len(frames):
            end = _number(
                frames[index + 1].get("timestamp_seconds")
            )
        else:
            end = (
                video_duration
                if video_duration is not None
                else start + default_interval
            )

        if end is None or end <= start:
            continue

        emotion = str(
            frame.get("primary_emotion", "uncertain")
        ).lower().strip()

        if emotion not in EMOTION_RULES:
            emotion = "uncertain"

        confidence = _number(frame.get("confidence")) or 0.0
        confidence = max(0.0, min(1.0, confidence))

        intervals.append({
            "start_time": round(start, 3),
            "end_time": round(end, 3),
            "duration_seconds": round(end - start, 3),
            "emotion": emotion,
            "confidence": round(confidence, 3),
            "scene": frame.get("scene", ""),
            "visual_evidence": frame.get(
                "visual_evidence", []
            ),
        })

    if not intervals:
        raise ValueError(
            "No valid video emotion intervals could be created."
        )

    return intervals


def _energy_score(
    energy: float | None,
    target_energy: float,
    min_energy: float,
    max_energy: float,
) -> float:
    if energy is None:
        return 10.0

    if max_energy == min_energy:
        normalized = 0.5
    else:
        normalized = (
            (energy - min_energy)
            / (max_energy - min_energy)
        )

    distance = abs(normalized - target_energy)

    return max(0.0, 20.0 * (1.0 - distance))


def _bpm_score(
    bpm: float | None,
    bpm_range: tuple,
) -> float:
    if bpm is None or bpm <= 0:
        return 7.5

    low, high = bpm_range

    if low <= bpm <= high:
        return 15.0

    distance = (
        low - bpm if bpm < low else bpm - high
    )

    return max(0.0, 15.0 - distance * 0.25)


def _segment_score(
    emotion: str,
    confidence: float,
    segment: dict,
    min_energy: float,
    max_energy: float,
) -> dict:

    rules = EMOTION_RULES[emotion]

    segment_type = segment.get(
        "segment_type", "uncertain"
    )

    preferred_types = rules["preferred_types"]

    if segment_type in preferred_types:
        type_score = 55.0
        type_reason = "Preferred vocal/instrumental type"
    elif segment_type == "uncertain":
        type_score = 20.0
        type_reason = "Music activity classification uncertain"
    else:
        type_score = 30.0
        type_reason = "Music activity type is less preferred"

    energy = _number(segment.get("average_energy"))

    energy_points = _energy_score(
        energy,
        rules["target_energy"],
        min_energy,
        max_energy,
    )

    bpm = _number(segment.get("bpm"))

    bpm_points = _bpm_score(
        bpm,
        rules["bpm_range"],
    )

    # Video confidence contributes up to 10 points.
    confidence_points = confidence * 10.0

    total = (
        type_score
        + energy_points
        + bpm_points
        + confidence_points
    )

    return {
        "score": round(min(100.0, total), 2),
        "score_breakdown": {
            "activity_type": round(type_score, 2),
            "energy": round(energy_points, 2),
            "bpm": round(bpm_points, 2),
            "video_confidence": round(
                confidence_points, 2
            ),
        },
        "reasons": [
            type_reason,
            f"Energy score: {energy_points:.2f}/20",
            f"BPM score: {bpm_points:.2f}/15",
        ],
    }


def match_emotion_to_music(
    video_analysis: dict,
    prepared_music: dict,
    top_k: int = 3,
    min_segment_duration: float = 1.0,
) -> dict:
    """
    Rank prepared music segments for every video emotion interval.

    Returns an editor-ready matching plan.
    """

    if not isinstance(video_analysis, dict):
        raise TypeError("video_analysis must be a dictionary.")

    if not isinstance(prepared_music, dict):
        raise TypeError("prepared_music must be a dictionary.")

    if top_k < 1:
        raise ValueError("top_k must be at least 1.")

    if min_segment_duration < 0:
        raise ValueError(
            "min_segment_duration cannot be negative."
        )

    music_segments = prepared_music.get("segments") or []

    if not music_segments:
        raise ValueError("No prepared music segments found.")

    valid_segments = []

    for segment in music_segments:

        start = _number(segment.get("start_time"))
        end = _number(segment.get("end_time"))

        if start is None or end is None or end <= start:
            continue

        if end - start < min_segment_duration:
            continue

        valid_segments.append(segment)

    if not valid_segments:
        raise ValueError(
            "No music segments meet the minimum duration."
        )

    energy_values = [
        value
        for segment in valid_segments
        if (
            value := _number(segment.get("average_energy"))
        ) is not None
    ]

    min_energy = min(energy_values) if energy_values else 0.0
    max_energy = max(energy_values) if energy_values else 1.0

    video_intervals = _build_video_intervals(
        video_analysis
    )

    matching_plan = []

    for video_interval in video_intervals:

        emotion = video_interval["emotion"]
        confidence = video_interval["confidence"]

        ranked = []

        for segment in valid_segments:

            result = _segment_score(
                emotion,
                confidence,
                segment,
                min_energy,
                max_energy,
            )

            ranked.append({
                "segment_id": segment.get("segment_id"),
                "music_start_time": segment["start_time"],
                "music_end_time": segment["end_time"],
                "music_duration_seconds": segment["duration_seconds"],
                "segment_type": segment.get("segment_type"),
                "bpm": segment.get("bpm"),
                "average_energy": segment.get("average_energy"),
                "lyrics": segment.get("lyrics", []),
                "score": result["score"],
                "score_breakdown": result["score_breakdown"],
                "reasons": result["reasons"],
            })

        ranked.sort(
            key=lambda item: (
                -item["score"],
                item["music_start_time"],
            )
        )

        matching_plan.append({
            "video_start_time": video_interval["start_time"],
            "video_end_time": video_interval["end_time"],
            "video_duration_seconds": video_interval[
                "duration_seconds"
            ],
            "emotion": emotion,
            "confidence": confidence,
            "scene": video_interval["scene"],
            "top_matches": ranked[:top_k],
        })

    return {
        "stage": "7.8",
        "music_file": prepared_music.get("file_name"),
        "music_id": prepared_music.get("music_id"),
        "video_interval_count": len(matching_plan),
        "music_segments_considered": len(valid_segments),
        "matching_plan": matching_plan,
        "notes": [
            "Scores are heuristic rankings, not trained predictions.",
            "Energy is normalized relative to the supplied music segments.",
            "Lyrics are retained but are not semantically interpreted.",
            "This stage ranks segments; it does not assemble or export audio.",
            "The same music segment may be recommended for multiple scenes.",
        ],
    }
