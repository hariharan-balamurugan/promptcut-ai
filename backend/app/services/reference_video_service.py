"""
reference_video_service.py — Reference video style analysis for PromptCut AI.

Completely isolated module; no shared state with the rest of the app.

Public API
----------
analyze_reference_video(video_path)  -> dict
save_reference_profile(ref_id, profile)
load_reference_profile(ref_id)       -> dict
apply_reference_style(plan, style_profile) -> dict
"""

import json
import subprocess
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR        = Path(__file__).resolve().parents[3]   # backend/
REFERENCES_DIR  = BASE_DIR / "data" / "references"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ffprobe_json(video_path: Path) -> dict:
    """Run ffprobe and return parsed JSON."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _get_video_stream(probe: dict) -> dict:
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    return {}


def _duration_from_probe(probe: dict) -> float:
    fmt = probe.get("format", {})
    try:
        return float(fmt.get("duration", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _avg_frame_rate(video_stream: dict) -> float:
    """Parse 'avg_frame_rate' like '30000/1001'."""
    raw = video_stream.get("avg_frame_rate", "0/1")
    try:
        num, den = raw.split("/")
        den = int(den)
        return float(num) / den if den else 0.0
    except Exception:
        return 0.0


def _extract_keyframe_count(video_path: Path) -> int:
    """Count keyframes as a proxy for scene cuts."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-select_streams", "v:0",
        "-skip_frame", "noref",
        "-show_entries", "frame=pict_type",
        "-print_format", "csv=p=0",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        lines  = result.stdout.strip().splitlines()
        return sum(1 for ln in lines if ln.strip() == "I")
    except Exception:
        return 0


def _extract_sample_frames(video_path: Path, count: int = 6) -> list[Path]:
    """Extract up to *count* equally-spaced JPEG frames to /tmp."""
    import tempfile
    out_dir = Path(tempfile.mkdtemp(prefix="ref_frames_"))
    frames  = []

    try:
        probe    = _ffprobe_json(video_path)
        duration = _duration_from_probe(probe)
        if duration <= 0:
            return frames

        for i in range(count):
            t        = duration * i / count
            out_file = out_dir / f"frame_{i:03d}.jpg"
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(t),
                "-i", str(video_path),
                "-frames:v", "1",
                "-q:v", "2",
                str(out_file),
            ]
            subprocess.run(cmd, capture_output=True, timeout=30)
            if out_file.is_file():
                frames.append(out_file)
    except Exception as exc:
        print(f"[reference] Frame extraction failed: {exc}")

    return frames


def _estimate_color_tone(frames: list[Path]) -> str:
    """
    Very lightweight heuristic: average R/G/B of sampled frames.
    Returns 'warm' | 'cool' | 'cinematic' | 'neutral'.
    """
    if not frames:
        return "neutral"

    try:
        import struct

        total_r = total_g = total_b = pixel_count = 0

        for frame in frames[:4]:
            # Read first few bytes to check JFIF header then sample.
            raw = frame.read_bytes()

            # Simple row-based sampling via ffprobe lavfi.
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-f", "lavfi",
                f"-i", f"movie={frame.as_posix()},signalstats",
                "-show_entries", "frame_tags=lavfi.signalstats.YAVG,lavfi.signalstats.UAVG,lavfi.signalstats.VAVG",
                "-print_format", "json",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                for fr in data.get("frames", []):
                    tags = fr.get("tags", {})
                    u    = float(tags.get("lavfi.signalstats.UAVG", 128))
                    v    = float(tags.get("lavfi.signalstats.VAVG", 128))
                    # U < 128 → blue-ish (cool), V > 128 → red/yellow (warm)
                    total_b += (128 - u)
                    total_r += (v - 128)
                    pixel_count += 1

        if pixel_count == 0:
            return "neutral"

        avg_warm = total_r / pixel_count
        avg_cool = total_b / pixel_count

        if avg_warm > 10:
            return "warm"
        if avg_cool > 10:
            return "cool"
        if abs(avg_warm) < 5 and abs(avg_cool) < 5:
            return "cinematic"
        return "neutral"

    except Exception:
        return "neutral"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_reference_video(video_path: Path) -> dict:
    """
    Analyze a reference video and return a style profile.

    Returns
    -------
    {
        "reference_id": str,
        "style_profile": {
            "pacing": "slow|medium|fast",
            "primary_transitions": [...],
            "color_tone": "warm|cool|neutral|cinematic",
            "avg_cut_duration": float,
            "has_slow_motion": bool,
            "has_fast_motion": bool,
            "aspect_ratio": str,
            "estimated_mood": str,
        }
    }
    """
    video_path   = Path(video_path).resolve()
    reference_id = uuid.uuid4().hex

    probe        = _ffprobe_json(video_path)
    video_stream = _get_video_stream(probe)
    duration     = _duration_from_probe(probe)
    fps          = _avg_frame_rate(video_stream)

    # Aspect ratio
    width  = int(video_stream.get("width",  0) or 0)
    height = int(video_stream.get("height", 0) or 0)
    if width and height:
        from math import gcd
        g = gcd(width, height)
        aspect_ratio = f"{width // g}:{height // g}"
    else:
        aspect_ratio = "unknown"

    # Scene-cut count → avg cut duration
    keyframes       = _extract_keyframe_count(video_path)
    cut_count       = max(keyframes - 1, 0)   # number of transitions
    avg_cut_duration = (duration / cut_count) if cut_count > 0 else duration

    # Pacing
    cuts_per_min = (cut_count / duration * 60) if duration > 0 else 0
    if cuts_per_min > 20:
        pacing = "fast"
    elif cuts_per_min > 6:
        pacing = "medium"
    else:
        pacing = "slow"

    # Motion detection via video stream metadata
    has_slow_motion = False
    has_fast_motion = False
    if fps > 0:
        r_num_str = video_stream.get("r_frame_rate", "0/1")
        try:
            rn, rd  = r_num_str.split("/")
            native_fps = float(rn) / float(rd) if float(rd) else fps
        except Exception:
            native_fps = fps
        if native_fps > fps * 1.8:
            has_slow_motion = True
        if native_fps < fps * 0.6:
            has_fast_motion = True

    # Dominant transitions (heuristic from pacing + keyframe pattern)
    transitions: list[str] = []
    if pacing == "fast":
        transitions = ["hard_cut", "zoom_out"]
    elif pacing == "medium":
        transitions = ["fade_in", "hard_cut"]
    else:
        transitions = ["fade_in", "fade_out", "dissolve"]

    # Color tone
    frames     = _extract_sample_frames(video_path, count=6)
    color_tone = _estimate_color_tone(frames)

    # Mood estimation
    if pacing == "fast" and color_tone in ("warm", "cinematic"):
        mood = "energetic"
    elif pacing == "slow" and color_tone == "cool":
        mood = "melancholic"
    elif pacing == "slow" and color_tone == "warm":
        mood = "peaceful"
    elif pacing == "fast":
        mood = "dynamic"
    else:
        mood = "neutral"

    # Vision AI enhancement (optional)
    try:
        from app.services.vision_analyzer import analyze_video_frames
        if frames:
            vision = analyze_video_frames(frames)
            if vision.get("primary_emotion"):
                mood = vision["primary_emotion"]
    except Exception as exc:
        print(f"[reference] Vision AI optional step skipped: {exc}")

    style_profile = {
        "pacing":              pacing,
        "primary_transitions": transitions,
        "color_tone":          color_tone,
        "avg_cut_duration":    round(avg_cut_duration, 2),
        "has_slow_motion":     has_slow_motion,
        "has_fast_motion":     has_fast_motion,
        "aspect_ratio":        aspect_ratio,
        "estimated_mood":      mood,
    }

    return {
        "reference_id":  reference_id,
        "style_profile": style_profile,
    }


def save_reference_profile(reference_id: str, profile: dict) -> None:
    """Persist a reference profile to backend/data/references/{id}.json."""
    REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
    out = REFERENCES_DIR / f"{reference_id}.json"
    out.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[reference] Profile saved: {out}")


def load_reference_profile(reference_id: str) -> dict:
    """Load a saved reference profile; raises FileNotFoundError if missing."""
    path = REFERENCES_DIR / f"{reference_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Reference profile not found: {reference_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def apply_reference_style(plan: dict, style_profile: dict) -> dict:
    """
    Merge a reference style profile into an editing plan.

    The plan dict (as produced by the prompt parser) may contain keys like
    'transitions', 'speed', 'color_grading', 'mood', etc.
    We inject / override relevant keys from the style profile.
    """
    merged = dict(plan)   # shallow copy; callers should not share the dict

    pacing      = style_profile.get("pacing", "medium")
    transitions = style_profile.get("primary_transitions", [])
    color_tone  = style_profile.get("color_tone", "neutral")
    mood        = style_profile.get("estimated_mood", "")
    has_slow    = style_profile.get("has_slow_motion", False)

    # Speed
    speed_map = {"slow": 0.75, "medium": 1.0, "fast": 1.5}
    if "speed" not in merged or merged.get("speed") == 1.0:
        merged["speed"] = speed_map.get(pacing, 1.0)

    # Transitions
    if transitions:
        merged["transitions"] = transitions

    # Color grading hint
    tone_map = {
        "warm":      "warm_grade",
        "cool":      "cool_grade",
        "cinematic": "cinematic_grade",
        "neutral":   "natural",
    }
    merged["color_grading"] = tone_map.get(color_tone, "natural")

    # Mood / atmosphere
    if mood:
        merged["mood"] = mood

    # Slow-motion flag
    if has_slow and "slow_motion" not in merged:
        merged["slow_motion"] = True

    return merged
