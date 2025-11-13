"""
Analyzer package for Aura Clip.

Iteration 2:
    - Encapsulates detection backends (PySceneDetect, AI experimental, etc.)
    - Allows the UI layer (app.py) to stay thin and just call run_* functions.
"""

from .pyscenedetect_analyzer import SCENEDETECT_AVAILABLE, run_pyscenedetect

__all__ = [
    "SCENEDETECT_AVAILABLE",
    "run_pyscenedetect",
]
