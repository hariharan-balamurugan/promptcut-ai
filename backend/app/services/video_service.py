import json
import shutil
import subprocess
import sys
from pathlib import Path
import tempfile

from app.services.online_music_service import get_online_music
from app.services.music_catalog import search_tracks

from app.services.prompt_parser import (
    parse_with_ollama,
    parse_with_openrouter,
)

from app.services.caption_service import generate_audio_captions

from app.services.video_editor import (
    edit_video,
    get_video_info,
    merge_video_clips,
)

from app.services.video_analysis import extract_video_frames
from app.services.vision_analyzer import analyze_video_frames
from app.services.video_analysis import (
    extract_video_frames,
    get_video_duration,
)
from app.services.music_timeline import build_music_timeline
from app.services.music_segment_preparation import prepare_music_segments
from app.services.emotion_music_matcher import match_emotion_to_music
from app.services.music_timeline_assembler import assemble_music_timeline

BASE_DIR = Path(__file__).resolve().parents[2]

MUSIC_LIBRARY_DIR = BASE_DIR / "music"
DEMUCS_CACHE_DIR = BASE_DIR / "data" / "demucs_cache"
DEMUCS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

MUSIC_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
}


MOOD_KEYWORDS = {
    "cinematic": [
        "cinematic", "movie", "dramatic", "epic", "action",
        "powerful", "hero", "mass", "battle", "mythological",
    ],
    "tamil": [
        "tamil", "village", "folk", "traditional",
        "celebration", "festival", "devotional",
    ],
    "instrumental": [
        "calm", "peaceful", "relax", "soft", "nature",
        "travel", "happy", "love", "emotional", "romantic",
        "motivation", "sad",
    ],
}


EMOTION_FAMILIES = {



    "neutral": {
      "neutral", "normal", "balanced",
      "ambient", "background", "subtle"
    },
    "epic": {
        "epic", "dramatic", "heroic", "powerful",
        "battle", "action", "intense", "mass"
    },
    "happy": {
        "happy", "joy", "cheerful", "fun",
        "celebration", "upbeat", "energetic", "comedy"
    },
    "sad": {
        "sad", "emotional", "sorrow", "melancholic",
        "heartbreak", "pain", "crying", "grief",
        "lonely", "pathos"
    },
    "romantic": {
        "romantic", "love", "melody", "tender",
        "affection", "romance"
    },
    "peaceful": {
        "peaceful", "calm", "relaxing", "soft",
        "serene", "nature", "meditation"
    },
    "devotional": {
        "devotional", "spiritual", "prayer",
        "divine", "religious", "bhakti"
    },
    "mystery": {
        "mystery", "suspense", "dark",
        "thriller", "tension", "scary"
    },
    "angry": {
        "angry", "anger", "aggressive",
        "rage", "fight", "revenge"
    },
    "fear": {
        "fear", "scared", "frightened",
        "panic", "horror"
    },

}


FAMILY_CATEGORY = {
    "epic": "cinematic",
    "happy": "instrumental",
    "sad": "instrumental",
    "romantic": "instrumental",
    "peaceful": "instrumental",
    "devotional": "tamil",
    "mystery": "cinematic",
}


def detect_music_category(prompt: str) -> str:
    """Fallback music category detection using prompt keywords."""

    text = prompt.lower()

    for category, keywords in MOOD_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category

    return "instrumental"


def _emotion_families(text: str) -> set[str]:
    """Map Vision AI mood text to known emotion families."""

    words = set(
        text.lower()
        .replace("-", " ")
        .replace("/", " ")
        .replace(",", " ")
        .split()
    )

    matched = set()

    for family, keywords in EMOTION_FAMILIES.items():
        if words.intersection(keywords):
            matched.add(family)

    return matched


def select_catalog_music(
    category: str,
    mood: str = "",
) -> dict | None:
    """
    Select a catalog track only when its metadata supports
    the detected emotion.
    """

    category = (category or "instrumental").strip().lower()
    mood_text = (mood or "").strip().lower()

    emotion_families = _emotion_families(mood_text)

    tracks = search_tracks(limit=500)

    if not tracks:
        return None

    def score(track: dict) -> int:

        title = str(track.get("title", "")).lower()
        track_mood = str(track.get("mood", "")).lower()
        genre = str(track.get("genre", "")).lower()
        track_category = str(track.get("category", "")).lower()

        metadata = (
            f"{title} {track_mood} {genre} {track_category}"
        )

        metadata_words = set(
            metadata.replace("-", " ")
            .replace("/", " ")
            .replace("_", " ")
            .replace(",", " ")
            .split()
        )

        result = 0
        matched_family = False

        if track_category == category:
            result += 2

        for family in emotion_families:

            hits = metadata_words.intersection(
                EMOTION_FAMILIES[family]
            )

            if hits:
                matched_family = True
                result += 20 + min(len(hits), 3) * 3
 
        if track_mood in emotion_families:
           result += 25
           matched_family = True

        if track_mood in {"", "general", "unknown"}:
            result -= 3

        if genre in {"", "general", "unknown"}:
            result -= 2

        return result if matched_family else 0

    valid_tracks = []

    for track in tracks:

        raw_path = track.get("file_path")

        if not raw_path:
            continue

        track_path = Path(raw_path).resolve()

        if (
            track_path.is_file()
            and track_path.suffix.lower() in MUSIC_EXTENSIONS
        ):

            track_score = score(track)

            if track_score > 0:
                valid_tracks.append(
                    (track, track_path, track_score)
                )

    if not valid_tracks:

        print(
            "No emotion-matched SQLite track found. "
            "Check music mood/category metadata; "
            "refusing a random selection."
        )

        return None

    valid_tracks.sort(
        key=lambda item: (
            -item[2],
            str(item[0].get("title", "")).lower(),
            str(item[0].get("music_id", "")),
        )
    )

    selected_track, track_path, selected_score = valid_tracks[0]

    detected_families = sorted(emotion_families)

    print("\n========== SQLITE MUSIC SELECTION ==========")
    print("Requested category:", category)
    print("Detected mood:", mood_text or "not provided")
    print("Emotion families:", detected_families or "not identified")
    print("Selected track:", selected_track.get("title"))
    print("Artist:", selected_track.get("artist"))
    print("Music ID:", selected_track.get("music_id"))
    print("Selection score:", selected_score)
    print("============================================\n")

    return {
        **selected_track,
        "path": track_path,
        "selection_score": selected_score,
        "detected_emotions": detected_families,
    }


def select_library_music(category: str) -> Path:
    """Select a local fallback track from the existing folder library."""

    category = category.lower().strip()

    if category not in {
        "tamil",
        "instrumental",
        "cinematic",
    }:
        category = "instrumental"

    category_dir = MUSIC_LIBRARY_DIR / category

    tracks = []

    if category_dir.is_dir():

        tracks = [
            path
            for path in category_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in MUSIC_EXTENSIONS
        ]

    if not tracks and MUSIC_LIBRARY_DIR.is_dir():

        tracks = [
            path
            for path in MUSIC_LIBRARY_DIR.rglob("*")
            if path.is_file()
            and path.suffix.lower() in MUSIC_EXTENSIONS
        ]

    if not tracks:

        raise FileNotFoundError(
            "No music tracks found in the SQLite catalog "
            "or local folders. Add authorized music files "
            "inside backend/music."
        )

    tracks.sort(key=lambda path: path.name.lower())

    selected_track = tracks[0]

    print("\n========== LOCAL FOLDER MUSIC SELECTION ==========")
    print("Requested category:", category)
    print("Selected track:", selected_track.name)
    print("==================================================\n")

    return selected_track
def build_emotion_matched_music(
    video_analysis: dict,
    selected_music: Path,
    temp_dir: Path,
    music_id: str | None = None,
    fast_mode: bool = True,
) -> dict:
    """
    Run Demucs (with persistent caching), analyze the music, prepare segments,
    match video emotions, and assemble the soundtrack.
    In fast mode when no cache exists, uses the emotion-selected catalog track directly.
    """
    selected_music = Path(selected_music).resolve()
    cached_separated_dir = DEMUCS_CACHE_DIR / selected_music.stem

    has_cache = (
        (cached_separated_dir / "vocals.wav").is_file()
        and (cached_separated_dir / "no_vocals.wav").is_file()
    )

    if fast_mode and not has_cache:
        print("\n[Fast Mode] Skipping CPU-heavy Demucs separation; using SQLite emotion-matched track directly.")
        return {
            "assembled_music_path": selected_music,
            "timeline": None,
            "prepared_segments": {"segment_count": 1},
            "matching": {"video_interval_count": 1},
            "assembly": {"status": "fast_mode_direct_sync", "track": selected_music.name},
        }

    print("\n========== STAGE 7 MUSIC PIPELINE ==========")

    if has_cache:
        print(f"\nUsing cached Demucs separation from {cached_separated_dir} (instant hit)...")
        separated_dir = cached_separated_dir
    else:
        demucs_output = temp_dir / "demucs"
        demucs_output.mkdir(parents=True, exist_ok=True)

        print("\nRunning Demucs separation...")

        command = [
            sys.executable,
            "-m",
            "demucs",
            "--two-stems=vocals",
            "-o",
            str(demucs_output),
            str(selected_music),
        ]

        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=1800,
        )

        separated_dir = (
            demucs_output
            / "htdemucs"
            / selected_music.stem
        )

        if not (separated_dir / "vocals.wav").is_file():
            raise FileNotFoundError(
                f"Demucs vocals output not found: {separated_dir}"
            )

        if not (separated_dir / "no_vocals.wav").is_file():
            raise FileNotFoundError(
                f"Demucs instrumental output not found: {separated_dir}"
            )

        # Cache separated stems for instant subsequent runs
        try:
            cached_separated_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(separated_dir / "vocals.wav", cached_separated_dir / "vocals.wav")
            shutil.copy2(separated_dir / "no_vocals.wav", cached_separated_dir / "no_vocals.wav")
            print(f"Demucs output cached to: {cached_separated_dir}")
        except Exception as cache_err:
            print(f"Demucs cache write warning: {cache_err}")

    print("\nBuilding music timeline...")

    timeline_result = build_music_timeline(
        audio_path=selected_music,
        separated_dir=separated_dir,
        music_id=music_id,
    )

    # Stage 7.7: Prepare music segments.

    print("\nPreparing music segments...")

    prepared_music = prepare_music_segments(
        timeline_result,
        min_segment_duration=0.5,
        include_uncertain=True,
    )

    # Stage 7.8: Match music segments with video emotions.

    print("\nMatching video emotions with music...")

    matching_result = match_emotion_to_music(
        video_analysis=video_analysis,
        prepared_music=prepared_music,
        top_k=3,
        min_segment_duration=1.0,
    )

    matching_json = temp_dir / "emotion_music_matching.json"

    matching_json.write_text(
        json.dumps(
            matching_result,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Stage 7.9: Assemble the matching music timeline.

    print("\nAssembling final music timeline...")

    assembled_music = temp_dir / "emotion_matched_music.wav"

    assembly_result = assemble_music_timeline(
        matching_json=str(matching_json),
        music_path=str(selected_music),
        output_path=str(assembled_music),
    )

    if not assembled_music.is_file():
        raise RuntimeError(
            "Music assembler did not create the output WAV."
        )

    print("\nStage 7 pipeline completed successfully.")

    return {
        "assembled_music_path": assembled_music,
        "timeline": timeline_result,
        "prepared_segments": prepared_music,
        "matching": matching_result,
        "assembly": assembly_result,
    }


def process_video_prompt(
    input_video: str,
    prompt: str,
    output_video: str,
    provider: str = "auto",
    background_music_path: str | None = None,
    music_volume: float = 0.20,
    music_fade_in: float = 2.0,
    music_fade_out: float = 2.0,
    enable_captions: bool | None = None,
    fast_mode: bool = True,
):
    """Analyze, edit and add emotion-matched background music."""

    input_path = Path(input_video).resolve()

    if not input_path.is_file():
        raise FileNotFoundError(
            f"Input video not found: {input_path}"
        )

    provider = provider.lower().strip()

    if provider not in {"auto", "ollama", "openrouter"}:
        raise ValueError("Invalid provider.")

    # Auto-detect whether captions/karaoke lyrics are requested in the prompt
    if enable_captions is None:
        prompt_lower = prompt.lower()
        enable_captions = any(
            kw in prompt_lower
            for kw in ["caption", "subtitles", "subtitle", "karaoke", "lyrics", "lyric"]
        )

    # STEP 1: Generate editing plan.

    if provider == "ollama":
        plan = parse_with_ollama(prompt)

    elif provider == "openrouter":
        plan = parse_with_openrouter(prompt)

    else:
        try:
            plan = parse_with_openrouter(prompt)

        except Exception as error:
            print("OpenRouter failed:", error)
            print("Trying Ollama fallback...")
            plan = parse_with_ollama(prompt)

    # STEP 2: Read video information.

    input_info = get_video_info(input_path)
    video_duration = get_video_duration(input_path)

    vision_analysis = None
    online_music_info = None
    catalog_music_info = None
    music_pipeline_info = None
    caption_info = None

    music_temp = tempfile.TemporaryDirectory(
        prefix="promptcut_music_"
    )

    temp_dir = Path(music_temp.name)

    try:

        # STEP 3: Analyze the video.

        try:
            print("\nExtracting frames across the video...")

            # Fast analysis: extract 3 frames for <= 30s clips, 4 frames for longer
            max_frames = 3 if video_duration <= 30 else 4
            frames = extract_video_frames(
                input_path,
                max_frames=max_frames,
            )

            print("\nAnalyzing video with Vision AI...")

            vision_analysis = analyze_video_frames(frames)

            # Give the matcher the actual video duration.
            vision_analysis["video_duration_seconds"] = (
                video_duration
            )

            detected_emotion = vision_analysis.get(
                "primary_emotion",
                "uncertain",
            )

            detected_mood = detected_emotion

            music_category = vision_analysis.get(
                "music_category",
                detect_music_category(prompt),
            )

            print("Video duration:", video_duration)
            print("Detected emotion:", detected_emotion)
            print(
                "Emotion confidence:",
                vision_analysis.get("confidence", 0.0),
            )

        except Exception as error:
            print("Vision AI failed:", error)
            print("Using prompt-based category fallback.")

            detected_mood = ""
            music_category = detect_music_category(prompt)

        # STEP 4: Select the original music.

        if background_music_path:

            # User-uploaded music has priority.

            selected_music = Path(
                background_music_path
            ).resolve()

            if not selected_music.is_file():
                raise FileNotFoundError(
                    f"Uploaded music not found: {selected_music}"
                )

            music_source = "user_upload"
            music_category = "user_selected"
            selected_music_title = selected_music.stem

        else:

            catalog_music_info = select_catalog_music(
                music_category,
                detected_mood,
            )

            if not catalog_music_info:
                raise RuntimeError(
                    f"No SQLite song is tagged for detected emotion "
                    f"'{detected_mood or 'uncertain'}'. "
                    "Please tag your music with accurate mood metadata."
                )

            selected_music = catalog_music_info["path"]

            music_source = catalog_music_info.get(
                "source",
                "sqlite_catalog",
            )

            selected_music_title = catalog_music_info.get(
                "title",
                selected_music.stem,
            )

        # STEP 5: Run Stages 7.1–7.9.

        music_for_edit = selected_music

        if vision_analysis:
            try:
                music_pipeline_info = build_emotion_matched_music(
                    video_analysis=vision_analysis,
                    selected_music=selected_music,
                    temp_dir=temp_dir,
                    music_id=(
                        catalog_music_info.get("music_id")
                        if catalog_music_info
                        else None
                    ),
                    fast_mode=fast_mode,
                )

                music_for_edit = music_pipeline_info[
                    "assembled_music_path"
                ]

                print(
                    "\nEmotion-matched soundtrack ready:",
                    music_for_edit,
                )

            except Exception as error:
                print(
                    "\nEmotion music pipeline failed:",
                    error,
                )
                print(
                    "Continuing with the original selected music."
                )

                music_for_edit = selected_music

        else:
            print(
                "\nSkipping emotion matching because "
                "video analysis is unavailable."
            )

        # STEP 6: Generate karaoke captions from the selected background song.
        # Transcribe music_for_edit (the exact soundtrack rendered below), not
        # the original video's audio. This keeps lyric timestamps aligned with
        # the song the viewer hears.
        subtitle_path = None
        if enable_captions:
            print("\nGenerating word-by-word karaoke lyrics from background music...")
            caption_info = generate_audio_captions(
                audio_path=music_for_edit,
                output_dir=temp_dir,
                max_duration=video_duration + 5.0,
            )
            subtitle_path = caption_info.get("subtitle_path")
            print(
                "Song caption status:",
                caption_info.get("status"),
                "| lyric events:",
                caption_info.get("caption_count", 0),
            )

        # STEP 7: Edit video, render captions, and add soundtrack.

        result = edit_video(
            input_path=input_path,
            plan=plan,
            output_path=output_video,
            background_music_path=music_for_edit,
            subtitle_path=subtitle_path,
            music_volume=music_volume,
            music_fade_in=music_fade_in,
            music_fade_out=music_fade_out,
        )

        # STEP 7: Prepare music information.

        background_music = {
            "filename": selected_music.name,
            "track_name": selected_music_title,
            "source": music_source,
            "category": music_category,
            "volume": music_volume,
            "fade_in": music_fade_in,
            "fade_out": music_fade_out,
            "added": result.get(
                "background_music_added",
                False,
            ),
            "emotion_matching_applied": (
                music_pipeline_info is not None
            ),
        }

        if catalog_music_info:
            background_music.update({
                "music_id": catalog_music_info.get("music_id"),
                "artist": catalog_music_info.get("artist"),
                "language": catalog_music_info.get("language"),
                "mood": catalog_music_info.get("mood"),
                "genre": catalog_music_info.get("genre"),
                "license": catalog_music_info.get("license"),
                "catalog_status": catalog_music_info.get("status"),
                "selection_score": catalog_music_info.get(
                    "selection_score"
                ),
                "detected_emotions": catalog_music_info.get(
                    "detected_emotions",
                    [],
                ),
            })

        # STEP 8: Return result.

        pipeline_summary = None

        if music_pipeline_info:
            pipeline_summary = {
                "status": "completed",
                "stage": "7.9",
                "music_segment_count": music_pipeline_info[
                    "prepared_segments"
                ].get("segment_count"),
                "video_interval_count": music_pipeline_info[
                    "matching"
                ].get("video_interval_count"),
                "assembly": music_pipeline_info["assembly"],
            }

        return {
            "message": "Video edited successfully.",
            "plan": plan,
            "input_info": input_info,
            "output_info": result["output_info"],
            "output_path": result["output_path"],
            "operations_applied": result["operations_applied"],
            "video_analysis": vision_analysis,
            "detected_emotion": (
                vision_analysis.get("primary_emotion")
                if vision_analysis else None
            ),
            "emotion_confidence": (
                vision_analysis.get("confidence")
                if vision_analysis else None
            ),
            "background_music": background_music,
            "music_pipeline": pipeline_summary,
            "captions": {
                "enabled": bool(enable_captions),
                "status": (caption_info or {}).get("status", "disabled"),
                "caption_count": (caption_info or {}).get("caption_count", 0),
                "language": (caption_info or {}).get("language"),
                "subtitle_rendered": result.get("captions_added", False),
                "caption_source": "background_music",
                "original_video_audio_muted": result.get("original_audio_muted", False),
                "note": (caption_info or {}).get("note"),
            },
        }

    finally:
        music_temp.cleanup()


def process_multi_video_prompt(
    video_paths: list[str | Path],
    prompt: str,
    output_video: str,
    provider: str = "auto",
    background_music_path: str | None = None,
    music_volume: float = 0.20,
    music_fade_in: float = 2.0,
    music_fade_out: float = 2.0,
    enable_captions: bool | None = None,
    fast_mode: bool = True,
) -> dict:
    """
    Merge multiple video clips (2 or more) into a single cohesive video,
    then apply AI natural language editing, vision analysis, soundtrack matching,
    audio mixing/ducking, and optional karaoke captions.
    """
    if not video_paths or len(video_paths) < 2:
        raise ValueError("At least 2 video files are required to merge and edit.")

    temp_dir = tempfile.TemporaryDirectory(prefix="promptcut_merge_")
    try:
        merged_source_path = Path(temp_dir.name) / "merged_input.mp4"
        print(f"\n[multi-video] Merging {len(video_paths)} clips into unified timeline...")
        merge_info = merge_video_clips(
            input_paths=video_paths,
            output_path=merged_source_path,
        )
        print(f"[multi-video] Merge complete: {merge_info['total_duration']:.2f}s total duration.")

        result = process_video_prompt(
            input_video=str(merged_source_path),
            prompt=prompt,
            output_video=output_video,
            provider=provider,
            background_music_path=background_music_path,
            music_volume=music_volume,
            music_fade_in=music_fade_in,
            music_fade_out=music_fade_out,
            enable_captions=enable_captions,
            fast_mode=fast_mode,
        )

        result["merged_clips_count"] = merge_info["merged_clips_count"]
        result["input_clips"] = merge_info["clips"]
        result["is_merged"] = True
        return result
    finally:
        temp_dir.cleanup()
