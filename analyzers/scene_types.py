"""
Type helpers for analyzers.

These are mostly for structure & readability - they describe the shape of
scene-level metrics produced by detection backends (PySceneDetect, AI, etc.).
"""

from typing import TypedDict, List, Dict, Any


class SceneDatum(TypedDict):
    """Per-scene metrics used for logging and AI training."""
    scene_idx: int       # 0-based index in detection order
    start_s: float       # scene start time in seconds
    end_s: float         # scene end time in seconds
    duration_s: float    # end_s - start_s, clamped to >= 0
    fps: float           # video frames per second (0.0 if unknown)
    threshold: float     # detector threshold value used
    source: str          # "pyscenedetect" or "ai"
    motion_proxy: float  # placeholder motion indicator: 1 / max(0.1, duration_s)


class AnalyzerResult(TypedDict, total=False):
    """
    Generic detection result.

    For now we keep:
        - 'scenes': backend's raw scene list (for UI/export compatibility)
        - 'scene_data': List[SceneDatum] with normalized metrics
        - plus whatever summary fields we need (threshold, elapsed_s, etc.)
    """
    scenes: list
    scene_data: List[SceneDatum]
    summary: Dict[str, Any]
    threshold: float
    elapsed_s: float
    backend: str
    api: str
