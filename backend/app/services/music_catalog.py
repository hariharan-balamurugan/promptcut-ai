"""SQLite-backed music catalog shared by FastAPI and the Telegram bot."""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"
DB_PATH = DATA_DIR / "music_catalog.db"
SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_catalog() -> None:
    with _connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS music_tracks (
                music_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL DEFAULT 'Unknown artist',
                language TEXT NOT NULL DEFAULT 'unknown',
                category TEXT NOT NULL DEFAULT 'instrumental',
                mood TEXT NOT NULL DEFAULT 'general',
                genre TEXT NOT NULL DEFAULT 'unknown',
                source TEXT NOT NULL,
                license TEXT NOT NULL DEFAULT 'user_supplied_unverified',
                file_path TEXT NOT NULL UNIQUE,
                file_extension TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'available',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS music_requests (
                request_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'unknown',
                notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'requested',
                failure_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_music_category ON music_tracks(category)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_music_language ON music_tracks(language)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_music_status ON music_tracks(status)")

        db.execute("""
            CREATE TABLE IF NOT EXISTS music_lyrics (
                lyric_id TEXT PRIMARY KEY,
                music_id TEXT NOT NULL,
                start_time REAL NOT NULL CHECK(start_time >= 0),
                end_time REAL NOT NULL CHECK(end_time > start_time),
                lyric_text TEXT NOT NULL,
                language TEXT NOT NULL DEFAULT 'unknown',
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (music_id) REFERENCES music_tracks(music_id)
                    ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS music_segments (
                segment_id TEXT PRIMARY KEY,
                music_id TEXT NOT NULL,
                start_time REAL NOT NULL CHECK(start_time >= 0),
                end_time REAL NOT NULL CHECK(end_time > start_time),
                segment_type TEXT NOT NULL DEFAULT 'unknown',
                mood TEXT NOT NULL DEFAULT 'general',
                energy REAL,
                bpm REAL,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (music_id) REFERENCES music_tracks(music_id)
                    ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_lyrics_track_time
            ON music_lyrics(music_id, start_time)
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_segments_track_time
            ON music_segments(music_id, start_time)
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_segments_mood
            ON music_segments(mood)
        """)


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def register_track(
    file_path: str | Path,
    *,
    title: str | None = None,
    artist: str = "Unknown artist",
    language: str = "unknown",
    category: str = "instrumental",
    mood: str = "general",
    genre: str = "unknown",
    source: str = "local_import",
    license_name: str = "user_supplied_unverified",
    music_id: str | None = None,
) -> dict[str, Any]:
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Music file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Unsupported music file extension.")

    music_id = music_id or uuid.uuid4().hex
    inferred_title = title or path.stem
    category = (category or "instrumental").strip().lower()
    language = (language or "unknown").strip().lower()

    init_catalog()
    with _connect() as db:
        db.execute("""
            INSERT INTO music_tracks
            (music_id, title, artist, language, category, mood, genre, source,
             license, file_path, file_extension, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'available')
            ON CONFLICT(music_id) DO UPDATE SET
              title=excluded.title, artist=excluded.artist,
              language=excluded.language, category=excluded.category,
              mood=excluded.mood, genre=excluded.genre, source=excluded.source,
              license=excluded.license, file_path=excluded.file_path,
              file_extension=excluded.file_extension, status='available',
              updated_at=CURRENT_TIMESTAMP
        """, (music_id, inferred_title, artist, language, category, mood, genre,
              source, license_name, str(path), path.suffix.lower()))
        row = db.execute("SELECT * FROM music_tracks WHERE music_id=?", (music_id,)).fetchone()
    return _row_to_dict(row) or {}


def get_track(music_id: str) -> dict[str, Any] | None:
    init_catalog()
    with _connect() as db:
        return _row_to_dict(db.execute(
            "SELECT * FROM music_tracks WHERE music_id=?", (music_id,)
        ).fetchone())


def get_track_path(music_id: str) -> Path | None:
    track = get_track(music_id)
    if not track:
        return None
    path = Path(track["file_path"]).resolve()
    return path if path.is_file() else None


def search_tracks(
    query: str = "", language: str | None = None,
    category: str | None = None, mood: str | None = None,
    source: str | None = None, limit: int = 100,
) -> list[dict[str, Any]]:
    init_catalog()
    clauses = ["status='available'"]
    values: list[Any] = []
    if query.strip():
        like = f"%{query.strip()}%"
        clauses.append("(title LIKE ? OR artist LIKE ? OR genre LIKE ? OR mood LIKE ?)")
        values.extend([like] * 4)
    for field, value in (("language", language), ("category", category), ("mood", mood), ("source", source)):
        if value:
            clauses.append(f"{field} = ?")
            values.append(value.strip().lower())
    values.append(max(1, min(int(limit), 500)))
    sql = "SELECT * FROM music_tracks WHERE " + " AND ".join(clauses) + " ORDER BY title COLLATE NOCASE LIMIT ?"
    with _connect() as db:
        rows = db.execute(sql, values).fetchall()
    return [_row_to_dict(row) or {} for row in rows]


def delete_track(music_id: str) -> bool:
    init_catalog()
    with _connect() as db:
        cursor = db.execute("DELETE FROM music_tracks WHERE music_id=?", (music_id,))
    return cursor.rowcount > 0


def create_music_request(title: str, artist: str = "", language: str = "unknown", notes: str = "") -> dict[str, Any]:
    init_catalog()
    request_id = uuid.uuid4().hex
    with _connect() as db:
        db.execute("""INSERT INTO music_requests
            (request_id, title, artist, language, notes, status)
            VALUES (?, ?, ?, ?, ?, 'requested')""",
            (request_id, title.strip(), artist.strip(), language.strip().lower(), notes.strip()))
        row = db.execute("SELECT * FROM music_requests WHERE request_id=?", (request_id,)).fetchone()
    return _row_to_dict(row) or {}


def list_music_requests(status: str | None = None) -> list[dict[str, Any]]:
    init_catalog()
    with _connect() as db:
        if status:
            rows = db.execute("SELECT * FROM music_requests WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM music_requests ORDER BY created_at DESC").fetchall()
    return [_row_to_dict(row) or {} for row in rows]


def update_music_request(request_id: str, status: str, failure_reason: str = "") -> dict[str, Any] | None:
    allowed = {"requested", "searching", "importing", "processing", "available", "failed"}
    if status not in allowed:
        raise ValueError(f"Status must be one of: {', '.join(sorted(allowed))}")
    init_catalog()
    with _connect() as db:
        db.execute("""UPDATE music_requests SET status=?, failure_reason=?,
            updated_at=CURRENT_TIMESTAMP WHERE request_id=?""",
            (status, failure_reason, request_id))
        row = db.execute("SELECT * FROM music_requests WHERE request_id=?", (request_id,)).fetchone()
    return _row_to_dict(row)


def scan_existing_music(folders: list[Path] | None = None) -> int:
    """Register existing local audio without claiming its license is verified."""
    init_catalog()
    folders = folders or [PROJECT_DIR / "music", BACKEND_DIR / "music", BACKEND_DIR / "music_uploads"]
    added = 0
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                relative_parts = [part.lower() for part in path.parts]
                category = next((name for name in ("tamil", "instrumental", "cinematic") if name in relative_parts), "instrumental")
                language = "tamil" if category == "tamil" else "unknown"
                existing = None
                with _connect() as db:
                    existing = db.execute("SELECT music_id FROM music_tracks WHERE file_path=?", (str(path.resolve()),)).fetchone()
                if not existing:
                    register_track(path, category=category, language=language, source="existing_local_library")
                    added += 1
            except (OSError, ValueError):
                continue
    return added


def add_lyric(
    music_id: str, start_time: float, end_time: float, lyric_text: str,
    *, language: str = "unknown", source: str = "manual",
) -> dict[str, Any]:
    """Add one timestamped lyric line to an existing music track."""
    start_time, end_time = float(start_time), float(end_time)
    lyric_text = lyric_text.strip()
    if start_time < 0 or end_time <= start_time:
        raise ValueError("Require 0 <= start_time < end_time.")
    if not lyric_text:
        raise ValueError("lyric_text cannot be empty.")
    init_catalog()
    lyric_id = uuid.uuid4().hex
    with _connect() as db:
        db.execute("""
            INSERT INTO music_lyrics
                (lyric_id, music_id, start_time, end_time, lyric_text, language, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (lyric_id, music_id, start_time, end_time, lyric_text,
              (language or "unknown").strip().lower(), source.strip()))
        row = db.execute(
            "SELECT * FROM music_lyrics WHERE lyric_id=?", (lyric_id,)
        ).fetchone()
    return _row_to_dict(row) or {}


def list_lyrics(music_id: str) -> list[dict[str, Any]]:
    """List timestamped lyrics for a track."""
    init_catalog()
    with _connect() as db:
        rows = db.execute("""
            SELECT * FROM music_lyrics WHERE music_id=?
            ORDER BY start_time, end_time
        """, (music_id,)).fetchall()
    return [_row_to_dict(row) or {} for row in rows]


def delete_lyric(lyric_id: str) -> bool:
    init_catalog()
    with _connect() as db:
        cursor = db.execute("DELETE FROM music_lyrics WHERE lyric_id=?", (lyric_id,))
    return cursor.rowcount > 0


def add_music_segment(
    music_id: str, start_time: float, end_time: float, *,
    segment_type: str = "unknown", mood: str = "general",
    energy: float | None = None, bpm: float | None = None, notes: str = "",
) -> dict[str, Any]:
    """Add a vocal/instrumental or otherwise classified track section."""
    start_time, end_time = float(start_time), float(end_time)
    if start_time < 0 or end_time <= start_time:
        raise ValueError("Require 0 <= start_time < end_time.")
    if energy is not None and not 0 <= float(energy) <= 1:
        raise ValueError("energy must be between 0 and 1, or None.")
    if bpm is not None and float(bpm) <= 0:
        raise ValueError("bpm must be positive, or None.")
    init_catalog()
    segment_id = uuid.uuid4().hex
    with _connect() as db:
        db.execute("""
            INSERT INTO music_segments
                (segment_id, music_id, start_time, end_time, segment_type,
                 mood, energy, bpm, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (segment_id, music_id, start_time, end_time,
              (segment_type or "unknown").strip().lower(),
              (mood or "general").strip().lower(),
              float(energy) if energy is not None else None,
              float(bpm) if bpm is not None else None, notes.strip()))
        row = db.execute(
            "SELECT * FROM music_segments WHERE segment_id=?", (segment_id,)
        ).fetchone()
    return _row_to_dict(row) or {}


def list_music_segments(music_id: str) -> list[dict[str, Any]]:
    """List classified sections for a track."""
    init_catalog()
    with _connect() as db:
        rows = db.execute("""
            SELECT * FROM music_segments WHERE music_id=?
            ORDER BY start_time, end_time
        """, (music_id,)).fetchall()
    return [_row_to_dict(row) or {} for row in rows]


def delete_music_segment(segment_id: str) -> bool:
    init_catalog()
    with _connect() as db:
        cursor = db.execute(
            "DELETE FROM music_segments WHERE segment_id=?", (segment_id,)
        )
    return cursor.rowcount > 0



init_catalog()
