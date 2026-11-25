
import json
import subprocess
import tempfile

from pathlib import Path


def assemble_music_timeline(
    matching_json: str,
    music_path: str,
    output_path: str,
    ffmpeg_path: str = "ffmpeg",
    fade_seconds: float = 0.08,
):
    """
    Stage 7.9:
    Assemble ranked music segments to match video intervals.

    If a selected segment is shorter than its video interval,
    use additional ranked candidates to fill the remaining time.
    A music segment is not reused across video intervals.
    """

    matching_file = Path(matching_json).resolve()
    source_music = Path(music_path).resolve()
    final_output = Path(output_path).resolve()

    if not matching_file.is_file():
        raise FileNotFoundError(matching_file)

    if not source_music.is_file():
        raise FileNotFoundError(source_music)

    with matching_file.open("r", encoding="utf-8") as file:
        data = json.load(file)

    intervals = data.get("matching_plan", [])

    if not intervals:
        raise ValueError("No matching intervals found.")

    used_segments = set()
    assembled_parts = []

    final_output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="promptcut_stage79_"
    ) as temp_dir:

        temp_dir = Path(temp_dir)

        for index, interval in enumerate(intervals):

            required_duration = float(
                interval["video_duration_seconds"]
            )

            candidates = sorted(
                interval.get("top_matches", []),
                key=lambda item: float(item.get("score", 0)),
                reverse=True,
            )

            remaining = required_duration
            interval_parts = []

            for candidate in candidates:

                segment_id = candidate["segment_id"]

                if segment_id in used_segments:
                    continue

                start = float(candidate["music_start_time"])
                end = float(candidate["music_end_time"])

                available = end - start

                if available <= 0:
                    continue

                take_duration = min(available, remaining)

                if take_duration <= 0:
                    continue

                part_path = temp_dir / (
                    f"interval_{index + 1}_part_"
                    f"{len(interval_parts) + 1}.wav"
                )

                command = [
                    ffmpeg_path,
                    "-y",
                    "-ss", str(start),
                    "-i", str(source_music),
                    "-t", str(take_duration),
                    "-vn",
                    "-ac", "2",
                    "-ar", "44100",
                    "-c:a", "pcm_s16le",
                    str(part_path),
                ]

                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                )

                if result.returncode != 0:
                    raise RuntimeError(
                        f"FFmpeg extraction failed: "
                        f"{result.stderr[-1000:]}"
                    )

                if not part_path.is_file():
                    raise RuntimeError(
                        "Audio segment was not created."
                    )

                interval_parts.append(part_path)
                used_segments.add(segment_id)

                remaining -= take_duration

                if remaining <= 0.001:
                    break

            if remaining > 0.05:
                raise RuntimeError(
                    f"Could not fill video interval "
                    f"{index + 1}. Missing {remaining:.3f} seconds."
                )

            # Join the selected pieces for this video interval.
            interval_list = temp_dir / (
                f"interval_{index + 1}_list.txt"
            )

            with interval_list.open(
                "w", encoding="utf-8"
            ) as file:

                for part in interval_parts:
                    escaped = str(part).replace("'", "'\\''")
                    file.write(f"file '{escaped}'\n")

            interval_output = temp_dir / (
                f"interval_{index + 1}.wav"
            )

            command = [
                ffmpeg_path,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(interval_list),
                "-af",
                f"afade=t=in:d={fade_seconds},"
                f"afade=t=out:st="
                f"{max(0.01, required_duration - fade_seconds)}:"
                f"d={fade_seconds}",
                "-t", str(required_duration),
                "-ac", "2",
                "-ar", "44100",
                str(interval_output),
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Interval assembly failed: "
                    f"{result.stderr[-1000:]}"
                )

            assembled_parts.append(interval_output)

            print(
                f"Interval {index + 1}: "
                f"{interval['emotion']} | "
                f"{required_duration:.2f}s | "
                f"{len(interval_parts)} music part(s)"
            )

        # Concatenate all video-aligned interval audio files.
        final_list = temp_dir / "final_list.txt"

        with final_list.open(
            "w", encoding="utf-8"
        ) as file:

            for part in assembled_parts:
                escaped = str(part).replace("'", "'\\''")
                file.write(f"file '{escaped}'\n")

        command = [
            ffmpeg_path,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(final_list),
            "-c:a", "pcm_s16le",
            str(final_output),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Final audio assembly failed: "
                f"{result.stderr[-1000:]}"
            )

    print("\nStage 7.9 completed.")
    print("Output:", final_output)
    print("Used segments:", sorted(used_segments))

    return {
        "output_path": str(final_output),
        "interval_count": len(intervals),
        "used_segments": sorted(used_segments),
    }
