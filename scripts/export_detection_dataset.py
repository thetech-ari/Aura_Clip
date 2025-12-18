# scripts/export_detection_dataset.py 

"""
Export a clean detection dataset for AI training.

Reads:
    runs/detect_scenes.csv  (written by run_logs.metrics.append_rows)

Writes:
    runs/datasets/detect_scenes_clean.csv
    runs/datasets/detect_scenes.jsonl

Each row is one scene with:
    file, scene_idx, start_s, end_s, duration_s, fps,
    threshold, source, motion_proxy, highlight_score
"""

from __future__ import annotations
import csv
import json
import os
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(os.getcwd())
RUNS_DIR = PROJECT_ROOT / "runs"
SRC_CSV = RUNS_DIR / "detect_scenes.csv"
DATASET_DIR = RUNS_DIR / "datasets"
OUT_CSV = DATASET_DIR / "detect_scenes_clean.csv"
OUT_JSONL = DATASET_DIR / "detect_scenes.jsonl"


COLUMNS = [
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


def main() -> None:
    if not SRC_CSV.exists():
        print(f"[export_detection_dataset] No source CSV found at {SRC_CSV}")
        print("Run Aura Clip and detect scenes at least once before exporting.")
        return

    DATASET_DIR.mkdir(parents=True, exist_ok=True)

    rows: List[Dict] = []
    with SRC_CSV.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in COLUMNS if c not in reader.fieldnames]
        if missing:
            raise RuntimeError(
                f"Source CSV is missing required columns: {missing}. "
                f"Found columns: {reader.fieldnames}"
            )

        for raw in reader:
            # Keep only the columns we care about
            row = {col: raw.get(col) for col in COLUMNS}
            rows.append(row)

    if not rows:
        print("[export_detection_dataset] No rows found; nothing to export.")
        return

    # --- Write clean CSV ---
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    # --- Write JSONL ---
    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for row in rows:
            # Convert numeric-looking fields
            cleaned = dict(row)
            for k in ["scene_idx", "start_s", "end_s", "duration_s", "fps", "threshold", "motion_proxy"]:
                if cleaned.get(k) is not None and cleaned[k] != "":
                    try:
                        if k == "scene_idx":
                            cleaned[k] = int(float(cleaned[k]))
                        else:
                            cleaned[k] = float(cleaned[k])
                    except ValueError:
                        pass
            f.write(json.dumps(cleaned) + "\n")

    print(f"[export_detection_dataset] Wrote {len(rows)} rows to:")
    print(f"  - {OUT_CSV}")
    print(f"  - {OUT_JSONL}")


if __name__ == "__main__":
    main()
