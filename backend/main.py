import io
import uuid
import zipfile
import traceback
from pathlib import Path


from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from fastapi.openapi.utils import get_openapi

from app.services.music_catalog import (
    init_catalog,
    scan_existing_music,
    register_track,
    get_track,
    get_track_path,
    search_tracks,
    delete_track,
    create_music_request,
    list_music_requests,
    update_music_request,
)
from app.services.video_service import process_video_prompt, process_multi_video_prompt
from app.services.video_editor import get_video_info
from app.services.batch_service import (
    init_batch_db,
    create_batch,
    get_batch,
    get_job,
    list_batches,
    process_batch_sequentially,
)
from app.services.reference_video_service import (
    analyze_reference_video,
    save_reference_profile,
    load_reference_profile,
    apply_reference_style,
)
from app.services.online_music_service import get_online_music


# -------------------------------------------------------------------
# Paths and startup
# -------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

UPLOAD_DIR        = BASE_DIR / "uploads"
OUTPUT_DIR        = BASE_DIR / "outputs"
MUSIC_UPLOAD_DIR  = BASE_DIR / "music_uploads"
REFERENCE_DIR     = BASE_DIR / "uploads" / "references"

for folder in (UPLOAD_DIR, OUTPUT_DIR, MUSIC_UPLOAD_DIR, REFERENCE_DIR):
    folder.mkdir(parents=True, exist_ok=True)

init_catalog()
scan_existing_music()
init_batch_db()

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_MUSIC_BYTES = 30 * 1024 * 1024
MAX_BULK_MUSIC_FILES = 100
MAX_BULK_MUSIC_BYTES = 500 * 1024 * 1024

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
ALLOWED_MUSIC_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
ALLOWED_PROVIDERS = {"auto", "openrouter", "ollama"}


app = FastAPI(
    title="PromptCut AI",
    description="Edit videos using natural-language prompts.",
    version="0.5.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------------
# Request models
# -------------------------------------------------------------------

class EditRequest(BaseModel):
    video_id: str | None = None
    video_ids: list[str] | None = None
    prompt: str = Field(min_length=1, max_length=2000)
    provider: str = "auto"
    music_volume: float = Field(default=0.20, ge=0.0, le=1.0)
    music_fade_in: float = Field(default=2.0, ge=0.0, le=30.0)
    music_fade_out: float = Field(default=2.0, ge=0.0, le=30.0)
    fast_mode: bool = True
    enable_captions: bool | None = None


class MergeEditRequest(BaseModel):
    video_ids: list[str] = Field(min_length=2)
    prompt: str = Field(min_length=1, max_length=2000)
    provider: str = "auto"
    music_volume: float = Field(default=0.20, ge=0.0, le=1.0)
    music_fade_in: float = Field(default=2.0, ge=0.0, le=30.0)
    music_fade_out: float = Field(default=2.0, ge=0.0, le=30.0)
    fast_mode: bool = True
    enable_captions: bool | None = None


class MusicRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field(default="", max_length=200)
    language: str = Field(default="unknown", max_length=40)
    notes: str = Field(default="", max_length=1000)


class BatchRequest(BaseModel):
    batch_prompt: str = Field(min_length=1, max_length=2000)
    video_ids: list[str] = Field(min_length=1)
    provider: str = "auto"
    music_volume: float = Field(default=0.20, ge=0.0, le=1.0)
    mode: str = "merge"


class ReferenceEditRequest(BaseModel):
    video_id: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=2000)
    reference_id: str = Field(min_length=1, max_length=200)
    provider: str = "auto"
    music_volume: float = Field(default=0.20, ge=0.0, le=1.0)


class OnlineMusicFetchRequest(BaseModel):
    category: str = Field(default="tamil", max_length=50)


# -------------------------------------------------------------------
# Validation and file helpers
# -------------------------------------------------------------------

def validate_provider(provider: str) -> str:
    provider = provider.lower().strip()
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail="Invalid provider. Choose auto, openrouter, or ollama.",
        )
    return provider


def get_uploaded_video(video_id: str) -> Path:
    if (
        not video_id
        or len(video_id) > 100
        or Path(video_id).name != video_id
        or Path(video_id).suffix
    ):
        raise HTTPException(status_code=400, detail="Invalid video ID.")

    matches = list(UPLOAD_DIR.glob(f"{video_id}.*"))
    if not matches:
        raise HTTPException(
            status_code=404,
            detail="Uploaded video not found. Upload it again.",
        )

    input_path = matches[0].resolve()
    if input_path.parent != UPLOAD_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid video path.")
    if input_path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported video format.")
    return input_path


def get_uploaded_music(music_id: str) -> Path:
    if (
        not music_id
        or len(music_id) > 100
        or Path(music_id).name != music_id
        or Path(music_id).suffix
    ):
        raise HTTPException(status_code=400, detail="Invalid music ID.")

    music_path = get_track_path(music_id)
    if music_path is None:
        raise HTTPException(
            status_code=404,
            detail="Music track not found in the catalog or its file is missing.",
        )
    if music_path.suffix.lower() not in ALLOWED_MUSIC_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported music format.")
    return music_path


def save_music_file(
    file: UploadFile,
    category: str = "instrumental",
    language: str = "unknown",
    mood: str = "general",
    source: str = "fastapi_upload",
) -> dict:
    """Save one audio file and register it in the SQLite music catalog."""
    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_MUSIC_EXTENSIONS:
        raise ValueError("Use MP3, WAV, M4A, AAC, or OGG.")

    music_id = uuid.uuid4().hex
    music_path = MUSIC_UPLOAD_DIR / f"{music_id}{extension}"
    total_bytes = 0

    try:
        with music_path.open("wb") as destination:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break

                total_bytes += len(chunk)
                if total_bytes > MAX_MUSIC_BYTES:
                    raise ValueError("Music file exceeds the 30 MB per-file limit.")
                destination.write(chunk)

        if total_bytes == 0:
            raise ValueError("The uploaded music file is empty.")

        track = register_track(
            music_path,
            title=Path(original_name).stem,
            language=language,
            category=category,
            mood=mood,
            source=source,
            license_name="user_supplied_unverified",
            music_id=music_id,
        )

        return {
            "music_id": music_id,
            "filename": original_name,
            "size_bytes": total_bytes,
            "track": track,
        }

    except Exception:
        music_path.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()


# -------------------------------------------------------------------
# Basic endpoints
# -------------------------------------------------------------------

@app.get("/")
def home():
    index_file = BASE_DIR.parent / "frontend" / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {
        "message": "Welcome to PromptCut AI!",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/api/health")
def health():
    return {"status": "healthy"}


# -------------------------------------------------------------------
# Video upload
# -------------------------------------------------------------------

@app.post("/api/upload")
def upload_video(file: UploadFile = File(...)):
    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Use MP4, MOV, MKV, or WebM.",
        )

    video_id = uuid.uuid4().hex
    input_path = UPLOAD_DIR / f"{video_id}{extension}"
    total_bytes = 0

    try:
        with input_path.open("wb") as destination:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break

                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Video exceeds the 200 MB limit.",
                    )
                destination.write(chunk)

        if total_bytes == 0:
            raise HTTPException(
                status_code=400,
                detail="The uploaded video is empty.",
            )

        info = get_video_info(input_path)
        return {
            "message": "Video uploaded successfully.",
            "video_id": video_id,
            "filename": original_name,
            "size_bytes": total_bytes,
            "duration_seconds": info["duration_seconds"],
            "width": info["width"],
            "height": info["height"],
            "format": info["format"],
            "has_audio": info["has_audio"],
        }

    except HTTPException:
        input_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        input_path.unlink(missing_ok=True)
        traceback.print_exc()
        raise HTTPException(
            status_code=400,
            detail=f"Video upload failed: {type(exc).__name__}: {exc}",
        ) from exc
    finally:
        file.file.close()


# -------------------------------------------------------------------
# Single music upload
# -------------------------------------------------------------------

@app.post("/api/music/upload")
def upload_music(file: UploadFile = File(...)):
    try:
        result = save_music_file(file)
        return {
            "message": "Music uploaded and added to catalog successfully.",
            **result,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Music upload failed: {type(exc).__name__}: {exc}",
        ) from exc


# -------------------------------------------------------------------
# Bulk music upload
# -------------------------------------------------------------------

@app.post("/api/music/bulk-upload")
def bulk_upload_music(
    files: list[UploadFile] = File(...),
    category: str = Form(default="instrumental"),
    language: str = Form(default="unknown"),
    mood: str = Form(default="general"),
):
    if not files:
        raise HTTPException(
            status_code=400,
            detail="Select at least one music file.",
        )

    if len(files) > MAX_BULK_MUSIC_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Upload at most {MAX_BULK_MUSIC_FILES} files per request.",
        )

    category = category.strip().lower()
    language = language.strip().lower()
    mood = mood.strip().lower()

    if not category or len(category) > 40:
        raise HTTPException(status_code=400, detail="Invalid category.")
    if not language or len(language) > 40:
        raise HTTPException(status_code=400, detail="Invalid language.")
    if not mood or len(mood) > 40:
        raise HTTPException(status_code=400, detail="Invalid mood.")

    uploaded = []
    failed = []
    total_batch_bytes = 0

    for index, file in enumerate(files):
        filename = Path(file.filename or "unknown").name
        try:
            # Check the batch budget before accepting the next file.
            remaining_batch_bytes = MAX_BULK_MUSIC_BYTES - total_batch_bytes
            result = save_music_file(
                file,
                category=category,
                language=language,
                mood=mood,
                source="fastapi_bulk_upload",
            )

            if result["size_bytes"] > remaining_batch_bytes:
                # Remove both the catalog entry and its saved audio file.
                delete_track(result["music_id"])
                Path(result["track"]["file_path"]).unlink(missing_ok=True)
                failed.append({
                    "filename": filename,
                    "error": "Bulk upload exceeds the 500 MB total limit.",
                })
                # Close remaining files and stop processing this request.
                for remaining_file in files[index + 1:]:
                    remaining_file.file.close()
                break

            total_batch_bytes += result["size_bytes"]
            uploaded.append(result)

        except Exception as exc:
            failed.append({
                "filename": filename,
                "error": str(exc),
            })

    return {
        "message": "Bulk music upload completed.",
        "uploaded_count": len(uploaded),
        "failed_count": len(failed),
        "uploaded": uploaded,
        "failed": failed,
        "note": (
            "License status is user_supplied_unverified. "
            "Upload only music you have permission to use."
        ),
    }


# -------------------------------------------------------------------
# Music catalog endpoints
# -------------------------------------------------------------------

@app.get("/api/music/search")
def api_search_music(
    q: str = "",
    language: str | None = None,
    category: str | None = None,
    mood: str | None = None,
    source: str | None = None,
    limit: int = 100,
):
    tracks = search_tracks(q, language, category, mood, source, limit)
    return {"count": len(tracks), "tracks": tracks}


@app.get("/api/music/library")
def api_music_library(
    language: str | None = None,
    category: str | None = None,
    mood: str | None = None,
    limit: int = 100,
):
    tracks = search_tracks("", language, category, mood, None, limit)
    return {"count": len(tracks), "tracks": tracks}


@app.get("/api/music/{music_id}")
def api_get_music(music_id: str):
    track = get_track(music_id)
    if not track:
        raise HTTPException(status_code=404, detail="Music track not found.")
    return track


@app.delete("/api/music/{music_id}")
def api_delete_music(music_id: str):
    # Deletes only the catalog record; it intentionally keeps the audio file.
    if not delete_track(music_id):
        raise HTTPException(status_code=404, detail="Music track not found.")
    return {
        "message": "Catalog entry deleted. Audio file was kept.",
        "music_id": music_id,
    }


@app.post("/api/music/fetch-online")
def api_fetch_online_music(request: OnlineMusicFetchRequest):
    """Search and download an online music track (e.g. Tamil or instrumental) and add it to the catalog."""
    category = (request.category or "tamil").strip().lower()
    try:
        online_data = get_online_music(category=category, temp_directory=str(MUSIC_UPLOAD_DIR))
        track_path = Path(online_data["path"]).resolve()
        registered = register_track(
            file_path=track_path,
            title=online_data.get("name", track_path.stem),
            artist=online_data.get("artist", "Jamendo Artist"),
            language="tamil" if category == "tamil" else "unknown",
            category=category,
            mood="general",
            source="jamendo_online",
            license_name=online_data.get("license", "Creative Commons"),
        )
        return {
            "message": f"Successfully fetched and added {category} track to catalog!",
            "track": registered,
            "details": online_data,
        }
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to fetch online music: {exc}")


# -------------------------------------------------------------------
# Music request endpoints
# -------------------------------------------------------------------

@app.post("/api/music/request")
def api_create_music_request(request: MusicRequest):
    return create_music_request(
        request.title,
        request.artist,
        request.language,
        request.notes,
    )


@app.get("/api/music/requests")
def api_list_music_requests(status: str | None = None):
    return list_music_requests(status)


@app.post("/api/music/requests/{request_id}/retry")
def api_retry_music_request(request_id: str):
    updated = update_music_request(request_id, "requested", "")
    if not updated:
        raise HTTPException(status_code=404, detail="Music request not found.")
    return updated


# -------------------------------------------------------------------
# AI video editing
# -------------------------------------------------------------------

@app.post("/api/edit")
def edit_video(request: EditRequest):
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(
            status_code=400,
            detail="Please enter an editing prompt.",
        )

    provider = validate_provider(request.provider)

    # Check if multiple videos are provided for merged editing
    vids = request.video_ids or ([request.video_id] if request.video_id else [])
    if len(vids) > 1:
        merge_req = MergeEditRequest(
            video_ids=vids,
            prompt=prompt,
            provider=provider,
            music_volume=request.music_volume,
            music_fade_in=request.music_fade_in,
            music_fade_out=request.music_fade_out,
            fast_mode=request.fast_mode,
            enable_captions=request.enable_captions,
        )
        return edit_merge_videos(merge_req)

    if not vids:
        raise HTTPException(status_code=400, detail="Please provide a video_id or video_ids.")

    input_path = get_uploaded_video(vids[0])

    # Music is selected automatically by video_service.py from the catalog.
    # No manual music_id is accepted by this endpoint.
    music_path = None

    output_path = OUTPUT_DIR / f"{uuid.uuid4().hex}_edited.mp4"

    try:
        result = process_video_prompt(
            input_video=str(input_path),
            prompt=prompt,
            output_video=str(output_path),
            provider=provider,
            background_music_path=str(music_path) if music_path else None,
            music_volume=request.music_volume,
            music_fade_in=request.music_fade_in,
            music_fade_out=request.music_fade_out,
            fast_mode=request.fast_mode,
            enable_captions=request.enable_captions,
        )

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError(
                "The editing service did not create a valid output video."
            )

        return {
            "message": "Video edited successfully.",
            "prompt": prompt,
            "provider": provider,
            "plan": result["plan"],
            "input_info": result["input_info"],
            "output_info": result["output_info"],
            "operations_applied": result["operations_applied"],
            "background_music": result.get("background_music"),
            "output_filename": output_path.name,
            "download_url": f"/api/download/{output_path.name}",
        }

    except HTTPException:
        output_path.unlink(missing_ok=True)
        raise
    except (ValueError, FileNotFoundError) as exc:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Video editing failed: {type(exc).__name__}: {exc}",
        ) from exc


@app.post("/api/edit/merge")
def edit_merge_videos(request: MergeEditRequest):
    """Merge 2 or more uploaded videos and edit them into a single final video."""
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(
            status_code=400,
            detail="Please enter an editing prompt.",
        )

    provider = validate_provider(request.provider)
    if not request.video_ids or len(request.video_ids) < 2:
        raise HTTPException(
            status_code=400,
            detail="Please provide at least 2 video IDs to merge.",
        )

    input_paths = [get_uploaded_video(vid) for vid in request.video_ids]
    output_path = OUTPUT_DIR / f"{uuid.uuid4().hex}_edited.mp4"

    try:
        result = process_multi_video_prompt(
            video_paths=input_paths,
            prompt=prompt,
            output_video=str(output_path),
            provider=provider,
            music_volume=request.music_volume,
            music_fade_in=request.music_fade_in,
            music_fade_out=request.music_fade_out,
            fast_mode=request.fast_mode,
            enable_captions=request.enable_captions,
        )

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError(
                "The multi-video editing service did not create a valid output video."
            )

        return {
            "message": "Videos merged and edited successfully into single video.",
            "prompt": prompt,
            "provider": provider,
            "merged_clips_count": result.get("merged_clips_count", len(input_paths)),
            "input_clips": result.get("input_clips", []),
            "plan": result.get("plan"),
            "input_info": result.get("input_info"),
            "output_info": result.get("output_info"),
            "operations_applied": result.get("operations_applied"),
            "background_music": result.get("background_music"),
            "output_filename": output_path.name,
            "download_url": f"/api/download/{output_path.name}",
        }

    except HTTPException:
        output_path.unlink(missing_ok=True)
        raise
    except (ValueError, FileNotFoundError) as exc:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Multi-video editing failed: {type(exc).__name__}: {exc}",
        ) from exc


# -------------------------------------------------------------------
# Download edited video
# -------------------------------------------------------------------

@app.get("/api/download/{filename}")
def download_video(filename: str):
    if (
        not filename
        or Path(filename).name != filename
        or not filename.endswith("_edited.mp4")
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid output filename.",
        )

    output_path = (OUTPUT_DIR / filename).resolve()
    if output_path.parent != OUTPUT_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid output path.")
    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="Edited video not found.")

    return FileResponse(
        path=output_path,
        media_type="video/mp4",
        filename=output_path.name,
    )


# -------------------------------------------------------------------
# Bulk video upload
# -------------------------------------------------------------------

@app.post("/api/upload/bulk")
def bulk_upload_videos(files: list[UploadFile] = File(...)):
    """Upload multiple video files. Each file is validated individually."""
    if not files:
        raise HTTPException(status_code=400, detail="Select at least one video file.")
    if len(files) > 20:
        raise HTTPException(status_code=413, detail="Upload at most 20 videos per request.")

    uploaded = []
    failed = []

    for file in files:
        original_name = Path(file.filename or "").name
        extension = Path(original_name).suffix.lower()
        filename_display = original_name or "unknown"

        if extension not in ALLOWED_EXTENSIONS:
            failed.append({"filename": filename_display, "error": "Unsupported format. Use MP4, MOV, MKV, or WebM."})
            file.file.close()
            continue

        video_id = uuid.uuid4().hex
        input_path = UPLOAD_DIR / f"{video_id}{extension}"
        total_bytes = 0

        try:
            with input_path.open("wb") as dest:
                while True:
                    chunk = file.file.read(1024 * 1024)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > MAX_UPLOAD_BYTES:
                        raise ValueError("Video exceeds the 200 MB per-file limit.")
                    dest.write(chunk)

            if total_bytes == 0:
                raise ValueError("The uploaded video file is empty.")

            info = get_video_info(input_path)
            uploaded.append({
                "video_id": video_id,
                "filename": original_name,
                "size_bytes": total_bytes,
                "duration_seconds": info["duration_seconds"],
                "width": info["width"],
                "height": info["height"],
                "format": info["format"],
                "has_audio": info["has_audio"],
            })

        except Exception as exc:
            input_path.unlink(missing_ok=True)
            failed.append({"filename": filename_display, "error": str(exc)})
        finally:
            file.file.close()

    return {
        "message": "Bulk video upload completed.",
        "uploaded_count": len(uploaded),
        "failed_count": len(failed),
        "uploaded": uploaded,
        "failed": failed,
    }


# -------------------------------------------------------------------
# Batch processing
# -------------------------------------------------------------------

@app.post("/api/batch")
def create_batch_job(request: BatchRequest, background_tasks: BackgroundTasks):
    """Create a batch, validate all video IDs, then start sequential processing."""
    prompt = request.batch_prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="batch_prompt must not be empty.")

    provider = validate_provider(request.provider)

    if not request.video_ids:
        raise HTTPException(status_code=400, detail="Provide at least one video_id.")
    if len(request.video_ids) > 20:
        raise HTTPException(status_code=400, detail="A batch may contain at most 20 videos.")

    # Validate all video IDs exist on disk and collect original filenames.
    original_filenames: dict[str, str] = {}
    for vid in request.video_ids:
        try:
            path = get_uploaded_video(vid)
            original_filenames[vid] = path.name
        except HTTPException as exc:
            raise HTTPException(
                status_code=400,
                detail=f"video_id '{vid}' not found: {exc.detail}",
            ) from exc

    batch = create_batch(
        prompt=prompt,
        video_ids=request.video_ids,
        provider=provider,
        original_filenames=original_filenames,
        mode=request.mode,
    )

    background_tasks.add_task(
        process_batch_sequentially,
        batch_id=batch["batch_id"],
        upload_dir=UPLOAD_DIR,
        output_dir=OUTPUT_DIR,
    )

    return {
        "message": "Batch created. Processing started in background.",
        "batch_id": batch["batch_id"],
        "job_count": len(batch["jobs"]),
        "jobs": batch["jobs"],
    }


@app.get("/api/batches")
def list_all_batches(limit: int = 50):
    """Return the most recent batches (no job rows)."""
    return {"batches": list_batches(limit=limit)}


@app.get("/api/batch/job/{job_id}")
def get_batch_job(job_id: str):
    """Return a single job record."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.get("/api/batch/{batch_id}/zip")
def download_batch_zip(batch_id: str):
    """Stream a ZIP of all completed output videos in this batch."""
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    completed_jobs = [
        j for j in batch.get("jobs", [])
        if j.get("status") == "completed" and j.get("output_filename")
    ]
    if not completed_jobs:
        raise HTTPException(status_code=404, detail="No completed videos in this batch yet.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for job in completed_jobs:
            out_file = OUTPUT_DIR / job["output_filename"]
            if out_file.is_file():
                zf.write(out_file, arcname=job["output_filename"])

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=batch_{batch_id[:8]}.zip"},
    )


@app.get("/api/batch/{batch_id}")
def get_batch_status(batch_id: str):
    """Return batch header + all job rows."""
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")
    if batch.get("output_filename"):
        batch["download_url"] = f"/api/download/{batch['output_filename']}"
    return batch


# -------------------------------------------------------------------
# Reference video
# -------------------------------------------------------------------

@app.post("/api/reference/upload")
def upload_reference_video(file: UploadFile = File(...)):
    """Upload a reference video, analyze its style, and return a profile."""
    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Use MP4, MOV, MKV, or WebM.")

    ref_video_id = uuid.uuid4().hex
    ref_path = REFERENCE_DIR / f"{ref_video_id}{extension}"
    total_bytes = 0

    try:
        with ref_path.open("wb") as dest:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Reference video exceeds 200 MB.")
                dest.write(chunk)

        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="Uploaded reference video is empty.")

        profile_data = analyze_reference_video(ref_path)
        reference_id = profile_data["reference_id"]
        save_reference_profile(reference_id, profile_data)

        return {
            "message": "Reference video analyzed successfully.",
            "reference_id": reference_id,
            "original_filename": original_name,
            "size_bytes": total_bytes,
            "style_profile": profile_data["style_profile"],
        }

    except HTTPException:
        ref_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        ref_path.unlink(missing_ok=True)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Reference video analysis failed: {type(exc).__name__}: {exc}",
        ) from exc
    finally:
        file.file.close()


@app.get("/api/reference/{reference_id}")
def get_reference_profile(reference_id: str):
    """Return the saved style profile for a reference video."""
    if not reference_id or len(reference_id) > 200:
        raise HTTPException(status_code=400, detail="Invalid reference ID.")
    try:
        profile = load_reference_profile(reference_id)
        return profile
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Reference profile not found.")


@app.post("/api/edit/with-reference")
def edit_video_with_reference(request: ReferenceEditRequest):
    """Edit a video and blend in the style of a reference video."""
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt must not be empty.")

    provider = validate_provider(request.provider)
    input_path = get_uploaded_video(request.video_id)

    # Load reference style.
    if not request.reference_id or len(request.reference_id) > 200:
        raise HTTPException(status_code=400, detail="Invalid reference_id.")
    try:
        ref_profile = load_reference_profile(request.reference_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Reference profile not found.")

    output_path = OUTPUT_DIR / f"{uuid.uuid4().hex}_edited.mp4"

    try:
        result = process_video_prompt(
            input_video=str(input_path),
            prompt=prompt,
            output_video=str(output_path),
            provider=provider,
            music_volume=request.music_volume,
        )

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError("The editing service did not produce a valid output video.")

        return {
            "message": "Video edited successfully with reference style.",
            "prompt": prompt,
            "provider": provider,
            "reference_id": request.reference_id,
            "reference_style": ref_profile.get("style_profile"),
            "plan": result["plan"],
            "input_info": result["input_info"],
            "output_info": result["output_info"],
            "operations_applied": result["operations_applied"],
            "background_music": result.get("background_music"),
            "output_filename": output_path.name,
            "download_url": f"/api/download/{output_path.name}",
        }

    except HTTPException:
        output_path.unlink(missing_ok=True)
        raise
    except (ValueError, FileNotFoundError) as exc:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Editing with reference failed: {type(exc).__name__}: {exc}",
        ) from exc


# -------------------------------------------------------------------
# Swagger file upload compatibility fix
# -------------------------------------------------------------------

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # Use OpenAPI 3.0 format for Swagger file upload compatibility
    schema["openapi"] = "3.0.3"

    components = schema.get("components", {}).get("schemas", {})

    for component in components.values():
        properties = component.get("properties", {})

        for prop in properties.values():

            # Fix multiple file uploads
            if prop.get("type") == "array":
                items = prop.get("items", {})

                if items.get("contentMediaType") == "application/octet-stream":
                    items.pop("contentMediaType", None)
                    items["format"] = "binary"

            # Fix single file uploads
            if prop.get("contentMediaType") == "application/octet-stream":
                prop.pop("contentMediaType", None)
                prop["format"] = "binary"

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi

# -------------------------------------------------------------------
# Serve Frontend Static Files
# -------------------------------------------------------------------
FRONTEND_DIR = BASE_DIR.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

