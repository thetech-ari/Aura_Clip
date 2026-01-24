"""
Helpers for writing runtime metrics (summary + per-scene) to /runs.

Files:
    runs/detect_log.json   - history of detection runs (JSON array)
    runs/detect_log.csv    - detection run summaries (CSV)
    runs/export_log.json   - export summaries (already used)
    runs/export_log.csv    - export summaries (CSV)
    runs/detect_scenes.csv - per-scene metrics (one row per scene)
"""

from __future__ import annotations

import csv
import datetime
import json
import os
from typing import Dict, List

# Create the /runs directory if needed and return its path
def _ensure_runs_dir() -> str:
    runs_dir = os.path.join(os.getcwd(), "runs")
    os.makedirs(runs_dir, exist_ok=True)
    return runs_dir


def append_summary(kind: str, data: Dict) -> None:
    """
    Append a single summary entry as both JSON and CSV.

    kind:
        "detect", "export", etc. → files like detect_log.json / detect_log.csv
    data:
        Flat dict; 'timestamp' will be added automatically.
    """
    runs_dir = _ensure_runs_dir()

    # Timestamp + payload
    log_entry = {"timestamp": datetime.datetime.now().isoformat(), **data}

    # --- JSON log (array of entries) ---
    json_path = os.path.join(runs_dir, f"{kind}_log.json")
    logs = []
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                logs = json.load(f) or []
        except Exception:
            logs = []

    logs.append(log_entry)
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2)
    except Exception as e:
        print(f"[LOGGING WARNING] Could not update {json_path}: {e}")

    # --- CSV log (one row per run) ---
    csv_path = os.path.join(runs_dir, f"{kind}_log.csv")
    write_header = not os.path.exists(csv_path)

    try:
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=log_entry.keys())
            if write_header:
                writer.writeheader()
            writer.writerow(log_entry)
    except Exception as e:
        print(f"[LOGGING WARNING] Could not update {csv_path}: {e}")


def append_rows(kind: str, rows: List[Dict]) -> None:
    """
    Append multiple detail rows (e.g., per-scene metrics) to a CSV.

    kind:
        - "detect_scenes" → runs/detect_scenes.csv
        - other kinds can be added later if needed.
    rows:
        List of dicts with identical keys; a 'timestamp' can be included
        by the caller.
    """
    if not rows:
        return

    runs_dir = _ensure_runs_dir()

    if kind == "detect_scenes":
        base_name = "detect_scenes"
    else:
        base_name = kind

    csv_path = os.path.join(runs_dir, f"{base_name}.csv")
    
    # Dynamically merge columns when new fields are added
    # Read existing headers if file exists
    existing_fieldnames = []
    if os.path.exists(csv_path):
        try:
            with open(csv_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                existing_fieldnames = list(reader.fieldnames or [])
        except Exception:
            existing_fieldnames = []
    
    # Get fieldnames from new rows
    new_fieldnames = list(rows[0].keys())
    
    # Merge: keep existing order, append any new fields at the end
    if existing_fieldnames:
        merged_fieldnames = existing_fieldnames[:]
        for field in new_fieldnames:
            if field not in merged_fieldnames:
                merged_fieldnames.append(field)
        fieldnames = merged_fieldnames
        write_header = False  # File exists, don't overwrite header
    else:
        fieldnames = new_fieldnames
        write_header = True  # New file, write header

    try:
        # Check if schema has evolved (new columns added)
        schema_changed = (existing_fieldnames and 
                          set(new_fieldnames) != set(existing_fieldnames))
        
        if schema_changed:
            # ===== Log schema changes for debugging =====
            # When new metrics are added, log which columns were added
            # This helps track the evolution of the dataset schema
            new_columns = set(new_fieldnames) - set(existing_fieldnames)
            print(f"[Fix #5: CSV Schema Update] Adding new columns to {base_name}.csv:")
            print(f"  New fields: {', '.join(sorted(new_columns))}")
            print(f"  Total columns: {len(existing_fieldnames)} → {len(fieldnames)}")
            
            # Read all existing rows (preserve historical data)
            existing_rows = []
            if os.path.exists(csv_path):
                with open(csv_path, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    existing_rows = list(reader)
            
            # Rewrite with merged headers + all rows (old + new)
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                # Write old rows with missing fields filled as empty strings
                for row in existing_rows:
                    filled_row = {field: row.get(field, "") for field in fieldnames}
                    writer.writerow(filled_row)
                
                # Write new rows
                for row in rows:
                    filled_row = {field: row.get(field, "") for field in fieldnames}
                    writer.writerow(filled_row)
            
            print(f"  ✓ Successfully updated {len(existing_rows)} existing rows with new schema")
        else:
            # Schema unchanged: Fast append path (no rewrite needed)
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if write_header:
                    writer.writeheader()
                for row in rows:
                    writer.writerow(row)
                    
    except Exception as e:
        print(f"[LOGGING WARNING] Could not update {csv_path}: {e}")
