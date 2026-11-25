
from faster_whisper import WhisperModel
from pathlib import Path

_model = None

BACKEND_DIR = Path(__file__).resolve().parents[2]

MODEL_DIR = (
    BACKEND_DIR
    / "models"
    / "faster-whisper-small"
)


def get_model():
    global _model

    if _model is None:
        if not MODEL_DIR.exists():
            raise FileNotFoundError(
                f"Whisper model folder not found: {MODEL_DIR}"
            )

        required_files = [
            "model.bin",
            "config.json",
            "tokenizer.json",
            "vocabulary.txt"
        ]

        for filename in required_files:
            if not (MODEL_DIR / filename).exists():
                raise FileNotFoundError(
                    f"Missing model file: {filename}"
                )

        print("Loading local Faster-Whisper model...")

        _model = WhisperModel(
            str(MODEL_DIR),
            device="cpu",
            compute_type="int8"
        )

        print("Local Whisper model loaded successfully!")

    return _model


def transcribe_audio(audio_path, language=None):
    audio_path = Path(audio_path)

    if not audio_path.exists():
        raise FileNotFoundError(
            f"Audio file not found: {audio_path}"
        )

    model = get_model()

    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
        vad_filter=False,
        word_timestamps=True,
        condition_on_previous_text=False
    )

    lyrics = []

    for segment in segments:
        text = segment.text.strip()

        if not text:
            continue

        words = []

        if segment.words:
            for word in segment.words:
                words.append({
                    "word": word.word.strip(),
                    "start_time": round(word.start, 2),
                    "end_time": round(word.end, 2)
                })

        lyrics.append({
            "start_time": round(segment.start, 2),
            "end_time": round(segment.end, 2),
            "text": text,
            "words": words
        })

    return {
        "file_name": audio_path.name,
        "language": info.language,
        "language_probability": round(
            info.language_probability, 3
        ),
        "duration_seconds": round(info.duration, 2),
        "lyrics": lyrics,
        "note": (
            "Singing transcription may contain errors. "
            "Verify lyrics and timestamps."
        )
    }
