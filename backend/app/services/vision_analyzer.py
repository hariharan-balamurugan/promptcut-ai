
import json
import os
import re

import httpx
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://127.0.0.1:11434",
).rstrip("/")

OLLAMA_VISION_MODEL = os.getenv(
    "OLLAMA_VISION_MODEL",
    "qwen3.5:4b",
)

# Local vision models can take time; default to 30s so pipeline stays fast.
# Override this in .env with OLLAMA_VISION_TIMEOUT=600 if needed.
OLLAMA_VISION_TIMEOUT = float(
    os.getenv("OLLAMA_VISION_TIMEOUT", "30")
)

ALLOWED_EMOTIONS = {
    "sad",
    "happy",
    "romantic",
    "angry",
    "fear",
    "peaceful",
    "devotional",
    "epic",
    "mystery",
    "neutral",
    "uncertain",
}

EMOTION_CATEGORIES = {
    "sad": "instrumental",
    "happy": "instrumental",
    "romantic": "instrumental",
    "angry": "cinematic",
    "fear": "cinematic",
    "peaceful": "instrumental",
    "devotional": "tamil",
    "epic": "cinematic",
    "mystery": "cinematic",
    "neutral": "instrumental",
    "uncertain": "instrumental",
}


def extract_json(text: str) -> dict:
    """Extract JSON from the Ollama response."""

    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError(
            f"No JSON found in Ollama response: {text[:1000]}"
        )

    return json.loads(text[start:end + 1])



def analyze_frame_emotion(frame: dict) -> dict:
    """Analyze one video frame using local Ollama vision AI."""

    image_base64 = frame.get("image_base64")
    timestamp = float(frame.get("timestamp_seconds", 0))

    if not image_base64:
        raise ValueError("Frame does not contain image data.")

    prompt = """
Analyze the people and visible activity in this image.

Consider:
- Facial expressions
- Smiling, laughing or crying
- Body language and gestures
- Interaction between people
- Visible scene context

Do not infer emotion only from the background or activity.
People playing together does not automatically mean they are happy.
Look for visible evidence.

Choose exactly one emotion:
sad, happy, romantic, angry, fear, peaceful,
devotional, epic, mystery, neutral, uncertain.

Definitions:
sad: visible sadness or crying.
happy: visible smiling, laughter or joy.
romantic: visible affection or tenderness.
angry: visible anger or aggression.
fear: visible fear or panic.
peaceful: visible calmness or relaxation.
devotional: visible prayer or worship.
epic: visible heroic or grand action.
mystery: visible suspenseful or mysterious scene.
neutral: no clear emotional expression.
uncertain: insufficient visual evidence.

Return ONLY a short JSON object in this format:
{
  "primary_emotion": "neutral",
  "confidence": 0.75,
  "visual_evidence": ["people are interacting"],
  "scene": "Two people standing outdoors",
  "reason": "No strong facial emotion is visible"
}

Confidence must be between 0 and 1.
Do not invent facial expressions or events.
"""

    payload = {
        "model": OLLAMA_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_base64],
            }
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_predict": 160,
        },
    }

    print(
        f"Analyzing frame at {timestamp}s "
        f"using Ollama {OLLAMA_VISION_MODEL}"
    )

    try:
        response = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=httpx.Timeout(
                OLLAMA_VISION_TIMEOUT,
                connect=10.0,
            ),
        )

        response.raise_for_status()
        data = response.json()

        message = data.get("message") or {}
        content = message.get("content") or ""

        if not content.strip():
            raise RuntimeError(
                "Ollama returned empty content. "
                f"done_reason={data.get('done_reason')}, "
                f"thinking_length={len(message.get('thinking') or '')}. "
                "Check model support for think=false and num_predict."
            )

        result = extract_json(content)

        emotion = str(
            result.get("primary_emotion", "uncertain")
        ).lower().strip()

        if emotion not in ALLOWED_EMOTIONS:
            emotion = "uncertain"

        try:
            confidence = float(result.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        confidence = max(0.0, min(1.0, confidence))

        evidence = result.get("visual_evidence", [])

        if isinstance(evidence, str):
            evidence = [evidence]

        if not isinstance(evidence, list):
            evidence = []

        return {
            "timestamp_seconds": timestamp,
            "primary_emotion": emotion,
            "confidence": confidence,
            "visual_evidence": [
                str(item) for item in evidence[:5]
            ],
            "scene": str(result.get("scene", "Unknown")),
            "reason": str(result.get("reason", "")),
            "music_category": EMOTION_CATEGORIES[emotion],
            "analysis_status": "success",
        }

    except httpx.ConnectError as exc:
        raise RuntimeError(
            "Cannot connect to Ollama. "
            "Check that Ollama is running."
        ) from exc

    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"Ollama vision analysis timed out at {timestamp}s."
        ) from exc

    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Ollama HTTP error {exc.response.status_code}: "
            f"{exc.response.text[:500]}"
        ) from exc


def analyze_video_timeline(frames: list[dict]) -> dict:
    """
    Analyze every frame separately and generate
    an emotion timeline.
    """

    if not frames:
        raise ValueError("No frames provided.")

    timeline = []

    for frame in frames:

        result = analyze_frame_emotion(frame)

        timeline.append(result)

        print(
            f"TIME: {result['timestamp_seconds']}s | "
            f"EMOTION: {result['primary_emotion']} | "
            f"CONFIDENCE: {result['confidence']}"
        )

    # Determine the most frequently detected emotion.
    emotion_counts = {}

    for item in timeline:

        emotion = item["primary_emotion"]

        if emotion in {"neutral", "uncertain"}:
            continue

        emotion_counts[emotion] = (
            emotion_counts.get(emotion, 0) + 1
        )

    if emotion_counts:

        dominant_emotion = max(
            emotion_counts,
            key=emotion_counts.get,
        )

    else:
        dominant_emotion = "uncertain"

    matching_results = [
        item for item in timeline
        if item["primary_emotion"] == dominant_emotion
    ]

    average_confidence = (
        sum(item["confidence"] for item in matching_results)
        / len(matching_results)
        if matching_results else 0.0
    )

    dominant_category = EMOTION_CATEGORIES[
        dominant_emotion
    ]

    return {
        "dominant_emotion": dominant_emotion,
        "primary_emotion": dominant_emotion,
        "confidence": round(average_confidence, 3),
        "music_category": dominant_category,
        "total_frames_analyzed": len(timeline),
        "interval_seconds": 2,
        "emotion_timeline": timeline,
    }
def analyze_video_timeline(frames: list[dict]) -> dict:
    """Analyze frames and build a fault-tolerant emotion timeline."""

    if not frames:
        raise ValueError("No frames provided.")

    timeline = []
    failed_frames = 0

    for frame in frames:
        timestamp = float(frame.get("timestamp_seconds", 0))

        try:
            result = analyze_frame_emotion(frame)

        except Exception as exc:
            failed_frames += 1

            print(
                f"Vision analysis failed at {timestamp}s: {exc}"
            )

            result = {
                "timestamp_seconds": timestamp,
                "primary_emotion": "uncertain",
                "confidence": 0.0,
                "visual_evidence": [],
                "scene": "Frame analysis failed",
                "reason": str(exc)[:300],
                "music_category": EMOTION_CATEGORIES["uncertain"],
                "analysis_status": "failed",
            }

        timeline.append(result)

        print(
            f"TIME: {timestamp}s | "
            f"EMOTION: {result['primary_emotion']} | "
            f"CONFIDENCE: {result['confidence']} | "
            f"STATUS: {result['analysis_status']}"
        )

    successful_frames = [
        item for item in timeline
        if item["analysis_status"] == "success"
    ]

    if not successful_frames:
        raise RuntimeError(
            "Vision AI failed to analyze every frame. "
            "Check Ollama, model support and available memory."
        )

    # Include neutral as a valid emotion.
    # Exclude uncertain and failed frames.
    emotion_counts = {}

    for item in successful_frames:
        emotion = item["primary_emotion"]

        if emotion == "uncertain":
            continue

        emotion_counts[emotion] = (
            emotion_counts.get(emotion, 0) + 1
        )

    if emotion_counts:
        dominant_emotion = max(
            emotion_counts,
            key=emotion_counts.get,
        )
    else:
        dominant_emotion = "uncertain"

    matching_results = [
        item for item in successful_frames
        if item["primary_emotion"] == dominant_emotion
    ]

    average_confidence = (
        sum(item["confidence"] for item in matching_results)
        / len(matching_results)
        if matching_results else 0.0
    )

    return {
        "dominant_emotion": dominant_emotion,
        "primary_emotion": dominant_emotion,
        "confidence": round(average_confidence, 3),
        "music_category": EMOTION_CATEGORIES[dominant_emotion],
        "total_frames_analyzed": len(timeline),
        "successful_frames": len(successful_frames),
        "failed_frames": failed_frames,
        "analysis_status": (
            "success" if failed_frames == 0 else "partial"
        ),
        "interval_seconds": 2,
        "emotion_timeline": timeline,
    }



def analyze_video_frames(frames: list[dict]) -> dict:
    """
    Backward-compatible function.

    Existing video_service.py can continue calling
    analyze_video_frames().

    The result now also contains emotion_timeline.
    """

    return analyze_video_timeline(frames)
