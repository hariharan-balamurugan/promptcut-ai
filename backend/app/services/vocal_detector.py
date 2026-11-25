from pathlib import Path

import librosa
import numpy as np


def _load_mono_audio(audio_path, sample_rate=22050):
    """Load an audio stem as mono audio at a consistent sample rate."""
    audio, sr = librosa.load(
        str(audio_path),
        sr=sample_rate,
        mono=True
    )
    return audio, sr


def _window_rms(audio, start_sample, end_sample):
    """Calculate RMS energy for one audio window."""
    chunk = audio[start_sample:end_sample]

    if len(chunk) == 0:
        return 0.0

    return float(np.sqrt(np.mean(np.square(chunk))))


def _merge_sections(sections):
    """Merge neighboring windows that have the same classification."""
    if not sections:
        return []

    merged = [sections[0].copy()]

    for section in sections[1:]:
        previous = merged[-1]

        if (
            previous["type"] == section["type"]
            and abs(previous["end_time"] - section["start_time"]) < 0.001
        ):
            previous["end_time"] = section["end_time"]
            previous["vocal_score_max"] = max(
                previous["vocal_score_max"],
                section["vocal_score_max"]
            )
        else:
            merged.append(section.copy())

    for section in merged:
        section["start_time"] = round(section["start_time"], 2)
        section["end_time"] = round(section["end_time"], 2)
        section["vocal_score_max"] = round(
            section["vocal_score_max"], 3
        )

    return merged


def detect_vocal_sections(
    transcription_result,
    vocals_path=None,
    instrumental_path=None,
    window_seconds=1.0
):
    """
    Estimate vocal/instrumental sections by comparing Demucs stems.

    If stem paths are not supplied, retain the older
    transcription-based behavior.

    This is an energy-based estimate, not a perfect vocal detector.
    """
    duration = float(
        transcription_result.get("duration_seconds", 0) or 0
    )
    lyrics = transcription_result.get("lyrics", [])

    # Backward-compatible fallback when separated stems are unavailable.
    if not vocals_path or not instrumental_path:
        language_probability = transcription_result.get(
            "language_probability", 0
        )

        if language_probability < 0.5 or not lyrics:
            return {
                "duration_seconds": duration,
                "overall_status": "uncertain",
                "sections": [{
                    "start_time": 0.0,
                    "end_time": round(duration, 2),
                    "type": "uncertain",
                    "reason": (
                        "Audio stems were not supplied and no reliable "
                        "lyrics were recognized"
                    )
                }],
                "note": (
                    "Transcription-only fallback. Unrecognized audio "
                    "is not confirmed to be instrumental."
                )
            }

        sections = []
        cursor = 0.0

        for lyric in lyrics:
            start = max(0.0, min(float(lyric["start_time"]), duration))
            end = max(start, min(float(lyric["end_time"]), duration))

            if start > cursor:
                sections.append({
                    "start_time": round(cursor, 2),
                    "end_time": round(start, 2),
                    "type": "uncertain",
                    "reason": "No lyrics recognized in this interval"
                })

            if end > start:
                sections.append({
                    "start_time": round(start, 2),
                    "end_time": round(end, 2),
                    "type": "likely_vocal",
                    "reason": "Speech recognition detected lyrics",
                    "text": lyric.get("text", "")
                })

            cursor = max(cursor, end)

        if cursor < duration:
            sections.append({
                "start_time": round(cursor, 2),
                "end_time": round(duration, 2),
                "type": "uncertain",
                "reason": "No lyrics recognized in this interval"
            })

        return {
            "duration_seconds": duration,
            "overall_status": "likely_vocal",
            "sections": sections,
            "note": "Transcription-based estimate only."
        }

    vocals_path = Path(vocals_path)
    instrumental_path = Path(instrumental_path)

    if not vocals_path.exists():
        raise FileNotFoundError(f"Vocals file not found: {vocals_path}")

    if not instrumental_path.exists():
        raise FileNotFoundError(
            f"Instrumental file not found: {instrumental_path}"
        )

    if window_seconds <= 0:
        raise ValueError("window_seconds must be greater than zero")

    print("Loading separated vocal and instrumental stems...")

    sample_rate = 22050
    vocals, sr = _load_mono_audio(vocals_path, sample_rate)
    instrumental, _ = _load_mono_audio(instrumental_path, sample_rate)

    # Use the shortest common duration to avoid indexing beyond either stem.
    common_samples = min(len(vocals), len(instrumental))
    if duration > 0:
        common_samples = min(
            common_samples,
            int(duration * sr)
        )

    vocals = vocals[:common_samples]
    instrumental = instrumental[:common_samples]
    analyzed_duration = common_samples / sr

    if common_samples == 0:
        raise ValueError("The separated audio stems are empty")

    window_samples = max(1, int(window_seconds * sr))
    vocal_rms_values = []
    instrumental_rms_values = []

    for start in range(0, common_samples, window_samples):
        end = min(start + window_samples, common_samples)
        vocal_rms_values.append(_window_rms(vocals, start, end))
        instrumental_rms_values.append(
            _window_rms(instrumental, start, end)
        )

    max_vocal_rms = max(vocal_rms_values, default=0.0)
    max_instrumental_rms = max(instrumental_rms_values, default=0.0)

    # Relative thresholds adapt to the loudness of each audio file.
    vocal_floor = max(0.003, max_vocal_rms * 0.12)
    instrumental_floor = max(0.003, max_instrumental_rms * 0.08)

    raw_sections = []

    for index, (vocal_rms, instrumental_rms) in enumerate(
        zip(vocal_rms_values, instrumental_rms_values)
    ):
        start_time = index * window_seconds
        end_time = min(
            (index + 1) * window_seconds,
            analyzed_duration
        )

        total_rms = vocal_rms + instrumental_rms
        vocal_score = (
            vocal_rms / total_rms if total_rms > 0 else 0.0
        )

        vocal_active = vocal_rms >= vocal_floor
        instrumental_active = (
            instrumental_rms >= instrumental_floor
        )

        if vocal_active and vocal_score >= 0.25:
            section_type = "likely_vocal"
            reason = (
                "Vocal stem has measurable energy relative to "
                "the instrumental stem"
            )
        elif (
            instrumental_active
            and (not vocal_active or vocal_score <= 0.12)
        ):
            section_type = "likely_instrumental"
            reason = (
                "Instrumental stem dominates and vocal stem "
                "has low energy"
            )
        else:
            section_type = "uncertain"
            reason = (
                "Vocal and instrumental stem evidence is mixed "
                "or too weak"
            )

        raw_sections.append({
            "start_time": start_time,
            "end_time": end_time,
            "type": section_type,
            "reason": reason,
            "vocal_score_max": vocal_score
        })

    sections = _merge_sections(raw_sections)

    detected_types = {section["type"] for section in sections}
    if detected_types == {"likely_vocal"}:
        overall_status = "likely_vocal"
    elif detected_types == {"likely_instrumental"}:
        overall_status = "likely_instrumental"
    elif "uncertain" in detected_types or len(detected_types) > 1:
        overall_status = "mixed_or_uncertain"
    else:
        overall_status = "uncertain"

    return {
        "duration_seconds": round(analyzed_duration, 3),
        "overall_status": overall_status,
        "sections": sections,
        "analysis": {
            "method": "Demucs stem RMS energy comparison",
            "window_seconds": window_seconds,
            "vocal_rms_threshold": round(vocal_floor, 6),
            "instrumental_rms_threshold": round(
                instrumental_floor, 6
            ),
            "note": (
                "These are heuristic estimates. Demucs may leave "
                "vocal bleed in the instrumental stem or instrumental "
                "bleed in the vocal stem. Verify important boundaries."
            )
        }
    }
