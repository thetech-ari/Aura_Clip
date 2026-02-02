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

# Iteration 2: Audio analysis for highlight detection
try:
    from pydub import AudioSegment
    from pydub.utils import mediainfo
    AUDIO_AVAILABLE = True
except ImportError:
    AudioSegment = None
    AUDIO_AVAILABLE = False

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

def extract_audio_energy(filepath: str, start_s: float, end_s: float) -> float:
    """
    Iteration 2: Extract RMS audio energy for a scene segment.
    
    Returns normalized audio intensity (0.0 - 1.0) where higher = louder.
    Returns 0.0 if audio extraction fails or pydub unavailable.
    """
    if not AUDIO_AVAILABLE or not AudioSegment:
        return 0.0
    
    try:
        # Load full audio (pydub handles format detection via ffmpeg)
        audio = AudioSegment.from_file(filepath)
        
        # Extract segment [start_s, end_s] in milliseconds
        start_ms = int(start_s * 1000)
        end_ms = int(end_s * 1000)
        segment = audio[start_ms:end_ms]
        
        # Calculate RMS (root mean square) energy - measures loudness
        # pydub's rms returns a value typically 0-20000+ for 16-bit audio
        rms = segment.rms
        
        # Normalize: typical gameplay audio RMS ranges 500-15000
        # We'll cap at 15000 and normalize to 0.0-1.0
        rms_normalized = min(float(rms), 15000.0) / 15000.0
        
        return float(round(rms_normalized, 4))
        
    except Exception as e:
        # Silent fallback - audio extraction is optional enhancement
        print(f"[Audio Extraction Warning] Scene {start_s:.1f}-{end_s:.1f}s: {e}")
        return 0.0

def compute_highlight_score(duration_s: float, motion_proxy: float, audio_energy: float = 0.0) -> float:
    """
    Iteration 2: Audio-enhanced highlight scoring.
    
    Ranking priority (per user requirement):
        1. Longest scenes with high audio energy (action moments)
        2. Audio intensity (gunshots, explosions, commentary excitement)
        3. Duration bonus (longer = more content)
    
    Weighting:
        - 60% audio energy (primary indicator of action)
        - 40% duration (prefer longer clips)
        - motion_proxy kept for backward compatibility in dataset logs
    
    Returns:
        float: highlight score 0.0-1.0 (higher = better highlight)
    """
    # Normalize audio energy (already 0-1 from extraction, but clamp for safety)
    audio = max(0.0, min(float(audio_energy), 1.0))
    
    # Normalize duration: cap at 30s (longer scenes ranked higher)
    dur = max(0.0, float(duration_s))
    dur_norm = min(dur, 30.0) / 30.0  # 0..1 range
    
    # Combine: 60% audio + 40% duration (prioritizes loud + long scenes)
    score = (0.60 * audio) + (0.40 * dur_norm)
    
    return float(round(score, 4))

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

    # Let UI know how many scenes were found before starting audio analysis
    if callable(report):
        report({"phase": "detect", "mode": "scene_count", "total_scenes": len(scenes)})

    # --- Build normalized per-scene metrics ---
    fps_value = 0.0 if fps is None else float(fps)

    scene_data: List[SceneDatum] = []

    # Iteration 2: Progress reporting for audio analysis (can be slow for long videos)
    if callable(report):
        report({"phase": "detect", "mode": "audio_analysis_start", "total_scenes": len(scenes)})

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

        # Iteration 2: Extract audio energy for this scene segment
        audio_energy = extract_audio_energy(filepath, start_s, end_s)

        # Update UI with current progress (every scene, not just every 5)
        if callable(report):
            report({
                "phase": "detect",
                "mode": "audio_progress",
                "done": idx + 1,
                "total": len(scenes)
            })

        # Lightweight motion proxy: shorter scenes → higher proxy value
        motion_proxy = 1.0 / max(0.1, duration_s)
        highlight_score = compute_highlight_score(duration_s, motion_proxy, audio_energy)

        scene_data.append(
            SceneDatum(
                scene_idx=idx,
                start_s=start_s,
                end_s=end_s,
                duration_s=duration_s,
                fps=fps_value,
                threshold=float(threshold),
                source="pyscenedetect",
                motion_proxy=motion_proxy,
                highlight_score=highlight_score,
                audio_energy=audio_energy,
                ai_detections=0.0,  # PySceneDetect mode doesn't use AI
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
