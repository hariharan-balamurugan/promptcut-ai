import json
import os

import httpx
import ollama
from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")

client = ollama.Client(
    host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
    timeout=300.0,
)

EDITING_SCHEMA = {
    "type": "object",
    "properties": {
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["trim", "resize", "speed", "mute", "transition"],
                    },
                    "start": {"type": ["number", "null"]},
                    "end": {"type": ["number", "null"]},
                    "aspect_ratio": {"type": ["string", "null"]},
                    "resolution": {"type": ["string", "null"]},
                    "factor": {"type": ["number", "null"]},
                    "transition": {
                        "type": ["string", "null"],
                        "enum": ["fade_in", "fade_out", "zoom_in", "zoom_out", "slide_left_to_right", "slide_right_to_left", "slide_top_to_bottom", "slide_bottom_to_top", None],
                    },
                    "duration": {"type": ["number", "null"]},
                },
                "required": [
                    "type", "start", "end", "aspect_ratio",
                    "resolution", "factor", "transition", "duration",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["operations"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """
You are PromptCut AI's video-editing plan generator.
Convert the user's request into JSON matching the supplied schema.

SUPPORTED OPERATIONS

1. trim:
- start and end are timestamps in seconds.
- For the first 10 seconds: start=0, end=10.
- Never use null for trim start or end.

2. resize:
- aspect_ratio must be "9:16", "16:9", or "1:1".
- Vertical = "9:16"; landscape = "16:9"; square = "1:1".

3. speed:
- factor is the playback-speed multiplier.
- 0.5 means half speed; 0.25 means quarter speed; 2 means double speed.
- Entire video: start=null, end=null.
- Selected range: provide both start and end.
- Never invent timestamps.

4. mute:
- Mute the original video audio.

5. transition:
This release supports fade, zoom, and directional slide-in transitions on one uploaded video.
- "fade in", "fade from black", "start with a fade": transition="fade_in".
- "fade out", "fade to black", "end with a fade": transition="fade_out".
- "zoom in", "zoom into the video", "push in at the beginning": transition="zoom_in".
- "zoom out", "pull back at the end": transition="zoom_out".
- "slide in from the left", "video comes from left to right": transition="slide_left_to_right".
- "slide in from the right", "video comes from right to left": transition="slide_right_to_left".
- "slide in from the top", "video comes from top to bottom": transition="slide_top_to_bottom".
- "slide in from the bottom", "video comes from bottom to top": transition="slide_bottom_to_top".
- Slide transitions start with a black frame and move the full video frame into its normal position.
- Zoom in and slide transitions are applied at the beginning; zoom out and slide transitions are applied at the end only when explicitly requested as an ending effect.
- duration is in seconds. Use 1.0 second by default unless specified.
- duration must be between 0.1 and 5 seconds.
- start=null, end=null, factor=null, aspect_ratio=null, resolution=null.

GENERAL RULES
- Return only valid JSON.
- Every operation must contain all eight fields:
  type, start, end, aspect_ratio, resolution, factor, transition, duration.
- Use null for fields that do not apply.
- Preserve the order of operations.
- Do not invent timestamps or parameters.
- If unclear or unsupported, return {"operations": []}.
- Never claim the video has already been edited.

Example: fade in for 2 seconds
{
  "operations": [{
    "type": "transition",
    "start": null,
    "end": null,
    "aspect_ratio": null,
    "resolution": null,
    "factor": null,
    "transition": "fade_in",
    "duration": 2
  }]
}

Example: fade out for 1 second
{
  "operations": [{
    "type": "transition",
    "start": null,
    "end": null,
    "aspect_ratio": null,
    "resolution": null,
    "factor": null,
    "transition": "fade_out",
    "duration": 1
  }]
}

Example: zoom in for 2 seconds
{
  "operations": [{
    "type": "transition", "start": null, "end": null,
    "aspect_ratio": null, "resolution": null, "factor": null,
    "transition": "zoom_in", "duration": 2
  }]
}

Example: zoom out for 2 seconds
{
  "operations": [{
    "type": "transition", "start": null, "end": null,
    "aspect_ratio": null, "resolution": null, "factor": null,
    "transition": "zoom_out", "duration": 2
  }]
}
"""


def normalize_plan(result: dict) -> dict:
    """Validate and normalize AI-generated editing operations."""
    if not isinstance(result, dict):
        raise ValueError("AI returned an invalid editing plan.")

    operations = result.get("operations")
    if not isinstance(operations, list):
        raise ValueError("AI returned an invalid operations list.")

    normalized = []
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("Invalid editing operation.")

        kind = operation.get("type")
        if kind not in {"trim", "resize", "speed", "mute", "transition"}:
            raise ValueError(f"Unsupported editing operation: {kind}")

        item = {
            "type": kind,
            "start": operation.get("start"),
            "end": operation.get("end"),
            "aspect_ratio": operation.get("aspect_ratio"),
            "resolution": operation.get("resolution"),
            "factor": operation.get("factor"),
            "transition": operation.get("transition"),
            "duration": operation.get("duration"),
        }

        if kind == "trim":
            start, end = item["start"], item["end"]
            if start is None and isinstance(end, (int, float)) and not isinstance(end, bool):
                start = 0
            if (
                isinstance(start, bool) or not isinstance(start, (int, float))
                or isinstance(end, bool) or not isinstance(end, (int, float))
                or start < 0 or end <= start
            ):
                raise ValueError("Trim requires valid numeric start and end timestamps.")
            item["start"], item["end"] = float(start), float(end)

        elif kind == "resize":
            if item["aspect_ratio"] not in {"9:16", "16:9", "1:1"}:
                raise ValueError("Resize ratio must be 9:16, 16:9, or 1:1.")

        elif kind == "speed":
            factor = item["factor"]
            if (
                isinstance(factor, bool) or not isinstance(factor, (int, float))
                or not 0.25 <= float(factor) <= 4.0 or float(factor) == 1.0
            ):
                raise ValueError("Speed factor must be between 0.25 and 4, excluding 1.")
            item["factor"] = float(factor)

            start, end = item["start"], item["end"]
            if (start is None) != (end is None):
                raise ValueError("Speed start and end must both be supplied, or both be null.")
            if start is not None:
                if (
                    isinstance(start, bool) or not isinstance(start, (int, float))
                    or isinstance(end, bool) or not isinstance(end, (int, float))
                    or start < 0 or end <= start
                ):
                    raise ValueError("Speed range must have valid numeric timestamps.")
                item["start"], item["end"] = float(start), float(end)

        elif kind == "transition":
            if item["transition"] not in {
                "fade_in", "fade_out", "zoom_in", "zoom_out",
                "slide_left_to_right", "slide_right_to_left",
                "slide_top_to_bottom", "slide_bottom_to_top",
            }:
                raise ValueError("Unsupported transition. Use fade, zoom, or a directional slide transition.")
            duration = item["duration"]
            if (
                isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not 0.1 <= float(duration) <= 5.0
            ):
                raise ValueError("Transition duration must be between 0.1 and 5 seconds.")
            item["duration"] = float(duration)

        normalized.append(item)

    return {"operations": normalized}


def parse_with_ollama(prompt: str) -> dict:
    if not prompt or not prompt.strip():
        raise ValueError("Please provide an editing prompt.")

    response = client.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt.strip()},
        ],
        format=EDITING_SCHEMA,
        think=False,
        options={"temperature": 0, "num_predict": 700},
        stream=False,
    )

    content = response["message"]["content"]
    if not content or not content.strip():
        raise ValueError("Ollama returned an empty response.")

    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("Ollama returned invalid JSON.") from exc

    return normalize_plan(result)


def parse_with_openrouter(prompt: str) -> dict:
    if not prompt or not prompt.strip():
        raise ValueError("Please provide an editing prompt.")

    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is missing.")
    if not model:
        raise ValueError("OPENROUTER_MODEL is missing.")

    try:
        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-OpenRouter-Title": "PromptCut AI",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt.strip()},
                ],
                "temperature": 0,
                "max_tokens": 700,
                "response_format": {"type": "json_object"},
            },
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise ValueError(f"OpenRouter returned no choices: {data}")

        content = choices[0].get("message", {}).get("content")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise ValueError("OpenRouter returned an empty response.")

        result = json.loads(content)

    except httpx.HTTPStatusError as exc:
        raise ValueError(
            f"OpenRouter API error: HTTP {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except (httpx.RequestError, json.JSONDecodeError) as exc:
        raise ValueError(f"OpenRouter response error: {exc}") from exc

    return normalize_plan(result)
