
import tempfile

from app.services.online_music_service import get_online_music

with tempfile.TemporaryDirectory() as temp_dir:

    print("Searching Jamendo for instrumental music...")

    result = get_online_music(
    category="tamil",
    temp_directory="backend/music"
)

    print("\nOnline music found!")
    print("Track:", result["name"])
    print("Artist:", result["artist"])
    print("Category:", result["category"])
    print("License:", result["license"])
    print("Track URL:", result["track_url"])
    print("Downloaded file:", result["path"])
    print("File size:", result["downloaded_bytes"])
