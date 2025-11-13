"""
AI Experimental analyzer stub for Aura Clip.

Iteration 2:
    - Provides a drop-in replacement for the detection backend
    - Does NOT run any real AI yet
    - Returns an empty scene list and zeroed metrics
    - Logs a clear warning so the user knows this is a stub
"""

from __future__ import annotations

import time
from typing import Any, Dict
from .scene_types import SceneDatum, AnalyzerResult

def run_ai_detection(
    filepath: str,
    threshold: float = 0.0,
    report=None,
) -> AnalyzerResult:
    """
    Stubbed AI detection backend.

    Designed to match the call pattern of run_pyscenedetect so it can be
    used with the same Worker/QThread wiring.

    Parameters:
        filepath: path to the video file (unused for now)
        threshold: ignored (reserved for future models)
        report: optional callback(dict) for progress updates

    Returns:
        dict with:
            - scenes: always []
            - threshold: 0.0
            - elapsed_s: very small stub time
            - backend: "ai_stub"
    """
    start = time.perf_counter()

    print("[AI Experimental] run_ai_detection() called — stub only, no real AI yet.")

    if callable(report):
        report({"phase": "detect", "mode": "ai_stub_start"})

    # simulate a tiny bit of work so it doesn't feel instant
    time.sleep(0.1)

    elapsed_s = time.perf_counter() - start

    if callable(report):
        report(
            {
                "phase": "detect",
                "mode": "ai_stub_end",
                "elapsed_s": elapsed_s,
            }
        )

    summary: Dict[str, Any] = {
        "backend": "ai_stub",
        "threshold": 0.0,
        "elapsed_s": float(elapsed_s),
        "scene_count": 0,
    }

    result: AnalyzerResult = {
        "scenes": [],        # no raw scenes yet
        "scene_data": [],    # no metrics yet
        "summary": summary,
        "threshold": 0.0,
        "elapsed_s": float(elapsed_s),
        "backend": "ai_stub",
    }

    return result

