"""
Basic regression tests for Aura Clip analyzers (Iteration 2).

Usage:
    python -m tests.test_analyzers

Behavior:
    - If PySceneDetect or the sample video are missing, prints SKIP.
    - Otherwise, runs PySceneDetect on a sample file, logs per-scene rows
      using the same schema as the app, and asserts:
        * scene_data length == number of rows just written
        * required columns exist in runs/detect_scenes.csv
"""

from __future__ import annotations

import csv
import datetime
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

from Aura_Clip.analyzers import run_pyscenedetect, SCENEDETECT_AVAILABLE
from Aura_Clip.run_logs.metrics import append_rows

PROJECT_ROOT = Path(os.getcwd())
RUNS_DIR = PROJECT_ROOT / "runs"
SRC_SCENES_CSV = RUNS_DIR / "detect_scenes.csv"
SAMPLES_DIR = PROJECT_ROOT / "video_samples"

# You can adjust this to match whatever sample file you have
SAMPLE_FILE = SAMPLES_DIR / "vs_1.mp4"

REQUIRED_COLUMNS = [
    "timestamp",
    "file",
    "scene_idx",
    "start_s",
    "end_s",
    "duration_s",
    "fps",
    "threshold",
    "source",
    "motion_proxy",
    "highlight_score",
]


def _print(msg: str) -> None:
    print(f"[test_analyzers] {msg}")


def main() -> None:
    # 1) Environment checks
    if not SCENEDETECT_AVAILABLE:
        _print("SKIP: PySceneDetect is not available in this environment.")
        return

    if not SAMPLE_FILE.exists():
        _print(f"SKIP: sample media not found at {SAMPLE_FILE}")
        _print("      Add a small test video there to enable the test.")
        return

    _print("Running analyzer regression test...")
    _print(f"Using sample file: {SAMPLE_FILE}")

    # 2) Run detection backend directly
    result = run_pyscenedetect(str(SAMPLE_FILE), threshold=27.0, fps=30.0)
    scene_data: List[Dict[str, Any]] = list(result.get("scene_data", []))
    scene_count = len(scene_data)

    if scene_count == 0:
        _print("WARN: No scenes detected in sample media. "
               "Test will only check column presence.")
    else:
        _print(f"Detected {scene_count} scene(s).")

    # 3) Log rows using the same schema as the app
    now_ts = datetime.datetime.now().isoformat()
    file_name = SAMPLE_FILE.name

    rows: List[Dict[str, Any]] = []
    for sd in scene_data:
        row = {
            "timestamp": now_ts,
            "file": file_name,
            "scene_idx": sd.get("scene_idx", -1),
            "start_s": sd.get("start_s", 0.0),
            "end_s": sd.get("end_s", 0.0),
            "duration_s": sd.get("duration_s", 0.0),
            "fps": sd.get("fps", 0.0),
            "threshold": sd.get("threshold", 0.0),
            "source": sd.get("source", "unknown"),
            "motion_proxy": sd.get("motion_proxy", 0.0),
        }
        rows.append(row)

    if rows:
        append_rows("detect_scenes", rows)
        _print(f"Appended {len(rows)} row(s) to runs/detect_scenes.csv")

    # 4) Re-open CSV and run assertions
    if not SRC_SCENES_CSV.exists():
        raise AssertionError(f"{SRC_SCENES_CSV} was not created.")

    with SRC_SCENES_CSV.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []

        # Column presence check
        for col in REQUIRED_COLUMNS:
            if col not in header:
                raise AssertionError(f"Missing required column: {col}")

        all_rows = list(reader)

    _print(f"detect_scenes.csv currently has {len(all_rows)} total rows.")

    if scene_count > 0:
        # Compare last N rows to the scene_data we just wrote
        last_rows = all_rows[-scene_count:]
        if len(last_rows) != scene_count:
            raise AssertionError(
                f"Expected at least {scene_count} new rows, found {len(last_rows)}."
            )

        # Basic shape checks on last rows
        for idx, r in enumerate(last_rows):
            if r.get("file") != file_name:
                raise AssertionError(
                    f"Row {idx} file mismatch: expected {file_name}, got {r.get('file')}"
                )

    _print("PASS: Analyzer regression checks succeeded.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _print(f"FAIL: {e}")
        sys.exit(1)
