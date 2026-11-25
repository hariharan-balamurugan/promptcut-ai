import sys
sys.path.insert(0, '.')

try:
    from app.services.batch_service import init_batch_db, create_batch, get_batch, update_job_status, list_batches
    print("batch_service: OK")
except Exception as e:
    print(f"batch_service: FAIL - {e}")

try:
    from app.services.reference_video_service import analyze_reference_video, save_reference_profile, load_reference_profile, apply_reference_style
    print("reference_video_service: OK")
except Exception as e:
    print(f"reference_video_service: FAIL - {e}")

try:
    from app.services.music_catalog import init_catalog, search_tracks
    print("music_catalog: OK")
except Exception as e:
    print(f"music_catalog: FAIL - {e}")

try:
    init_batch_db()
    print("init_batch_db(): OK")
except Exception as e:
    print(f"init_batch_db(): FAIL - {e}")

print("All checks done.")
