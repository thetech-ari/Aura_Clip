# Aura Clip — Development Report  
**Course:** Project & Portfolio IV  
**Student:** Arianna Miller-Paul  

---

## Project Overview
Aura Clip is a desktop AI-assisted highlight generator for streamers and video editors.  
Its purpose is to **automatically detect scenes**, **let users select the best moments**, and **export clips** without manual timeline scrubbing.  
The project is built with **Python 3.11**, **PyQt 6**, **PySceneDetect**, **MoviePy**, **FFmpeg**, and **YOLOv8**.

---

## Project Status
| Phase | Goal | Status |
|-------|------|--------|
| **Research & Development** | Build a proof-of-concept showing import → detect → export flow with placeholder UI. | COMPLETE |
| **Iteration 1 Build** | Strengthen the prototype into a usable demo with empirical data and improved export naming. | COMPLETE |
| **Iteration 2 Build** | Add AI-powered highlight detection, audio analysis, and modular analyzer architecture. | COMPLETE |
| **Iteration 3 Build** | Usability testing, refinements, and final polish. | IN PROGRESS |

---

## Research & Development Phase 

### Objectives
- Establish project structure and core dependencies.  
- Verify PyQt 6 GUI launches correctly.  
- Implement **Import**, **Detect Scenes**, and **Export Clips** actions end-to-end.  
- Log user interactions and confirm that each feature works on a sample video.  
- Produce a short R&D video explaining design choices.

---

## Iteration 1 Build 

### Objectives
Focus only on **unique user-value features** and **measurable performance**:  
- Maintain the import → detect → select → export pipeline.  
- Add **empirical data** (timings, counts, success metrics).  
- Rename exported clips to reflect the **actual scene numbers** shown in-app.  
- Prevent UI freeze during long operations (threading).  
- Record the **Iteration 1 Showcase Video** proving the complete workflow.

---

## Iteration 2 Build 

### Objectives
Extend detection capabilities with **AI-powered analysis** and prepare for machine learning:  
- **Modular Analyzer Architecture**: Separated PySceneDetect logic into `analyzers/` package for easy extension.  
- **Audio Analysis**: Extract RMS audio energy from scene segments to identify loud/exciting moments (gunshots, explosions, commentary peaks).  
- **AI-Powered Detection**: Integrated YOLOv8 object detection to count action indicators (people, vehicles, weapons) in keyframes.  
- **Highlight Scoring System**: Combined audio energy (60%), duration (40%), and AI detections into a 0.0-1.0 ranking score.  
- **Detection Mode Switching**: Added Manual / PySceneDetect / AI modes via menu bar.  
- **Scene Ranking Toggle**: "Rank Scenes by Score" filter to sort scenes by highlight score (highest first).  
- **Per-Scene CSV Logging**: Expanded `detect_scenes.csv` with `audio_energy` and `ai_detections` columns for ML training datasets.  
- **Automated Testing**: Created `test_analyzers.py` to validate detection pipeline and CSV schema consistency.

### Key Features
- **AI Mode**: Uses pre-trained YOLOv8n model to detect action-related objects in keyframes  
- **Audio Analysis**: Measures sound intensity (RMS) to identify exciting gameplay moments  
- **Smart Ranking**: Combines AI + audio + duration scores to automatically highlight best scenes  
- **Extensible**: Clean analyzer interface makes it easy to add new detection methods  

### Technical Stack
- **PySceneDetect**: Fast content-based scene detection (v0.5 and v0.6 API support)  
- **YOLOv8**: Real-time object detection (COCO dataset: 80 classes)  
- **pydub + ffmpeg**: Audio extraction and RMS energy analysis  
- **OpenCV**: Keyframe extraction for AI inference  
- **MoviePy**: Video metadata probing (duration, FPS, resolution)  

---

## Iteration 3 Build (Current)

### Objectives
Conduct **usability testing** and implement **user-facing refinements**:  
- Perform think-aloud usability tests with 2+ participants.  
- Fix timeout message appearing during successful AI detection.  
- Add in-app glossary for technical terms (Help → Glossary).  
- Add visual feedback for scene selection: counter + Select All/Deselect All buttons.  
- Ensure CSV headers update automatically when new metrics are added.  
- Polish UI/UX based on tester feedback (upcoming).  

### Completed Fixes (Week 3)
1. **Robust Timeout Handling**: AI detection timeout timer is now properly cancelled after successful completion, preventing false "timed out" messages
2. **In-App Glossary**: Help menu now includes technical term definitions (threshold, highlight score, audio energy, etc.) accessible via F1 key
3. **Selection Feedback**: Scene list shows dynamic "X scenes selected" counter with color-coded visual feedback and batch Select All/Deselect All buttons
4. **Dynamic CSV Schema**: Metrics logging now automatically merges new columns into existing CSVs without breaking historical data
5. **README Documentation**: Comprehensive project documentation with installation guides, usage workflows, and technical architecture

---

## Installation

### Requirements
```bash
# Core dependencies
pip install PyQt6 moviepy scenedetect imageio-ffmpeg pydub

# AI mode dependencies (optional but recommended)
pip install ultralytics opencv-python-headless
```

### Quick Start
```bash
# Clone repository
git clone https://github.com/thetech-ari/Aura_Clip.git
cd Aura_Clip

# Run application
python app.py
```

---

## Usage Workflow

1. **Import Video**: File → Import Video (supports MP4, MOV, MKV, AVI)
2. **Choose Detection Mode**: Detection Mode menu → PySceneDetect (fast, 2-5s) or AI (smarter, 2-3min)
3. **Detect Scenes**: Tools → Detect Scenes (wait for progress bar to complete)
4. **Review Scenes**: 
   - Click scenes to preview start point
   - Double-click to play through entire scene
   - Check boxes to mark for export
5. **Rank by Score** (optional): Tools → Rank Scenes by Score (sorts by AI-calculated highlight quality)
6. **Select for Export**:
   - Check individual scenes, or use "Select All" button
   - Selection counter shows "X scenes selected"
7. **Export Clips**: Tools → Export Clips (saves checked scenes to `./exports` folder)

### Keyboard Shortcuts
- **F1**: Open Glossary (technical term definitions)
- **Space**: Play/Pause video preview
- **←/→**: Seek backward/forward 5 seconds

---

## Project Structure
```
Aura_Clip/
├── app.py                     # Main PyQt6 application 
├── config.py                  # Detection mode settings
├── analyzers/                 # Detection backends (modular architecture)
│   ├── __init__.py
│   ├── pyscenedetect_analyzer.py   # Traditional detection + audio
│   ├── ai_experimental.py          # YOLO-based AI detection
│   └── scene_types.py              # Type definitions for metrics
├── run_logs/
│   ├── __init__.py
│   └── metrics.py             # CSV/JSON logging utilities
├── runs/                      # Generated metrics (gitignored)
│   ├── detect_log.csv         # Detection run summaries
│   ├── detect_log.json
│   ├── detect_scenes.csv      # Per-scene training dataset
│   ├── export_log.csv         # Export summaries
│   └── export_log.json
├── scripts/
│   └── export_detection_dataset.py   # Clean dataset for ML training
├── tests/
│   ├── __init__.py
│   └── test_analyzers.py      # Automated regression tests
├── video_samples/             # Test videos (gitignored)
└── exports/                   # Exported clips (gitignored)
```

---

## Metrics & Logging

All detection and export operations are automatically logged to `/runs`:
- **detect_log.csv**: Detection summaries (scenes found, threshold, elapsed time)
- **detect_scenes.csv**: Per-scene metrics (timestamps, audio energy, AI detections, highlight score)
- **export_log.csv**: Export summaries (clips requested, succeeded, failed, elapsed time)

These logs serve as training data for future machine learning models and provide empirical performance data for iterative improvements.

### Sample detect_scenes.csv Schema
| timestamp | file | scene_idx | start_s | end_s | duration_s | fps | threshold | source | motion_proxy | highlight_score | audio_energy | ai_detections |
|-----------|------|-----------|---------|-------|------------|-----|-----------|--------|--------------|----------------|--------------|---------------|
| 2025-01-24... | vs_1.mp4 | 0 | 0.0 | 3.42 | 3.42 | 30.0 | 27.0 | ai_yolo | 0.2924 | 0.7241 | 0.8156 | 0.6500 |

---

## Testing

Run automated tests:
```bash
python -m tests.test_analyzers
```

Tests verify:
- PySceneDetect integration (v0.5 and v0.6 API support)
- CSV schema consistency and dynamic header updates
- Scene detection accuracy on sample video
- Analyzer interface compliance

---

## Known Limitations

- **AI Mode**: Requires YOLOv8 download (~6MB) on first run; inference takes 2-3 minutes for 50+ scenes
- **Audio Analysis**: Requires valid audio stream (silent videos will have 0.0 energy scores)
- **YOLO Classes**: Limited to COCO dataset (80 classes); game-specific actions (explosions, muzzle flashes) would require custom model fine-tuning
- **Memory**: Large videos (>2GB) may cause slowdowns during preview playback

---

## Future Enhancements (Iteration 4+)

- **Custom YOLO Training**: Fine-tune model on game-specific actions (explosions, weapon muzzle flashes, special effects)
- **Frame-Level Analysis**: Extend AI to every frame instead of just keyframes (slower but more accurate)
- **Multi-Modal Fusion**: Add brightness/contrast analysis and optical flow to improve highlight scoring
- **Export Presets**: Add quality/format presets (720p, 1080p, 4K, H.265 HEVC encoding)
- **Batch Processing**: Process multiple videos in sequence with progress tracking
- **Cloud Export**: Direct upload to YouTube, Twitch, or cloud storage
- **Scene Transitions**: Detect and categorize fade-in/fade-out vs hard cuts vs dissolves

---

## Development Notes

### Week 1 (R&D + Iteration 1)
- Established PyQt6 + PySceneDetect + MoviePy + FFmpeg integration
- Implemented basic user flow: import → detect → select → export
- Added threading to prevent UI freeze during long operations
- Created empirical metrics logging system

### Week 2 (Iteration 2)
- Built modular analyzer architecture for extensibility
- Integrated YOLOv8 for AI-powered object detection
- Added audio analysis (RMS energy extraction)
- Designed highlight scoring algorithm (audio + AI + duration)
- Expanded CSV logging schema for ML training datasets
- Created automated test suite

### Week 3 (Iteration 3 - In Progress)
- Fixed timeout handling bug in AI detection mode
- Added in-app glossary for user clarity
- Implemented visual selection feedback (counter + batch buttons)
- Ensured backward-compatible CSV schema updates
- Conducting usability testing (2+ participants, think-aloud protocol)

---

## License
Educational project for Full Sail University - Project & Portfolio IV course.  
Not licensed for commercial use.

---

## Contact
**Arianna Miller-Paul**  
Full Sail University - Computer Science BS  
GitHub: [@thetech-ari](https://github.com/thetech-ari)