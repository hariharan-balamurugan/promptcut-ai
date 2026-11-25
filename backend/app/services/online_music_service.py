
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

JAMENDO_API = "https://api.jamendo.com/v3.0/tracks/"
JAMENDO_DOWNLOAD_API = "https://api.jamendo.com/v3.0/tracks/file/"

CLIENT_ID = os.getenv("JAMENDO_CLIENT_ID")
print("Jamendo Client ID loaded:", bool(CLIENT_ID))

MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024

CATEGORY_SEARCH = {
    "instrumental": "peaceful ambient instrumental",
    "cinematic": "cinematic soundtrack orchestral",
    "tamil": "tamil folk traditional world",
}


def get_license_url(track: dict) -> str:
    """Get the Creative Commons license URL from track metadata."""

    license_url = track.get("license_ccurl")

    if license_url:
        return str(license_url)

    licenses = track.get("licenses")

    if isinstance(licenses, dict):
        license_url = licenses.get("cc", {}).get("url")

        if license_url:
            return str(license_url)

    return ""


def is_acceptable_license(license_url: str) -> bool:
    """Allow recognizable CC BY, CC BY-SA or CC0 licenses only."""

    if not license_url:
        return False

    normalized = license_url.lower().rstrip("/")

    if "creativecommons.org" not in normalized:
        return False

    if "/by-nc" in normalized or "/by-nd" in normalized:
        return False

    return (
        "/licenses/by/" in normalized
        or "/licenses/by-sa/" in normalized
        or "/publicdomain/zero/" in normalized
    )



def search_jamendo_music(category: str) -> dict:
    """Search Jamendo using multiple search strategies."""

    if not CLIENT_ID:
        raise ValueError("JAMENDO_CLIENT_ID is missing from .env.")

    category = category.lower().strip()

    # Try different search methods if one returns no results.
    search_attempts = [
        {
            "search": "instrumental",
            "vocalinstrumental": "instrumental",
        },
        {
            "fuzzytags": "ambient",
        },
        {
            "search": "peaceful music",
        },
        {
            "fuzzytags": "relaxation",
        },
    ]

    if category == "cinematic":
        search_attempts = [
            {"search": "cinematic soundtrack"},
            {"fuzzytags": "soundtrack"},
            {"fuzzytags": "orchestral"},
        ]
    elif category == "tamil":
        search_attempts = [
            {"search": "tamil music"},
            {"search": "kollywood"},
            {"fuzzytags": "tamil"},
            {"fuzzytags": "carnatic"},
            {"fuzzytags": "bollywood"},
            {"fuzzytags": "hindustani"},
            {"fuzzytags": "desi"},
            {"fuzzytags": "world"},
            {"fuzzytags": "folk"},
        ]

    for attempt_number, search_params in enumerate(
        search_attempts, start=1
    ):

        params = {
            "format": "json",
    "limit": 50,
    "include": "licenses+musicinfo",
    "audiodlformat": "mp32",
    "type": "single albumtrack",
    **search_params,
    "client_id": CLIENT_ID,
        }

        print(f"\nJamendo search attempt: {attempt_number}")
        print("Search parameters:", search_params)

        try:
            response = httpx.get(
                JAMENDO_API,
                params=params,
                timeout=30,
            )

            response.raise_for_status()
            data = response.json()

        except httpx.HTTPError as exc:
            print("API request failed:", exc)
            continue

        headers = data.get("headers", {})

        if headers.get("status") != "success":
            print("Jamendo API error:", headers)
            continue

        tracks = data.get("results", [])

        print("Tracks received:", len(tracks))

        for track in tracks:


            allowed = track.get("audiodownload_allowed")
            download_url = track.get("audiodownload", "")
            
            
 
            license_url = get_license_url(track)

            print(
                "Track:", track.get("name"),
                "| Download allowed:", allowed,
                "| License:", license_url,
            )
            if category == "tamil":
                musicinfo = track.get("musicinfo", {})
                language  = musicinfo.get("lang", "").lower()
                tags_raw  = musicinfo.get("tags", {})
                # Collect all tag strings (tags may be dict of lists or plain list)
                all_tags: list[str] = []
                if isinstance(tags_raw, dict):
                    for tag_list in tags_raw.values():
                        if isinstance(tag_list, list):
                            all_tags.extend(str(t).lower() for t in tag_list)
                elif isinstance(tags_raw, list):
                    all_tags = [str(t).lower() for t in tags_raw]

                TAMIL_LANGS  = {"ta", "hi", "te", "kn", "ml", "bn"}
                WORLD_TAGS   = {
                    "tamil", "kollywood", "carnatic", "bollywood",
                    "hindustani", "desi", "world", "folk", "indian",
                    "classical", "devotional",
                }
                is_tamil_lang = language in TAMIL_LANGS
                has_world_tag = bool(WORLD_TAGS.intersection(set(all_tags)))

                if not is_tamil_lang and not has_world_tag:
                    continue

            if allowed is not True:
                continue

            if not download_url:
                continue

            if not is_acceptable_license(license_url):
                continue

            print("\nEligible track found:", track.get("name"))

            return {
                "id": str(track.get("id")),
                "name": track.get("name", "Unknown"),
                "artist": track.get("artist_name", "Unknown"),
                "download_url": download_url,
                "license_url": license_url,
                "track_url": (
                    track.get("shareurl")
                    or track.get("shorturl")
                    or ""
                ),
                "category": category,
            }

    raise RuntimeError(
        "Jamendo returned no downloadable tracks matching "
        "the accepted license requirements. "
        "Check the search diagnostics above."
    )


def download_music_track(track, destination):
    if not CLIENT_ID:
        raise ValueError("JAMENDO_CLIENT_ID is missing in .env")

    track_id = track.get("id")

    if not track_id:
        raise ValueError("Jamendo track ID is missing")

    download_api = "https://api.jamendo.com/v3.0/tracks/file/"

    params = {
        "client_id": CLIENT_ID,
        "id": track_id,
        "audioformat": "mp32",
        "action": "download",
    }

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=60.0
        ) as client:

            response = client.get(
                download_api,
                params=params
            )

            response.raise_for_status()

            content = response.content

            # Check whether the response is an actual MP3 file
            is_mp3 = (
                content.startswith(b"ID3")
                or (
                    len(content) > 1
                    and content[0] == 0xFF
                    and (content[1] & 0xE0) == 0xE0
                )
            )

            if not is_mp3:
                raise ValueError(
                    f"Jamendo did not return an MP3 file. "
                    f"Content-Type: {response.headers.get('content-type')}"
                )

            destination = Path(destination)
            destination.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            destination.write_bytes(content)

            print("Music downloaded successfully!")
            print("Track:", track.get("name"))
            print("File:", destination)

            return str(destination)

    except httpx.HTTPError as error:
        raise RuntimeError(
            f"Jamendo download failed: {error}"
        ) from error



    

def get_online_music(category: str, temp_directory: str) -> dict:
    """Search and download one suitable online music track."""

    track = search_jamendo_music(category)

    destination = (
        Path(temp_directory) / f"jamendo_{track['id']}.mp3"
    )

    downloaded_path = download_music_track(
        track,
        destination,
    )

    downloaded_path = Path(downloaded_path)

    return {
        "path": str(downloaded_path),
        "filename": downloaded_path.name,
        "name": track["name"],
        "artist": track["artist"],
        "source": "Jamendo",
        "category": track["category"],
        "license": track["license_url"],
        "track_url": track["track_url"],
        "downloaded_bytes": downloaded_path.stat().st_size,
    }
