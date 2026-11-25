from pathlib import Path
from copy import deepcopy

from app.services.music_analysis import analyze_audio
from app.services.lyrics_transcriber import transcribe_audio
from app.services.vocal_detector import detect_vocal_sections
from app.services import music_catalog


def clamp_time(value, duration):
    """Keep a timestamp within the original audio duration."""
    return round(max(0.0, min(float(value), float(duration))), 2)


def correct_transcription_timestamps(transcription, duration):
    """Correct lyric and word timestamps to original audio duration."""
    result = deepcopy(transcription)
    result["duration_seconds"] = duration

    corrected_lyrics = []
    for lyric in result.get("lyrics", []):
        start = clamp_time(lyric["start_time"], duration)
        end = clamp_time(lyric["end_time"], duration)
        if end <= start:
            continue

        lyric["start_time"] = start
        lyric["end_time"] = end

        corrected_words = []
        for word in lyric.get("words", []):
            word_start = clamp_time(word["start_time"], duration)
            word_end = clamp_time(word["end_time"], duration)
            if word_end <= word_start:
                continue
            word["start_time"] = word_start
            word["end_time"] = word_end
            corrected_words.append(word)

        lyric["words"] = corrected_words
        corrected_lyrics.append(lyric)

    result["lyrics"] = corrected_lyrics
    return result


def correct_vocal_timeline(timeline, duration):
    """Correct vocal timeline section timestamps."""
    result = deepcopy(timeline)
    result["duration_seconds"] = duration

    corrected_sections = []
    for section in result.get("sections", []):
        start = clamp_time(section["start_time"], duration)
        end = clamp_time(section["end_time"], duration)
        if end <= start:
            continue
        section["start_time"] = start
        section["end_time"] = end
        corrected_sections.append(section)

    result["sections"] = corrected_sections
    return result


def correct_energy_windows(windows, duration):
    """Prevent energy windows from exceeding original duration."""
    corrected = []
    for window in windows:
        start = clamp_time(window["start_time"], duration)
        end = clamp_time(window["end_time"], duration)
        if end <= start:
            continue
        item = dict(window)
        item["start_time"] = start
        item["end_time"] = end
        corrected.append(item)
    return corrected


def classify_lyric_activity(word, vocal_timeline):
    """
    Compare a Whisper word interval with Demucs activity sections.

    Original Whisper timestamps are read only; they are never modified here.
    """
    word_start = float(word["start_time"])
    word_end = float(word["end_time"])
    word_duration = word_end - word_start

    if word_duration <= 0:
        return {
            "lyric_activity_status": "uncertain",
            "activity_overlap": {
                "likely_vocal_seconds": 0.0,
                "likely_instrumental_seconds": 0.0,
                "uncertain_seconds": 0.0,
                "unclassified_seconds": 0.0,
                "likely_vocal_fraction": 0.0,
                "likely_instrumental_fraction": 0.0,
                "uncertain_fraction": 0.0,
                "coverage_fraction": 0.0,
            },
        }

    overlap_seconds = {
        "likely_vocal": 0.0,
        "likely_instrumental": 0.0,
        "uncertain": 0.0,
    }

    for section in vocal_timeline.get("sections", []):
        section_start = float(section["start_time"])
        section_end = float(section["end_time"])
        overlap = max(
            0.0,
            min(word_end, section_end) - max(word_start, section_start),
        )
        if overlap <= 0:
            continue

        section_type = str(section.get("type", "uncertain")).lower()
        if section_type not in overlap_seconds:
            section_type = "uncertain"
        overlap_seconds[section_type] += overlap

    # Timeline sections should normally not overlap. Cap the measured
    # coverage to the word duration to protect fractions from malformed data.
    classified_total = sum(overlap_seconds.values())
    if classified_total > word_duration:
        scale = word_duration / classified_total
        overlap_seconds = {
            key: value * scale for key, value in overlap_seconds.items()
        }
        classified_total = word_duration

    unclassified_seconds = max(0.0, word_duration - classified_total)

    fractions = {
        key: value / word_duration
        for key, value in overlap_seconds.items()
    }

    vocal_fraction = fractions["likely_vocal"]
    instrumental_fraction = fractions["likely_instrumental"]
    uncertain_fraction = fractions["uncertain"]

    # A strong majority is required for a confident label. If both vocal
    # and instrumental evidence are meaningful, retain the disagreement.
    if vocal_fraction >= 0.60 and vocal_fraction > instrumental_fraction:
        status = "likely_vocal"
    elif (
        instrumental_fraction >= 0.60
        and instrumental_fraction > vocal_fraction
    ):
        status = "likely_instrumental"
    elif vocal_fraction >= 0.15 and instrumental_fraction >= 0.15:
        status = "boundary_conflict"
    else:
        status = "uncertain"

    return {
        "lyric_activity_status": status,
        "activity_overlap": {
            "likely_vocal_seconds": round(
                overlap_seconds["likely_vocal"], 3
            ),
            "likely_instrumental_seconds": round(
                overlap_seconds["likely_instrumental"], 3
            ),
            "uncertain_seconds": round(overlap_seconds["uncertain"], 3),
            "unclassified_seconds": round(unclassified_seconds, 3),
            "likely_vocal_fraction": round(vocal_fraction, 3),
            "likely_instrumental_fraction": round(instrumental_fraction, 3),
            "uncertain_fraction": round(uncertain_fraction, 3),
            "coverage_fraction": round(
                classified_total / word_duration, 3
            ),
        },
    }


def build_combined_timeline(vocal_timeline, transcription):
    """
    Combine Demucs activity sections with Whisper word timestamps.

    Each word receives an activity label based on exact interval overlap.
    Whisper word text and timestamps remain unchanged.
    """
    words = []

    for lyric in transcription.get("lyrics", []):
        lyric_words = lyric.get("words") or [{
            "word": lyric.get("text", ""),
            "start_time": lyric["start_time"],
            "end_time": lyric["end_time"],
        }]

        for word in lyric_words:
            text = str(word.get("word", "")).strip()
            if not text:
                continue

            original_word = {
                "word": text,
                "start_time": word["start_time"],
                "end_time": word["end_time"],
            }
            activity = classify_lyric_activity(
                original_word, vocal_timeline
            )
            words.append({**original_word, **activity})

    combined_sections = []
    for section in vocal_timeline.get("sections", []):
        start = section["start_time"]
        end = section["end_time"]

        overlapping_words = [
            word for word in words
            if word["start_time"] < end and word["end_time"] > start
        ]

        combined_sections.append({
            **section,
            "lyrics": overlapping_words,
        })

    status_counts = {}
    for word in words:
        status = word["lyric_activity_status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "duration_seconds": vocal_timeline.get("duration_seconds", 0),
        "sections": combined_sections,
        "words": words,
        "word_count": len(words),
        "activity_status_counts": status_counts,
        "note": (
            "Vocal activity comes from Demucs stem-energy comparison. "
            "Words and timestamps come from Faster-Whisper. Each word's "
            "activity status is assigned by measuring its time overlap "
            "with the activity sections. Boundary conflicts and uncertain "
            "results are preserved; original Whisper timestamps are not "
            "changed by this comparison."
        ),
    }


def save_music_timeline(music_id, combined_timeline, transcription, bpm=None):
    """
    Replace the saved timeline for a catalog track.
    Stores each recognized word as a timestamped music_lyrics row and
    each vocal/instrumental activity section as a music_segments row.
    """
    if not music_id:
        raise ValueError("music_id is required to save a timeline.")

    # Remove the previous analysis so rerunning this job does not duplicate rows.
    for row in music_catalog.list_lyrics(music_id):
        music_catalog.delete_lyric(row["lyric_id"])

    for row in music_catalog.list_music_segments(music_id):
        music_catalog.delete_music_segment(row["segment_id"])

    language = transcription.get("language") or "unknown"
    saved_lyrics = 0
    saved_segments = 0

    # Save each recognized word once, directly from the transcription.
    for lyric in transcription.get("lyrics", []):
        lyric_words = lyric.get("words") or [{
            "word": lyric.get("text", ""),
            "start_time": lyric["start_time"],
            "end_time": lyric["end_time"],
        }]
        for word in lyric_words:
            word_text = str(word.get("word", "")).strip()
            if not word_text or word["end_time"] <= word["start_time"]:
                continue
            music_catalog.add_lyric(
                music_id,
                word["start_time"],
                word["end_time"],
                word_text,
                language=language,
                source="faster_whisper_word_timestamp",
            )
            saved_lyrics += 1

    for section in combined_timeline.get("sections", []):
        start = section["start_time"]
        end = section["end_time"]
        if end <= start:
            continue

        score = section.get("vocal_score_max")
        notes = section.get("reason", "")
        if score is not None:
            notes = f"{notes}; vocal_score_max={score}"

        music_catalog.add_music_segment(
            music_id,
            start,
            end,
            segment_type=section.get("type", "uncertain"),
            mood="general",
            energy=None,
            bpm=bpm,
            notes=notes,
        )
        saved_segments += 1

    return {
        "music_id": music_id,
        "saved_lyrics": saved_lyrics,
        "saved_segments": saved_segments,
    }


def build_music_timeline(audio_path, separated_dir, music_id=None):
    audio_path = Path(audio_path)
    separated_dir = Path(separated_dir)

    vocals_path = separated_dir / "vocals.wav"
    instrumental_path = separated_dir / "no_vocals.wav"

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio not found: {audio_path}")
    if not vocals_path.exists():
        raise FileNotFoundError(f"Vocals file not found: {vocals_path}")
    if not instrumental_path.exists():
        raise FileNotFoundError(f"Instrumental file not found: {instrumental_path}")

    print("Step 1: Analyzing original music...")
    audio_features = analyze_audio(audio_path)
    original_duration = audio_features["duration_seconds"]
    print(f"Original duration: {original_duration}s")

    print("Step 2: Transcribing separated vocals...")
    transcription = transcribe_audio(vocals_path, language="ta")
    transcription_duration_before_correction = transcription.get("duration_seconds")
    print(f"Separated vocal duration: {transcription_duration_before_correction}s")

    print("Step 3: Correcting timestamps...")
    transcription = correct_transcription_timestamps(
        transcription, original_duration
    )

    print("Step 4: Building vocal activity timeline...")
    vocal_timeline = detect_vocal_sections(
        transcription,
        vocals_path=vocals_path,
        instrumental_path=instrumental_path,
        window_seconds=0.5,
    )
    vocal_timeline = correct_vocal_timeline(vocal_timeline, original_duration)

    energy_windows = correct_energy_windows(
        audio_features["windows"], original_duration
    )

    print("Step 5: Combining vocal activity and lyric timestamps...")
    combined_timeline = build_combined_timeline(vocal_timeline, transcription)

    database_result = None
    if music_id:
        print("Step 6: Saving timeline to SQLite catalog...")
        database_result = save_music_timeline(
            music_id,
            combined_timeline,
            transcription,
            bpm=audio_features.get("estimated_bpm"),
        )

    print("Music timeline completed!")

    return {
        "file_name": audio_path.name,
        "music_id": music_id,
        "duration_seconds": original_duration,
        "audio_features": {
            "estimated_bpm": audio_features.get("estimated_bpm"),
            "average_rms": audio_features.get("average_rms"),
            "average_spectral_centroid_hz": audio_features.get(
                "average_spectral_centroid_hz"
            ),
            "energy_windows": energy_windows,
        },
        "transcription": transcription,
        "vocal_timeline": vocal_timeline,
        "combined_timeline": combined_timeline,
        "database": database_result or {
            "saved": False,
            "reason": "No music_id supplied; timeline was not saved.",
        },
        "separated_audio": {
            "vocals": str(vocals_path),
            "instrumental": str(instrumental_path),
        },
        "timestamp_validation": {
            "original_duration": original_duration,
            "transcription_duration_before_correction":
                transcription_duration_before_correction,
            "transcription_duration_after_correction":
                transcription.get("duration_seconds"),
            "all_timestamps_clamped": True,
        },
        "note": (
            "Vocal activity is estimated from Demucs stem-energy comparison. "
            "Lyrics and word timestamps are estimated by Faster-Whisper. "
            "Uncertain sections are preserved rather than guessed."
        ),
    }
