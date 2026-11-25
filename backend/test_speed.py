import time
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path("c:/Users/harih/Downloads/ai/backend").resolve()))

from app.services.video_service import process_video_prompt

input_video = "c:/Users/harih/Downloads/ai/backend/uploads/01c366613ca94f6b97113903d95bcbd7.mp4"
output_video = "c:/Users/harih/Downloads/ai/backend/outputs/test_speed_out.mp4"
prompt = "make the vedio cenimatic and add suitable song and make slide from top to bottom"

print(f"Starting test with prompt: {prompt}")
start = time.time()

try:
    result = process_video_prompt(
        input_video=input_video,
        prompt=prompt,
        output_video=output_video,
        provider="auto",
        fast_mode=True,
    )
    elapsed = time.time() - start
    print(f"\n==========================================")
    print(f"SUCCESS! Output created in {elapsed:.2f} seconds!")
    print(f"Output path: {result['output_path']}")
    print(f"Plan: {result['plan']}")
    print(f"Operations: {result['operations_applied']}")
    print(f"==========================================")
except Exception as e:
    import traceback
    print(f"FAILED after {time.time() - start:.2f} seconds:")
    traceback.print_exc()
