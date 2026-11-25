"""
batch_service.py — SQLite-backed batch job manager for PromptCut AI.

Tables:
  batches   — one row per batch request
  batch_jobs — one row per video within a batch
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.services.video_service import process_video_prompt, process_multi_video_prompt

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[3]   # backend/
DATA_DIR = BASE_DIR / "data"
DB_PATH  = DATA_DIR / "batch_jobs.db"


# ---------------------------------------------------------------------------
# DB initialisation
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_batch_db() -> None:
    """Create the batch tables if they do not already exist."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS batches (
                batch_id      TEXT PRIMARY KEY,
                prompt        TEXT NOT NULL,
                total_jobs    INTEGER NOT NULL DEFAULT 0,
                completed_jobs INTEGER NOT NULL DEFAULT 0,
                failed_jobs   INTEGER NOT NULL DEFAULT 0,
                status        TEXT NOT NULL DEFAULT 'pending',
                created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at  TEXT,
                mode          TEXT NOT NULL DEFAULT 'individual',
                output_filename TEXT
            );

            CREATE TABLE IF NOT EXISTS batch_jobs (
                job_id            TEXT PRIMARY KEY,
                batch_id          TEXT NOT NULL,
                video_id          TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                prompt            TEXT NOT NULL,
                provider          TEXT NOT NULL DEFAULT 'auto',
                status            TEXT NOT NULL DEFAULT 'pending',
                output_filename   TEXT,
                error_message     TEXT,
                created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at        TEXT,
                completed_at      TEXT,
                FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
            );
        """)
        for col, col_type in [("mode", "TEXT DEFAULT 'individual'"), ("output_filename", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE batches ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


def create_batch(
    prompt: str,
    video_ids: list[str],
    provider: str = "auto",
    original_filenames: dict[str, str] | None = None,
    mode: str = "individual",
) -> dict:
    """
    Create a batch record and jobs.
    In 'individual' mode: one job per video_id.
    In 'merge' mode: one merged job that concatenates and edits all video_ids into a single video.

    Parameters
    ----------
    prompt             : shared editing prompt
    video_ids          : list of video UUIDs already on disk
    provider           : LLM provider string
    original_filenames : optional map {video_id -> original filename}
    mode               : 'individual' (edit separately) or 'merge' (edit as 1 single video)

    Returns
    -------
    {"batch_id": str, "mode": str, "jobs": [{"job_id": str, "video_id": str, "status": str}, ...]}
    """
    if original_filenames is None:
        original_filenames = {}

    batch_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    mode = "merge" if mode == "merge" else "individual"

    jobs = []
    with _get_conn() as conn:
        total_jobs = 1 if mode == "merge" else len(video_ids)
        conn.execute(
            """INSERT INTO batches
               (batch_id, prompt, total_jobs, completed_jobs, failed_jobs,
                status, created_at, mode)
               VALUES (?, ?, ?, 0, 0, 'pending', ?, ?)""",
            (batch_id, prompt, total_jobs, now, mode),
        )

        if mode == "merge":
            job_id = uuid.uuid4().hex
            names_summary = ", ".join([original_filenames.get(v, v) for v in video_ids[:3]])
            if len(video_ids) > 3:
                names_summary += f", +{len(video_ids)-3} more"
            combined_label = f"Merged {len(video_ids)} clips ({names_summary})"
            vids_joined = ",".join(video_ids)
            conn.execute(
                """INSERT INTO batch_jobs
                   (job_id, batch_id, video_id, original_filename,
                    prompt, provider, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (job_id, batch_id, vids_joined, combined_label, prompt, provider, now),
            )
            jobs.append({"job_id": job_id, "video_id": vids_joined, "status": "pending"})
        else:
            for vid in video_ids:
                job_id  = uuid.uuid4().hex
                fname   = original_filenames.get(vid, vid)
                conn.execute(
                    """INSERT INTO batch_jobs
                       (job_id, batch_id, video_id, original_filename,
                        prompt, provider, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                    (job_id, batch_id, vid, fname, prompt, provider, now),
                )
                jobs.append({"job_id": job_id, "video_id": vid, "status": "pending"})

    return {"batch_id": batch_id, "mode": mode, "jobs": jobs}


def get_batch(batch_id: str) -> dict:
    """Return the batch header + all its jobs."""
    with _get_conn() as conn:
        batch = _row_to_dict(
            conn.execute(
                "SELECT * FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
        )
        if not batch:
            return {}

        rows = conn.execute(
            "SELECT * FROM batch_jobs WHERE batch_id = ? ORDER BY created_at",
            (batch_id,),
        ).fetchall()
        batch["jobs"] = [_row_to_dict(r) for r in rows]
    return batch


def get_job(job_id: str) -> dict:
    """Return a single job record."""
    with _get_conn() as conn:
        return _row_to_dict(
            conn.execute(
                "SELECT * FROM batch_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        )


def update_job_status(
    job_id: str,
    status: str,
    output_filename: str | None = None,
    error_message: str | None = None,
) -> None:
    """Update a job's status and propagate aggregate counts to its batch."""
    now = datetime.now(timezone.utc).isoformat()

    with _get_conn() as conn:
        job = _row_to_dict(
            conn.execute(
                "SELECT batch_id, status FROM batch_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        )
        if not job:
            return

        # Build the SET clause dynamically.
        sets   = ["status = ?"]
        values: list = [status]

        if status == "processing":
            sets.append("started_at = ?")
            values.append(now)

        if status in ("completed", "failed"):
            sets.append("completed_at = ?")
            values.append(now)

        if output_filename is not None:
            sets.append("output_filename = ?")
            values.append(output_filename)

        if error_message is not None:
            sets.append("error_message = ?")
            values.append(error_message)

        values.append(job_id)
        conn.execute(
            f"UPDATE batch_jobs SET {', '.join(sets)} WHERE job_id = ?",
            values,
        )

        batch_id = job["batch_id"]

        # Recount completed / failed / total.
        agg = conn.execute(
            """SELECT
                 COUNT(*) AS total,
                 SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                 SUM(CASE WHEN status = 'failed'    THEN 1 ELSE 0 END) AS failed
               FROM batch_jobs WHERE batch_id = ?""",
            (batch_id,),
        ).fetchone()

        total     = agg["total"]
        completed = agg["completed"] or 0
        failed    = agg["failed"]    or 0
        done      = completed + failed

        if done >= total:
            batch_status = "completed" if failed == 0 else "failed"
            batch_completed_at = now
        elif status == "processing":
            batch_status       = "processing"
            batch_completed_at = None
        else:
            batch_status       = "pending"
            batch_completed_at = None

        # Preserve existing batch status when it's already further along.
        existing = _row_to_dict(
            conn.execute(
                "SELECT status FROM batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
        )
        rank = {"pending": 0, "processing": 1, "completed": 2, "failed": 2}
        if rank.get(batch_status, 0) >= rank.get(existing.get("status"), 0):
            if batch_completed_at:
                conn.execute(
                    """UPDATE batches
                       SET status = ?, completed_jobs = ?, failed_jobs = ?,
                           completed_at = ?
                       WHERE batch_id = ?""",
                    (batch_status, completed, failed, batch_completed_at, batch_id),
                )
            else:
                conn.execute(
                    """UPDATE batches
                       SET status = ?, completed_jobs = ?, failed_jobs = ?
                       WHERE batch_id = ?""",
                    (batch_status, completed, failed, batch_id),
                )


def list_batches(limit: int = 50) -> list:
    """Return the most recent *limit* batches (no job rows)."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM batches ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Sequential batch processor (runs in a FastAPI BackgroundTask thread)
# ---------------------------------------------------------------------------

def process_batch_sequentially(
    batch_id: str,
    upload_dir: Path,
    output_dir: Path,
) -> None:
    """
    Worker function.
    In 'merge' mode: takes all video IDs in the batch, merges them into 1 video, and edits it.
    In 'individual' mode: runs every job in the batch one-by-one.
    Calls process_video_prompt() or process_multi_video_prompt().
    Safe to call from FastAPI BackgroundTasks (runs in a thread pool).
    """
    batch = get_batch(batch_id)
    if not batch:
        print(f"[batch] batch_id {batch_id} not found — aborting.")
        return

    update_job_status.__module__   # keep import alive
    mode = batch.get("mode", "individual")

    if mode == "merge":
        jobs = batch.get("jobs", [])
        if not jobs:
            return
        job = jobs[0]
        job_id = job["job_id"]
        prompt = job["prompt"]
        provider = job["provider"]
        raw_vids = [v.strip() for v in job["video_id"].split(",") if v.strip()]

        update_job_status(job_id, "processing")

        video_paths = []
        for vid in raw_vids:
            matches = list(upload_dir.glob(f"{vid}.*"))
            if not matches:
                update_job_status(
                    job_id, "failed",
                    error_message=f"Video file not found for video_id={vid}",
                )
                print(f"[batch-merge] file not found for video_id={vid}")
                return
            video_paths.append(matches[0])

        output_name = f"{uuid.uuid4().hex}_edited.mp4"
        output_path = output_dir / output_name

        try:
            print(f"[batch-merge] starting merge edit for {len(video_paths)} clips in batch {batch_id}...")
            process_multi_video_prompt(
                video_paths=video_paths,
                prompt=prompt,
                output_video=str(output_path),
                provider=provider,
            )

            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise RuntimeError("Merged output video was not created.")

            update_job_status(
                job_id, "completed",
                output_filename=output_name,
            )
            with _get_conn() as conn:
                conn.execute(
                    "UPDATE batches SET output_filename = ? WHERE batch_id = ?",
                    (output_name, batch_id),
                )
            print(f"[batch-merge] batch {batch_id} completed → {output_name}")

        except Exception as exc:
            output_path.unlink(missing_ok=True)
            update_job_status(
                job_id, "failed",
                error_message=f"{type(exc).__name__}: {exc}",
            )
            print(f"[batch-merge] batch {batch_id} FAILED: {exc}")
        return

    for job in batch.get("jobs", []):
        job_id   = job["job_id"]
        video_id = job["video_id"]
        prompt   = job["prompt"]
        provider = job["provider"]

        # Only process pending jobs (tolerate retries).
        if job["status"] not in ("pending", "failed"):
            continue

        # Locate the uploaded video file.
        matches = list(upload_dir.glob(f"{video_id}.*"))
        if not matches:
            update_job_status(
                job_id, "failed",
                error_message=f"Video file not found for video_id={video_id}",
            )
            continue

        input_path  = matches[0]
        output_name = f"{uuid.uuid4().hex}_edited.mp4"
        output_path = output_dir / output_name

        update_job_status(job_id, "processing")

        try:
            process_video_prompt(
                input_video=str(input_path),
                prompt=prompt,
                output_video=str(output_path),
                provider=provider,
            )

            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise RuntimeError("Output video was not created.")

            update_job_status(
                job_id, "completed",
                output_filename=output_name,
            )
            print(f"[batch] job {job_id} completed → {output_name}")

        except Exception as exc:
            output_path.unlink(missing_ok=True)
            update_job_status(
                job_id, "failed",
                error_message=f"{type(exc).__name__}: {exc}",
            )
            print(f"[batch] job {job_id} FAILED: {exc}")
