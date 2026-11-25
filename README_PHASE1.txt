PROMPTCUT AI - PHASE 1 MUSIC CATALOG
===================================

This patch adds a shared SQLite music catalog used by FastAPI and the Telegram bot.
It preserves the existing video editing endpoints and FFmpeg processing flow.

FILES TO COPY INTO YOUR EXISTING PROJECT
----------------------------------------
1. backend/main.py
   Replace your existing backend/main.py with this updated file.

2. backend/telegram_music_bot.py
   Replace your existing backend/telegram_music_bot.py with this updated file.

3. backend/app/services/video_service.py
   Replace your existing backend/app/services/video_service.py with this updated file.

4. backend/app/services/music_catalog.py
   This is NEW. Add it at this exact path.

The database is created automatically at:
backend/data/music_catalog.db

DEPENDENCIES
------------
The new catalog uses Python's built-in sqlite3 module. No new pip package is needed.
Your existing dependencies (FastAPI, python-telegram-bot, python-dotenv, etc.) remain required.

WHAT IS ADDED
-------------
- Shared SQLite catalog for local, FastAPI-uploaded, and Telegram-uploaded tracks.
- Automatic registration of existing audio files in:
    backend/music/tamil/
    backend/music/instrumental/
    backend/music/cinematic/
    backend/music_uploads/
    project-root music/ folders, if present.
- Search/filter tracks by title, artist, language, category, mood, and source.
- Create and track music acquisition requests.
- Request statuses: requested, searching, importing, processing, available, failed.
- AI video music selection now checks the PromptCut local catalog first, then Jamendo.
- Telegram uploads are automatically registered in the same catalog.
- Deleting a catalog record does NOT delete the audio file.

NEW / UPDATED API ROUTES
------------------------
GET    /api/music/library?query=&language=&category=&mood=&source=&limit=100
GET    /api/music/search?q=&language=&category=
GET    /api/music/{music_id}
DELETE /api/music/{music_id}
POST   /api/music/request
GET    /api/music/requests?status=requested
PATCH  /api/music/requests/{request_id}
GET    /api/music/recommend?category=tamil&language=tamil&mood=happy

Existing POST /api/music/upload remains available. It now also registers the uploaded
track in the catalog and returns its music_id.

REQUEST EXAMPLE
---------------
POST /api/music/request
Content-Type: application/json

{
  "title": "Example Tamil song",
  "artist": "Artist name",
  "language": "tamil",
  "notes": "Need an authorized copy for editing"
}

STATUS UPDATE EXAMPLE
---------------------
PATCH /api/music/requests/REQUEST_ID
Content-Type: application/json

{
  "status": "failed",
  "failure_reason": "No authorized source found"
}

RUN
---
From your project root in PowerShell:

.\venv\Scripts\Activate.ps1
python -m uvicorn main:app --app-dir backend --reload

Open http://127.0.0.1:8000/docs

Telegram bot (from project root):
python backend/telegram_music_bot.py

IMPORTANT NOTES
---------------
- Existing files are scanned and registered on FastAPI startup.
- Telegram and FastAPI uploads receive the license label
  "user_supplied_unverified". This is deliberate: uploading a file does not prove
  that it is licensed for synchronization, editing, or redistribution.
- The request system manages requests and statuses. It does not automatically
  download songs from YouTube, Spotify, or unauthorized sources.
- The PATCH request-status route currently has no authentication. Keep this API
  local/private until authentication and authorization are added.
- The DELETE catalog route removes only the database record, not the audio file.
