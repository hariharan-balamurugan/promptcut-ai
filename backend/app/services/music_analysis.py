"""Basic audio feature analysis for PromptCut AI.

Estimates duration, tempo, RMS energy and spectral brightness.
Does not transcribe lyrics or reliably classify vocal/instrumental sections.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import librosa
import numpy as np


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if np.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def analyze_audio(
    audio_path: str | Path,
    *,
    window_seconds: float = 5.0,
    sample_rate: int = 22050,
) -> dict[str, Any]:
    """Analyze an audio file and return JSON-serializable feature estimates."""
    path = Path(audio_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be greater than zero.")

    y, sr = librosa.load(str(path), sr=sample_rate, mono=True)
    if y.size == 0:
        raise ValueError("Audio file contains no readable audio.")

    duration = float(librosa.get_duration(y=y, sr=sr))
    if duration <= 0:
        raise ValueError("Audio duration is zero.")

    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    tempo_array = np.asarray(tempo).reshape(-1)
    bpm = _as_float(tempo_array[0]) if tempo_array.size else 0.0

    hop = 512
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    centroid = librosa.feature.spectral_centroid(
        y=y, sr=sr, n_fft=2048, hop_length=hop
    )[0]
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)

    frames_per_window = max(1, int(round(window_seconds * sr / hop)))
    windows = []
    for start in range(0, len(rms), frames_per_window):
        end = min(len(rms), start + frames_per_window)
        start_sec = start * hop / sr
        end_sec = min(duration, end * hop / sr)
        if end <= start:
            continue

        r = float(np.mean(rms[start:end]))
        c = float(np.mean(centroid[start:end]))
        o = float(np.mean(onset[start:end])) if len(onset) >= end else 0.0
        windows.append({
            "start_time": round(start_sec, 3),
            "end_time": round(end_sec, 3),
            "rms": r,
            "spectral_centroid_hz": c,
            "onset_strength": o,
        })

    max_rms = max((item["rms"] for item in windows), default=0.0)
    for item in windows:
        item["energy"] = round(item["rms"] / max_rms, 4) if max_rms else 0.0
        item["rms"] = round(item["rms"], 6)
        item["spectral_centroid_hz"] = round(item["spectral_centroid_hz"], 2)
        item["onset_strength"] = round(item["onset_strength"], 6)

    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)

    return {
        "file_name": path.name,
        "duration_seconds": round(duration, 3),
        "sample_rate": sr,
        "estimated_bpm": round(bpm, 2) if bpm > 0 else None,
        "beat_count_estimate": int(len(beat_times)),
        "average_rms": round(_as_float(np.mean(rms)), 6),
        "average_spectral_centroid_hz": round(_as_float(np.mean(centroid)), 2),
        "analysis_window_seconds": float(window_seconds),
        "windows": windows,
        "notes": [
            "BPM is an estimate and may be half-time or double-time.",
            "Energy is relative to the loudest window in this audio file.",
            "These features do not determine song emotion.",
            "Lyrics and vocal/instrumental classification require separate stages.",
        ],
    }
