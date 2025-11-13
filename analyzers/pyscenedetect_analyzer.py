"""
PySceneDetect-based scene analyzer for Aura Clip.

Responsible for:
    - Importing and adapting to PySceneDetect v0.6+ or v0.5 APIs
    - Running detection on a single video file
    - Returning a simple result dict used by the UI thread

Exposed API:
    - SCENEDETECT_AVAILABLE: bool
    - run_pyscenedetect(filepath, threshold=27.0, report=None) -> dict
"""

from __future__ import annotations

import time
from typing import Any, Dict, List
from .scene_types import SceneDatum, AnalyzerResult

SCENEDETECT_AVAILABLE: bool = False
SCENEDETECT_API: str | None = None

# Try v0.6+ first, then fall back to v0.5
try:
    # v0.6+ API
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    SCENEDETECT_AVAILABLE = True
    SCENEDETECT_API = "v0.6+"
except Exception:
    try:
        # v0.5 API
        from scenedetect import VideoManager, SceneManager  # type: ignore
        from scenedetect.detectors import ContentDetector  # type: ignore

        SCENEDETECT_AVAILABLE = True
        SCENEDETECT_API = "v0.5"
    except Exception:
        # remains unavailable; caller should show a friendly message
        SCENEDETECT_AVAILABLE = False
        SCENEDETECT_API = None


def run_pyscenedetect(
    filepath: str,
    threshold: float = 27.0,
    fps: float | None = None,
    report=None,
) -> AnalyzerResult:

    """
    Background job for scene detection.

    This function is designed to run inside the generic Worker in app.py.

    Parameters:
        filepath: path to the video file
        threshold: ContentDetector threshold (higher = fewer scenes)
        report: optional callback(dict) for progress updates

    Returns:
        dict with:
            - scenes: list of (start, end) timecodes from PySceneDetect
            - threshold: the threshold used
            - elapsed_s: total wall time in seconds
    """
    if not SCENEDETECT_AVAILABLE or not SCENEDETECT_API:
        raise RuntimeError("PySceneDetect is not available in this environment.")

    start_time = time.perf_counter()

    if callable(report):
        report({"phase": "detect", "mode": "start"})

    # Use whichever API was successfully imported.
    if SCENEDETECT_API == "v0.6+":
        video = open_video(filepath)
        sm = SceneManager()
        sm.add_detector(ContentDetector(threshold=threshold, luma_only=True))
        sm.detect_scenes(video)
        scenes: List[Any] = sm.get_scene_list()

    elif SCENEDETECT_API == "v0.5":
        vm = VideoManager([filepath])
        sm = SceneManager()
        sm.add_detector(ContentDetector(threshold=threshold))
        vm.set_downscale_factor()
        vm.start()
        sm.detect_scenes(frame_source=vm)
        scenes = sm.get_scene_list()
        vm.release()
    else:
        raise RuntimeError(f"Unsupported PySceneDetect API version: {SCENEDETECT_API!r}")

    elapsed_s = time.perf_counter() - start_time

    if callable(report):
        report({"phase": "detect", "mode": "end", "elapsed_s": elapsed_s})

    # --- Build normalized per-scene metrics ---
    fps_value = 0.0 if fps is None else float(fps)

    scene_data: List[SceneDatum] = []
    for idx, (start_tc, end_tc) in enumerate(scenes, start=0):
        # PySceneDetect FrameTimecode objects provide get_seconds()
        try:
            start_s = float(start_tc.get_seconds())
            end_s = float(end_tc.get_seconds())
        except AttributeError:
            # In case a future backend returns plain floats
            start_s = float(start_tc)
            end_s = float(end_tc)

        duration_s = max(0.0, end_s - start_s)

        scene_data.append(
            SceneDatum(
                scene_idx=idx,
                start_s=start_s,
                end_s=end_s,
                duration_s=duration_s,
                fps=fps_value,
                threshold=float(threshold),
                source="pyscenedetect",
            )
        )

    # Summary is lightweight now; more fields later will be added later
    summary: Dict[str, Any] = {
        "backend": "pyscenedetect",
        "api": SCENEDETECT_API,
        "threshold": float(threshold),
        "elapsed_s": float(elapsed_s),
        "video_fps": fps_value,
        "scene_count": len(scene_data),
    }

    # keeps 'scenes' (raw PySceneDetect output) for UI/export compatibility
    result: AnalyzerResult = {
        "scenes": scenes,
        "scene_data": scene_data,
        "summary": summary,
        "threshold": float(threshold),
        "elapsed_s": float(elapsed_s),
        "backend": "pyscenedetect",
        "api": SCENEDETECT_API,
    }

    return result
