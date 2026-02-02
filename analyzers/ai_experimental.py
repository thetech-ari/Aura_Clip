"""
AI Experimental analyzer for Aura Clip using YOLOv8 object detection.

Iteration 2:
    - Uses pre-trained YOLOv8n (nano) model for real-time object detection
    - First runs PySceneDetect to find scene cuts
    - Extracts keyframes from each scene (start, middle, end)
    - Runs YOLO inference to detect action indicators (people, weapons, vehicles)
    - Combines AI detections + audio energy + duration for final ranking
    
This demonstrates understanding of:
    - Loading and using pre-trained ML models
    - Computer vision preprocessing (frame extraction)
    - Feature engineering from model outputs
    - Multi-modal score combination
"""

from __future__ import annotations

import time
import cv2
from typing import Any, Dict, List
from .scene_types import SceneDatum, AnalyzerResult

# Iteration 2: YOLOv8 object detection for AI-based scene analysis
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO = None
    YOLO_AVAILABLE = False

# Iteration 2: Reuse PySceneDetect for initial scene cuts + audio analysis
try:
    from .pyscenedetect_analyzer import (
        SCENEDETECT_AVAILABLE,
        run_pyscenedetect,
        extract_audio_energy,
    )
except ImportError:
    SCENEDETECT_AVAILABLE = False
    run_pyscenedetect = None
    extract_audio_energy = None


# Action-related COCO classes that indicate exciting gameplay moments
# YOLO is trained on COCO dataset with 80 classes - we focus on action indicators
ACTION_CLASSES = {
    0: "person",      # players, characters
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
    # Note: COCO doesn't have "gun" or "explosion" - those would need custom training
    # For demo purposes, high person + vehicle counts indicate action
}


def extract_keyframes(filepath: str, start_s: float, end_s: float, num_frames: int = 3) -> List[Any]:
    """
    Extract keyframes from a video segment for YOLO analysis.
    
    Args:
        filepath: path to video file
        start_s: scene start time in seconds
        end_s: scene end time in seconds
        num_frames: number of evenly-spaced frames to extract (default 3)
    
    Returns:
        List of numpy arrays (BGR format) representing frames
    """
    frames = []
    
    try:
        cap = cv2.VideoCapture(filepath)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        
        # Calculate frame positions (start, middle, end)
        duration_s = end_s - start_s
        if duration_s < 0.1:
            cap.release()
            return []
        
        # Evenly space frames across the scene
        time_points = [start_s + (duration_s * i / (num_frames - 1)) for i in range(num_frames)]
        
        for t in time_points:
            frame_num = int(t * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            
            if ret and frame is not None:
                frames.append(frame)
        
        cap.release()
        
    except Exception as e:
        print(f"[Keyframe Extraction Warning] Scene {start_s:.1f}-{end_s:.1f}s: {e}")
    
    return frames


def run_yolo_on_frames(model: Any, frames: List[Any]) -> float:
    """
    Run YOLO inference on extracted frames and count action-related detections.
    
    Args:
        model: loaded YOLO model instance
        frames: list of frame images (numpy arrays)
    
    Returns:
        Normalized detection score (0.0-1.0) where higher = more action
    """
    if not frames:
        return 0.0
    
    total_detections = 0
    
    try:
        for frame in frames:
            # Run YOLO inference (conf=0.25 is default confidence threshold)
            results = model(frame, verbose=False, conf=0.25)
            
            # Count detections of action-related classes
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    cls_id = int(box.cls[0])
                    if cls_id in ACTION_CLASSES:
                        total_detections += 1
        
        # Normalize: typical action scenes have 5-20 detections across 3 frames
        # Cap at 20 and normalize to 0.0-1.0
        normalized = min(float(total_detections), 20.0) / 20.0
        
        return float(round(normalized, 4))
        
    except Exception as e:
        print(f"[YOLO Inference Warning] {e}")
        return 0.0


def compute_ai_highlight_score(
    duration_s: float,
    audio_energy: float,
    ai_detections: float,
) -> float:
    """
    Iteration 2: AI-enhanced highlight scoring combining multiple signals.
    
    Ranking priority:
        1. AI object detections (people, vehicles = action)
        2. Audio energy (gunshots, explosions)
        3. Duration (longer scenes = more content)
    
    Weighting:
        - 40% AI detections (primary ML signal)
        - 40% audio energy (secondary audio signal)
        - 20% duration (tertiary length bonus)
    
    Returns:
        float: highlight score 0.0-1.0 (higher = better highlight)
    """
    # Normalize inputs (should already be 0-1, but clamp for safety)
    ai = max(0.0, min(float(ai_detections), 1.0))
    audio = max(0.0, min(float(audio_energy), 1.0))
    
    # Normalize duration: cap at 30s (longer = better)
    dur = max(0.0, float(duration_s))
    dur_norm = min(dur, 30.0) / 30.0
    
    # Combine: prioritize AI + audio, with duration bonus
    score = (0.40 * ai) + (0.40 * audio) + (0.20 * dur_norm)
    
    return float(round(score, 4))


def run_ai_detection(
    filepath: str,
    threshold: float = 27.0,  # PySceneDetect threshold for initial cuts
    fps: float | None = None,
    report=None,
) -> AnalyzerResult:
    """
    AI-powered detection backend using YOLOv8 object detection + audio analysis.
    
    Workflow:
        1. Use PySceneDetect to find initial scene cuts
        2. Extract keyframes from each scene
        3. Run YOLOv8 on keyframes to count action indicators
        4. Extract audio energy for each scene
        5. Combine AI + audio + duration scores
        6. Return ranked scenes
    
    Parameters:
        filepath: path to the video file
        threshold: PySceneDetect threshold for scene cuts
        fps: video FPS (optional, will be detected)
        report: optional callback(dict) for progress updates
    
    Returns:
        AnalyzerResult with AI-enhanced scene rankings
    """
    start_time = time.perf_counter()
    
    # Check dependencies
    if not YOLO_AVAILABLE or YOLO is None:
        raise RuntimeError(
            "YOLOv8 (ultralytics) is not available.\n"
            "Install with: pip install ultralytics opencv-python-headless"
        )
    
    if not SCENEDETECT_AVAILABLE or run_pyscenedetect is None:
        raise RuntimeError("PySceneDetect is not available for AI mode.")
    
    if callable(report):
        report({"phase": "detect", "mode": "ai_start"})
    
    # Step 1: Load YOLO model (nano version for speed)
    print("[AI Detection] Loading YOLOv8n model...")
    try:
        model = YOLO("yolov8n.pt")  # Downloads automatically on first run (~6MB)
    except Exception as e:
        raise RuntimeError(f"Failed to load YOLO model: {e}")
    
    if callable(report):
        report({"phase": "detect", "mode": "ai_model_loaded"})
    
    # Step 2: Run PySceneDetect to find scene cuts
    print("[AI Detection] Running PySceneDetect for scene cuts...")
    pyscene_result = run_pyscenedetect(filepath, threshold, fps, report)
    scenes = pyscene_result.get("scenes", [])
    
    if not scenes:
        print("[AI Detection] No scenes detected by PySceneDetect.")
        elapsed_s = time.perf_counter() - start_time
        return {
            "scenes": [],
            "scene_data": [],
            "summary": {
                "backend": "ai_yolo",
                "threshold": float(threshold),
                "elapsed_s": float(elapsed_s),
                "scene_count": 0,
            },
            "threshold": float(threshold),
            "elapsed_s": float(elapsed_s),
            "backend": "ai_yolo",
        }
    
    if callable(report):
        report({
            "phase": "detect",
            "mode": "ai_analysis_start",
            "total_scenes": len(scenes)
        })
    
    # Step 3: Process each scene with YOLO + audio
    print(f"[AI Detection] Analyzing {len(scenes)} scenes with YOLOv8...")
    
    fps_value = float(fps) if fps else 0.0
    scene_data: List[SceneDatum] = []
    
    for idx, (start_tc, end_tc) in enumerate(scenes, start=0):
        # Convert timecodes to seconds
        try:
            start_s = float(start_tc.get_seconds())
            end_s = float(end_tc.get_seconds())
        except AttributeError:
            start_s = float(start_tc)
            end_s = float(end_tc)
        
        duration_s = max(0.0, end_s - start_s)
        
        # Extract keyframes and run YOLO
        frames = extract_keyframes(filepath, start_s, end_s, num_frames=3)
        ai_detections = run_yolo_on_frames(model, frames)
        
        # Extract audio energy (reuse from pyscenedetect_analyzer)
        audio_energy = 0.0
        if extract_audio_energy is not None:
            audio_energy = extract_audio_energy(filepath, start_s, end_s)
        
        # Legacy motion proxy (kept for dataset compatibility)
        motion_proxy = 1.0 / max(0.1, duration_s)
        
        # Compute AI-enhanced highlight score
        highlight_score = compute_ai_highlight_score(
            duration_s,
            audio_energy,
            ai_detections,
        )
        
        scene_data.append(
            SceneDatum(
                scene_idx=idx,
                start_s=start_s,
                end_s=end_s,
                duration_s=duration_s,
                fps=fps_value,
                threshold=float(threshold),
                source="ai_yolo",
                motion_proxy=motion_proxy,
                highlight_score=highlight_score,
                audio_energy=audio_energy,
                ai_detections=ai_detections,
            )
        )
        
        # Progress update every 5 scenes
        if callable(report):
            report({
                "phase": "detect",
                "mode": "ai_analysis",
                "done": idx + 1,
                "total": len(scenes)
            })
    
    elapsed_s = time.perf_counter() - start_time
    
    if callable(report):
        report({"phase": "detect", "mode": "ai_complete", "elapsed_s": elapsed_s})
    
    print(f"[AI Detection] Complete! Analyzed {len(scene_data)} scenes in {elapsed_s:.2f}s")
    
    # Build result
    summary: Dict[str, Any] = {
        "backend": "ai_yolo",
        "model": "yolov8n",
        "threshold": float(threshold),
        "elapsed_s": float(elapsed_s),
        "video_fps": fps_value,
        "scene_count": len(scene_data),
    }
    
    result: AnalyzerResult = {
        "scenes": scenes,
        "scene_data": scene_data,
        "summary": summary,
        "threshold": float(threshold),
        "elapsed_s": float(elapsed_s),
        "backend": "ai_yolo",
    }
    
    return result