"""
Aura Clip - PP4 Project (Full Sail University)
-------------------------
Week-1:

    R&D Build - Foundational Prototype
        - Established end-to-end technical stack:
            - UI / UX: PyQt6 window with menus, status bar, and video preview
            - Detection: PySceneDetect (v0.6+ and legacy v0.5 API support)
            - Metadata Probe: MoviePy (VideoFileClip) for duration / fps / size
            - Export: FFmpeg (imageio-ffmpeg binary via subprocess calls)
        - Implemented basic user flow (Import > Detect > Select > Export)
        - Verified media loading and preview playback with seek and transport controls
        - Proved multi-library integration (MoviePy + PySceneDetect + FFmpeg)

    Iteration 1 - Functional and UX Expansion
        - Added Guardrails  - validated input, clamped timestamps, ffmpeg sanity check
        - Added Threading  - detect / export now run on QThreads with Worker class
        - Added Progress UI  - indeterminate bar for detect, determinate bar for export
        - Added Metrics  - console summary + /run logging (JSON and CSV)
        - Added Polish  - status messages with timeouts, short dialogs, presenter-ready UX
        - Ensured full guarded flow (no UI freeze or unhandled errors)

Week 2:

    Iteration 2:
        - Signal architecture maturity with modular analyzers and richer metrics output
        - Lay groundwork for machine-learning-based highlight detection(optical flow / brightness / audio peaks)
        - Extend per-scene detection metrics and CSV logging
        - Modularize PySceneDetect logic for analyzer integration
        - Add “Detection Mode” switch (Manual | PySceneDetect | AI-Experimental)
        - Establish dataset export and automated test stubs for model validation

Basic User flow:
    1. Import video > read metadata (MoviePy)
    2. Detect scenes > background thread (PySceneDetect)
    3. Review / select scenes > check boxes in list
    4. Export clips > FFmpeg subprocess on thread > status + logs
    5. Preview controls > Play/Pause, Seek ±5 s, Jump to scene (start/double-click)
"""

# -------- Aura Clip - Base Application Window -------

# Third-party libraries & Qt widgets used to build the UI
# PyQt6 drives the desktop UI to create the base window.
from PyQt6.QtCore import Qt, QUrl, QThread, QObject, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QStatusBar, QMenuBar,
    QFileDialog, QMessageBox, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QSlider, QStyle,
    QProgressBar, QScrollArea, QLineEdit, QFrame
)
from PyQt6.QtGui import QAction
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from config import settings, DetectionMode
from analyzers import SCENEDETECT_AVAILABLE, run_pyscenedetect, run_ai_detection
from run_logs.metrics import append_summary, append_rows

# --- Standard Library ---
import sys, os, subprocess, time, json, csv, datetime

class Worker(QObject):
    """
    Generic worker that runs a callable in a background thread.
    Emits back to UI: 
        - progress(object): optional progress payloads from the job
        - finished(object): result dict or an Exception
    """
    finished = pyqtSignal(object)
    progress = pyqtSignal(object)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            # If the target function accepts a 'report' kwarg, provide a signal-emitting callable.  
            if hasattr(self._fn, "__code__") and "report" in self._fn.__code__.co_varnames:   
                result = self._fn(*self._args, report=self.progress.emit, **self._kwargs)      
            else:                                                                            
                result = self._fn(*self._args, **self._kwargs)                               
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit(e)

# This supports EITHER the modern v0.6+ API OR the legacy v0.5 API 
try:
    # v0.6+ API
    from scenedetect import SceneManager, open_video        
    from scenedetect.detectors import ContentDetector      
    SCENEDETECT_AVAILABLE = True                           
    SCENEDETECT_API = "v0.6+"                              
except Exception:
    try:
        # v0.5.x API
        from scenedetect import VideoManager, SceneManager  
        from scenedetect.detectors import ContentDetector  
        SCENEDETECT_AVAILABLE = True                        
        SCENEDETECT_API = "v0.5"                            
    except Exception:
        pass    # remains unavailable; UI will show a friendly message      

# Lightweight MoviePy import for read only metadata; 
# (VideoFileClip is only needed to read duration/fps/size, no writing)
try:
    from moviepy.video.io.VideoFileClip import VideoFileClip              
    MOVIEPY_AVAILABLE = True 
except Exception:
    VideoFileClip = None                          
    MOVIEPY_AVAILABLE = False      

# --- FFmpeg Setup (for exporting clips) ---
# ensures ffmpeg binary is known to MoviePy/imageio tools so they use the same executable
import imageio_ffmpeg
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_EXE

def _export_job(run_ffmpeg_slice, custom_names, src_file, selections, duration, export_dir, report=None):
    """
        Background job for exporting selected scenes via ffmpeg.
        Runs outside the GUI thread via QtThread to avoid UI freezes.

        Parameters:
            run_ffmpeg_slice: function(src, start_s, end_s, dst) -> (ok, stderr)
            scene_count: total count of items currently in the scene list (for name padding)
            basename: base output name derived from the loaded file
            src_file: original video path
            selections: list[(idx, start_s, end_s)] — clamped selections to export
            duration: media duration in seconds (already probed)
            export_dir: destination folder
        
        Returns:
            dict with:
                - requested: number of segments we attempted to export
                - ok: number of successful exports
                - failed: number of failed exports
                - errors: list of (scene_num, start_s, end_s, stderr_text) for failures
                - elapsed_s: total wall time in seconds
                - export_dir: echo back the directory for UI display
    """

    start_wall = time.perf_counter()    # start timing

    exported_ok = 0     # count successes
    errors = []         # collect details for failures

    # custom_names is a list of user-provided filenames (one per selection)
    total = len(selections)
    done = 0
    if callable(report):
        report({"phase": "export", "done": done, "total": total})

    # Export each selected scene using user-provided names
    for i, (idx, start_s, end_s) in enumerate(selections):
        scene_num = idx + 1

        # Use custom name provided by user (already validated and sanitized)
        filename = f"{custom_names[i]}.mp4"
        out_path = os.path.join(export_dir, filename)

        # Run ffmpeg slice; returns (ok, stderr)
        ok, err = run_ffmpeg_slice(src_file, start_s, end_s, out_path)
        if ok:
            exported_ok += 1
        else:
            # Keep enough context to show useful diagnostics to the user
            errors.append((scene_num, start_s, end_s, err))
        done += 1                                                          
        if callable(report):                                               
            report({"phase": "export", "done": done, "total": total, "last_ok": bool(ok), "scene": scene_num})

    elapsed_s = time.perf_counter() - start_wall        # total export time

    return {
        "requested": len(selections),
        "ok": exported_ok,
        "failed": len(errors),
        "errors": errors,
        "elapsed_s": elapsed_s,
        "export_dir": export_dir,
    }

# ===== Iteration 4 - Commit 3: Export Naming Dialog =====
# Custom dialog for naming each exported clip individually
class ExportNamingDialog(QWidget):
    """
    Dialog for naming each selected scene before export.
    Shows scene previews and allows user to customize each filename.
    """
    def __init__(self, parent, scene_selections, default_basename):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Name Export Clips")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.scene_selections = scene_selections  # List of (idx, start_s, end_s)
        self.default_basename = default_basename
        self.name_inputs = []  # Store QLineEdit widgets
        self.result_names = None  # Will store final names if user accepts
        
        self.setup_ui()
        
    def setup_ui(self):
        """Build the naming dialog UI."""
        
        layout = QVBoxLayout(self)
        instructions = QLabel(
            f"You have selected {len(self.scene_selections)} scene(s) to export.\n"
            "Customize the filename for each clip below:"
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        # Scrollable area for clip names
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(400)
        scroll.setMinimumWidth(500)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        # Create name input for each selected scene
        for i, (idx, start_s, end_s) in enumerate(self.scene_selections, start=1):
            scene_num = idx + 1
            
            # Scene info label
            info_label = QLabel(
                f"Scene {scene_num}: {self._format_time(start_s)} → {self._format_time(end_s)}"
            )
            scroll_layout.addWidget(info_label)
            
            # Default filename suggestion
            default_name = f"{self.default_basename}_scene_{scene_num:02d}"
            
            # Name input field
            name_input = QLineEdit(self)
            name_input.setText(default_name)
            name_input.setPlaceholderText("Enter filename (without .mp4 extension)")
            self.name_inputs.append(name_input)
            scroll_layout.addWidget(name_input)
            
            # Add spacing between entries
            if i < len(self.scene_selections):
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFrameShadow(QFrame.Shadow.Sunken)
                scroll_layout.addWidget(line)
        
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        # Button row (Cancel / Export)
        button_row = QWidget(self)
        button_layout = QHBoxLayout(button_row)
        
        cancel_btn = QPushButton("Cancel")
        export_btn = QPushButton("Export All")
        
        cancel_btn.clicked.connect(self.reject)
        export_btn.clicked.connect(self.accept)
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(export_btn)
        
        layout.addWidget(button_row)
    
    def _format_time(self, seconds: float) -> str:
        """Format seconds as HH:MM:SS."""
        s = max(0, int(round(float(seconds))))
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:02d}"
    
    def accept(self):
        """Validate and store user-provided names."""
        # Collect all names
        names = []
        for input_widget in self.name_inputs:
            name = input_widget.text().strip()
            
            # Validate: not empty and no invalid characters
            if not name:
                QMessageBox.warning(
                    self,
                    "Invalid Filename",
                    "All clips must have a filename. Please fill in all fields."
                )
                return
            
            # Remove any file extension if user added one
            if name.lower().endswith('.mp4'):
                name = name[:-4]
            
            # Sanitize filename (remove invalid characters)
            invalid_chars = '<>:"/\\|?*'
            for char in invalid_chars:
                name = name.replace(char, '_')
            
            names.append(name)
        
        # Check for duplicates
        if len(names) != len(set(names)):
            QMessageBox.warning(
                self,
                "Duplicate Filenames",
                "Each clip must have a unique filename. Please check for duplicates."
            )
            return
        
        self.result_names = names
        self.close()
    
    def reject(self):
        """User cancelled the export."""
        self.result_names = None
        self.close()

# ----------------------------------------------- M A I N   W I N D O W ----------------------------------------
class AuraClipApp(QMainWindow):
    
    def __init__(self):
        super().__init__()

        # --- Window chrome & state ---
        self.setWindowTitle("Aura Clip")
        self.setGeometry(200, 200, 900, 600)

        # Track the currently selected file path + detected scenes in memory
        self.current_file: str | None = None
        self.current_scenes: list | None = None

        # cache of the ffmpeg check
        self._ffmpeg_ok_result = None    

        # cached duration for UI-thread safety
        self._media_duration = 0.0  
        # cached FPS for analyzer metrics
        self._media_fps = 0.0  

        # --- Main content area ---
        """ 
            [Left-Top] Video preview panel + file metadata 
            [Left-Bottom] Transport Bar (video playback buttons and slider)
            [Right] Checkable scene list (one row per detected segment) 
        """
        # preview + info + scenes
        self.container = QWidget(self)
        self.layout = QHBoxLayout(self.container)
        self.setCentralWidget(self.container)           

        # Left: video preview (top) + info (middle) + transport (bottom)
        left = QWidget(self.container)
        from PyQt6.QtWidgets import QVBoxLayout, QGridLayout
        left_v = QVBoxLayout(left)
        left_v.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(left, stretch=1)

        # Video preview
        self.video_widget = QVideoWidget(left)
        self.video_widget.setMinimumSize(480, 270)
        left_v.addWidget(self.video_widget, stretch=1)

        # File info
        self.info_label = QLabel("No file loaded.", left)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        left_v.addWidget(self.info_label)

        # Transport bar (play/pause + seek + skip)
        transport = QWidget(left)
        t = QHBoxLayout(transport)
        t.setContentsMargins(0, 0, 0, 0)

        self.btn_back = QPushButton("<<  5s")
        self.btn_play = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), "")
        self.btn_fwd  = QPushButton("5s  >>")
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 1000)  # map 0..1000 to 0..duration

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(110)  # keeps UI from jumping as time changes
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Track "stop at scene end" behavior
        self._scene_stop_ms = None

        #scriber setup
        t.addWidget(self.btn_back)
        t.addWidget(self.btn_play)
        t.addWidget(self.btn_fwd)
        t.addWidget(self.seek, stretch=1)
        t.addWidget(self.time_label)
        left_v.addWidget(transport)

        # This makes the detection workflow more visible and intuitive
        # Button is disabled until a video is loaded
        self.detect_btn = QPushButton("Detect Scenes", left)
        self.detect_btn.setMinimumHeight(36)  
        self.detect_btn.clicked.connect(self.detect_scenes)
        self.detect_btn.setEnabled(False)  # Disabled until file loaded
        left_v.addWidget(self.detect_btn)

        # Usability improvement: Selection counter label + Select All/Deselect All buttons
        
        # Right panel: Scene list with selection controls
        right_panel = QWidget(self.container)
        right_v = QVBoxLayout(right_panel)
        right_v.setContentsMargins(0, 0, 0, 0)
        
        # Selection counter label: Shows "X scenes selected"
        self.selection_label = QLabel("0 scenes selected", right_panel)
        self.selection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selection_label.setStyleSheet(
            "font-weight: bold; "
            "padding: 8px; "
            "background-color: #e8f4f8; "
            "border: 1px solid #b8d4e0; "
            "border-radius: 4px; "
            "color: #2c5f7c;"
        )
        right_v.addWidget(self.selection_label)
        
        # Batch selection buttons: Select All / Deselect All
        selection_buttons = QWidget(right_panel)
        selection_btn_layout = QHBoxLayout(selection_buttons)
        selection_btn_layout.setContentsMargins(0, 5, 0, 5)
        
        self.btn_select_all = QPushButton("Select All", selection_buttons)
        self.btn_deselect_all = QPushButton("Deselect All", selection_buttons)
        
        self.btn_select_all.clicked.connect(self._select_all_scenes)
        self.btn_deselect_all.clicked.connect(self._deselect_all_scenes)
        
        # Style buttons for better visibility
        self.btn_select_all.setStyleSheet("padding: 6px;")
        self.btn_deselect_all.setStyleSheet("padding: 6px;")
        
        selection_btn_layout.addWidget(self.btn_select_all)
        selection_btn_layout.addWidget(self.btn_deselect_all)
        right_v.addWidget(selection_buttons)

        # Rank Scenes toggle (moved from Tools menu)
        self.rank_toggle_btn = QPushButton("Rank Scenes by Score")
        self.rank_toggle_btn.setCheckable(True)
        self.rank_toggle_btn.setChecked(False)
        self.rank_toggle_btn.clicked.connect(self._toggle_rank_from_button)
        right_v.addWidget(self.rank_toggle_btn)

        # Create the actual QListWidget for displaying detected scenes
        self.scene_list = QListWidget(right_panel)
        right_v.addWidget(self.scene_list, stretch=1)  
        right_panel.setFixedWidth(350)
        self.layout.addWidget(right_panel)
        
        # clicking a scene seeks to its start; double-click plays from there
        self.scene_list.itemClicked.connect(self._jump_to_scene_start)
        self.scene_list.itemDoubleClicked.connect(self._play_from_scene_start)
        self.scene_list.itemChanged.connect(lambda: self._update_selection_counter())
        
        # Update selection counter whenever checkboxes change
        self.scene_list.itemChanged.connect(self._update_selection_count)           

        # --- Status Bar ---
        # Displays messages to the user, such as file loaded or task complete.
        self.status = QStatusBar(self)
        self.setStatusBar(self.status)

        # Progress bar lives in the status bar; hidden until work runs.                  
        self.progress = QProgressBar(self)                                               
        self.progress.setVisible(False)                                                 
        self.progress.setTextVisible(False)                                             
        self.status.addPermanentWidget(self.progress, 0) 

        # Detection Mode Label
        self.mode_label = QLabel(self)
        self.statusBar().addPermanentWidget(self.mode_label)
        self.update_mode_label()  # show current detection mode at startup

        # --- Menu Bar ---
        # The menu bar gives the user structured access to actions.
        menubar = QMenuBar(self)
        self.setMenuBar(menubar)

        # File Menu (Import + Exit buttons)
        file_menu = menubar.addMenu("File")

        import_action = file_menu.addAction("Import Video")
        import_action.triggered.connect(self.import_video)

        # Export Video action redirects to export_clips (same as button)
        self.export_action_menu = file_menu.addAction("Export Video")
        self.export_action_menu.triggered.connect(self.export_clips)
        self.export_action_menu.setEnabled(False)    # Disabled at startup until a file is loaded

        file_menu.addSeparator()

        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

        # Detection Mode Menu 
        mode_menu = menubar.addMenu("Scene Detection Mode")

        manual_action = mode_menu.addAction("Manual")
        pysd_action = mode_menu.addAction("Default")
        ai_action = mode_menu.addAction("AI")

        manual_action.triggered.connect(lambda: self.set_mode(DetectionMode.MANUAL))
        pysd_action.triggered.connect(lambda: self.set_mode(DetectionMode.PYSDETECT))
        ai_action.triggered.connect(lambda: self.set_mode(DetectionMode.AI_EXPERIMENTAL))
        
        # Settings Menu
        settings_menu = menubar.addMenu("Settings")
        settings_action = settings_menu.addAction("Preferences")
        settings_action.triggered.connect(self.open_settings)

        settings_menu.addSeparator()
        
        about_action = settings_menu.addAction("About Aura Clip")
        about_action.triggered.connect(self.show_about)

        # Iteration 4: Dedicated menu for technical terms and workflow tips
        # Helps users understand threshold, highlight score, audio energy, etc.
        glossary_menu = menubar.addMenu("Glossary")

        view_glossary_action = glossary_menu.addAction("Open Glossary")
        view_glossary_action.triggered.connect(self.show_glossary)
    
        self.top_highlights_only = False
        self.top_highlights_action = QAction("Rank Scenes by Score", self)
        self.top_highlights_action.setCheckable(True)
        self.top_highlights_action.setChecked(False)
        self.top_highlights_action.triggered.connect(self._toggle_top_highlights)
        
        print("Aura Clip initialized successfully.")

        #--------------------------------------------------------------

        # Media player setup
        # Media is set to the preview; audio routed via QAudioOutput + 
        # keep our own cached duration in milliseconds to map the seek slider.
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)

        # UI wiring
        self.btn_play.clicked.connect(self._toggle_play_pause)
        self.btn_back.clicked.connect(lambda: self._nudge(-5.0))
        self.btn_fwd.clicked.connect(lambda: self._nudge(+5.0))
        self.seek.sliderMoved.connect(self._seek_to_ratio)

        # keep slider in sync with playback
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)

        self._media_duration_ms = 0

        self.status.showMessage("Idle — > Ready to import a video!", 4000)

    # Helper to enable/disable both actions at once
    def set_actions_enabled(self, loaded: bool) -> None:
        self.detect_btn.setEnabled(loaded)  
        self.export_action_menu.setEnabled(loaded)

    # switching detection modes
    def update_mode_label(self):
        if settings.detection_mode is DetectionMode.PYSDETECT:
            text = "Detection Mode: Default"
        elif settings.detection_mode is DetectionMode.AI_EXPERIMENTAL:
            text = "Detection Mode: AI"
        else:
            text = "Detection Mode: Manual"
        self.mode_label.setText(text)  

    def set_mode(self, mode):
        settings.detection_mode = mode
        self.update_mode_label()
        self.statusBar().showMessage(f"Switched to {self.mode_label.text()}", 3000)

    def get_media_info(self, file_path: str) -> dict:  
        """
        Read lightweight metadata from a video file.

        Returns:
        dict with:
            - duration (float seconds)
            - fps (float)
            - width (int)
            - height (int)

        Notes:
        - Uses MoviePy's VideoFileClip in a context manager with audio disabled
          to avoid opening an audio device. Will close immediately after reading.
        - If MoviePy isn't available or probing fails, will return zeros and show
          an error to avoid a crash.
        """

        if not MOVIEPY_AVAILABLE:  
            return {"duration": 0.0, "fps": 0.0, "width": 0, "height": 0}

        if not os.path.exists(file_path):                    
            QMessageBox.critical(self, "Media Error", "File does not exist.")  
            return {"duration": 0.0, "fps": 0.0, "width": 0, "height": 0} 

        try:
            with VideoFileClip(file_path, audio=False) as clip:
                duration = float(clip.duration) if clip.duration else 0.0
                fps = float(clip.fps) if clip.fps else 0.0
                w, h = clip.size if clip.size else (0, 0)
            return {"duration": duration, "fps": fps, "width": w, "height": h}
        except Exception as e:
            # show an error message and return empty info
            QMessageBox.critical(
                self, 
                "Media Error", 
                f"Could not read media info:\n{e}"
                )
            return {"duration": 0.0, "fps": 0.0, "width": 0, "height": 0}    

    # --- ACTIONS ---

    def import_video(self):
        # Open a file dialog to select a local video file.
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", "Video Files (*.mp4 *.mov *.mkv *.avi)"
        )
        if not file_path:  # early-return on cancel
            self.status.showMessage("Import canceled.", 3000)  
            self.set_actions_enabled(False)                    
            return
        
        # Record file and read media info
        self.current_file = file_path  
        info = self.get_media_info(self.current_file)
        self._media_duration = float(info.get("duration", 0.0)) if info else 0.0
        self._media_fps = float(info.get("fps", 0.0)) if info else 0.0

        # load into player
        self.player.setSource(QUrl.fromLocalFile(self.current_file))
        self.player.pause()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))  

        # Format a user-friendly display, rounding values for readability
        duration_s = round(info["duration"], 2)
        duration_ts = self.format_time(duration_s)  # HH:MM:SS  
        fps = round(info["fps"], 2)              
        w, h = info["width"], info["height"]     

        # Update UI with file + metadata
        basename = os.path.basename(file_path)  
        self.info_label.setText(                    
            f"Loaded file:\n{basename}\n\n"
            f"Duration: {duration_ts}s\n"
            f"FPS: {fps}\n"
            f"Resolution: {w} x {h}"
        )

        # Show a message on the right
        self.status.showMessage(f"Imported {basename}. Use Tools > Detect Scenes.", 6000)  

        # enable Detect/Export now that a file is loaded
        self.set_actions_enabled(True)

    def _to_seconds(self, tc) -> float:
        # PySceneDetect timecodes (v0.5/v0.6) or floats to seconds
        try:
            return float(tc.get_seconds())
        except Exception:
            try:
                # v0.6 VideoTimecode exposes get_seconds()
                return float(tc)  # already numeric
            except Exception:
                return 0.0

    def format_time(self, seconds: float) -> str:
        """
            Convert a float number of seconds to a human-friendly timestamp.
            Returns HH:MM:SS (zero-padded), e.g., 00:03:07 for 187s.
                - Clamps negatives to 0.
            This is for *positions* in the media (scene starts/ends), not performance timing.
        """
        try:
            s = max(0, int(round(float(seconds))))
        except Exception: 
            s = 0

        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60

        return f"{h:02d}:{m:02d}:{sec:02d}"
    
    # --- Safety Net Helpers ----------------------------------------------------
    def _ffmpeg_ok(self) -> bool:
        """
        One-time/lazy check that ffmpeg is callable. Result is cached.
        Prevents user from hitting Export only to learn ffmpeg isn't available. 
        """  
        # Cache result so we don’t spawn subprocesses repeatedly      
        if getattr(self, "_ffmpeg_ok_result", None) is not None:       
            return self._ffmpeg_ok_result                                

        ffmpeg_bin = os.environ.get("IMAGEIO_FFMPEG_EXE") or "ffmpeg"   
        try:                                                            
            probe = subprocess.run(                                     
                [ffmpeg_bin, "-version"], capture_output=True, text=True
            )                                                           
            self._ffmpeg_ok_result = (probe.returncode == 0)            
        except Exception:                                               
            self._ffmpeg_ok_result = False                              

        if not self._ffmpeg_ok_result:                                  
            QMessageBox.critical(                                       
                self, "Missing ffmpeg",                                 
                "ffmpeg is not runnable.\n\n"                           
                "Fix: reinstall imageio-ffmpeg (pip install imageio-ffmpeg)\n"
                "or install system ffmpeg and relaunch Aura Clip."      
            )                                                           
        return self._ffmpeg_ok_result                                   

    def _clamp_range(self, start_s: float, end_s: float, duration: float) -> tuple[float, float]:
        """
        Clamp [start_s, end_s] into [0, duration]. Returns (s, e) with s <= e.
        """  
        s = max(0.0, min(float(start_s), float(duration)))               
        e = max(0.0, min(float(end_s),   float(duration)))               
        if e < s:                                                        
            s, e = e, s  # swap just in case user data flipped them     
        return s, e                                                      

    def _collect_valid_selections(self, duration: float) -> list[tuple[int, float, float]]:
        """
        Read CHECKED rows, clamp to duration, and filter out invalid/too-short ranges.
        Returns list of (idx, start_s, end_s). Shows friendly early-exit messages when empty.
        """  
        if self.scene_list.count() == 0:                                 
            QMessageBox.information(self, "Export Clips", "No scenes to select. Run detection first.")
            return []                                                   

        selections: list[tuple[int, float, float]] = []                  
        for idx in range(self.scene_list.count()):                       
            item = self.scene_list.item(idx)                             
            # If the list contains the placeholder row "No scenes detected.", skip it 
            data = item.data(Qt.ItemDataRole.UserRole)                   
            if item.checkState() == Qt.CheckState.Checked and data:      
                start_s, end_s = data                                    
                s, e = self._clamp_range(start_s, end_s, duration)       
                if (e - s) > 0.05:                                       
                    selections.append((idx, s, e))                       

        if not selections:                                              
            QMessageBox.information(                                     
                self, "Export Clips",                                    
                "No valid scenes selected.\n\n"
                "Hint: Check one or more scenes in the list. Very short segments (<0.05s) are ignored."
            )                                                            
            return []                                                    

        return selections  

        # --- Run Logging Helpers ----------------------
    def _log_run(self, kind: str, data: dict):   
        """
            Write detection/export summaries to /runs as JSON + CSV.  
            
            Delegates to run_logs.metrics.append_summary so that logging logic
            can be reused by other modules.
        """   
        try:   
            append_summary(kind, data)   

        except Exception as e:   
            print(f"[LOGGING WARNING] Could not log {kind} run: {e}")                                                 

    # Scene detection implementation
    def detect_scenes(self):
        # Run PySceneDetect and populate the scene list(will support v0.6 and v0.5)
        """
            Run PySceneDetect and populate the scene list while collecting
            empirical performance data (timing + scene counts) without freezing the UI.
            Uses QThread + Worker to run heavy detection off the GUI thread.
        """

        if not self.current_file:
            QMessageBox.information(self, "No File", "Please import a video first.")
            return
                # Decide which detection backend to use based on DetectionMode
        mode = settings.detection_mode

        if mode is DetectionMode.AI_EXPERIMENTAL:
            backend_fn = run_ai_detection
            backend_label = "AI"
        else:
            # For now, MANUAL falls back to PySceneDetect behavior too
            if not SCENEDETECT_AVAILABLE:
                QMessageBox.critical(
                    self,
                    "Missing Library",
                    "PySceneDetect not available.\nInstall with:\n  pip install scenedetect",
                )
                return 

            backend_fn = run_pyscenedetect   # from analyzers.pyscenedetect_analyzer
            backend_label = "PySceneDetect"

        # Immediate user feedback + block re-entrancy while running
        self._progress_busy(f"Detecting scenes using {backend_label}... please wait.")
        self.detect_btn.setEnabled(False)
        self.export_action_menu.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        
        # Console logging for debugging
        print(f"\n{'='*60}")
        print(f"[DETECTION START] Beginning scene detection")
        print(f"  Backend: {backend_label}")
        print(f"  File: {os.path.basename(self.current_file)}")
        print(f"  Duration: {self._media_duration:.2f}s")
        print(f"  FPS: {self._media_fps:.2f}")
        print(f"  Threshold: 27.0")
        print(f"{'='*60}\n")

        # Spin up a one-off worker thread for detection
        self._detect_thread = QThread(self)
        self._detect_worker = Worker(
            backend_fn,
            self.current_file,
            27.0,  # threshold ; currently ignored by AI stub 
            self._media_fps # fps passed into analyzer
        )
        self._detect_worker.moveToThread(self._detect_thread)

        def on_progress(payload):
            # Show detailed progress updates - no timeout tracking needed
            if not isinstance(payload, dict):
                return
                
            phase = payload.get("phase", "")
            mode = payload.get("mode", "")
            
            if phase == "detect":
                # Show what's happening at each stage
                if mode == "start":
                    self.status.showMessage(f"Starting {backend_label} detection...")
                    print(f"[PROGRESS] Starting {backend_label} detection")

                elif mode == "scene_count":
                    # PySceneDetect reports total scene count after detection completes
                    total_scenes = payload.get("total_scenes", 0)
                    if total_scenes > 0:
                        self.status.showMessage(
                            f"Detected {total_scenes} scene(s) - Analyzing highlights..."
                    )
                        
                elif mode == "audio_analysis_start":
                    # Audio analysis phase (can be slow for long videos)
                    total_scenes = payload.get("total_scenes", 0)
                    self.progress.setRange(0, total_scenes)  # Switch to determinate
                    self.progress.setValue(0)
                    self.status.showMessage(
                        f"Analyzing audio for {total_scenes} scene(s)..."
                    )
                
                elif mode == "audio_progress":
                    # Update progress bar during audio analysis
                    done = payload.get("done", 0)
                    total = payload.get("total", 1)
                    self.progress.setValue(done)
                    self.status.showMessage(
                        f"Analyzing audio: scene {done}/{total}..."
                    )
                    
                elif mode == "ai_start":
                    self.status.showMessage("Loading AI models...")
                    print("[PROGRESS] Loading AI models...")
                    
                elif mode == "ai_model_loaded":
                    self.status.showMessage("AI models loaded, finding scene cuts...")
                    print("[PROGRESS] AI models loaded, finding scene cuts...")
                    
                elif mode == "ai_analysis_start":
                    total_scenes = payload.get("total_scenes", 0)
                    self.progress.setRange(0, total_scenes)
                    self.progress.setValue(0)
                    self.status.showMessage(
                        f"Running AI analysis on {total_scenes} scene(s)..."
                    )
                    print(f"[PROGRESS] Analyzing {total_scenes} scenes with AI")
                    
                elif mode == "ai_analysis":
                    done = payload.get("done", 0)
                    total = payload.get("total", 1)
                    self.progress.setValue(done)
                    self.status.showMessage(
                        f"AI analysis: scene {done}/{total}..."
                    )
                    print(f"[PROGRESS] AI analyzing scene {done}/{total}")

                elif mode == "ai_complete":
                    elapsed_s = payload.get("elapsed_s", 0)
                    self.status.showMessage(f"AI detection complete ({elapsed_s:.1f}s)")
                            
                elif mode == "audio_analysis_start":
                    total = payload.get("total_scenes", 0)
                    self.status.showMessage(f"Extracting audio from {total} scenes...")
                    print(f"[PROGRESS] Extracting audio from {total} scenes")
                    
                elif mode == "end":
                    elapsed = payload.get("elapsed_s", 0.0)
                    self.status.showMessage(f"Detection complete in {elapsed:.1f}s")
                    print(f"[PROGRESS] Detection complete in {elapsed:.1f}s")
        
        self._detect_worker.progress.connect(on_progress)
        
        # Start the worker when thread starts (queued, non-blocking)             
        self._detect_thread.started.connect(self._detect_worker.run, Qt.ConnectionType.QueuedConnection)  
        
        def on_finished(payload):
            # Detection completed - no timeout cleanup needed
            self._progress_done("Detection Complete.")
            self.status.showMessage("Detection Done! Review scenes, then Export", 5000)
            QApplication.restoreOverrideCursor()
            self.detect_btn.setEnabled(True)
            self.export_action_menu.setEnabled(bool(self.current_file))

            # --- Update UI list (uses cached duration to avoid slow probe)
            if isinstance(payload, Exception):
                QMessageBox.critical(
                    self, 
                    "Detection Error", 
                    "Scene detection failed. Check console for details."
                    )
                return

            scenes = payload.get("scenes", [])  
            threshold = payload.get("threshold", 27.0)
            elapsed_ms = (payload.get("elapsed_s", 0.0) or 0.0) * 1000.0   # milliseconds
           
            # structured scene metrics from analyzer
            scene_data = payload.get("scene_data", [])

            self.current_scene_data = scene_data

            # Map scene_idx -> highlight_score for UI labels
            score_by_idx = {}
            try:
                for sd in scene_data:
                    score_by_idx[int(sd.get("scene_idx", 0))] = float(sd.get("highlight_score", 0.0))
            except Exception:
                score_by_idx = {}

            self.current_scenes = scenes
            self.scene_list.clear()

            if not scenes:
                self.scene_list.addItem(QListWidgetItem("No scenes detected."))
                self.status.showMessage("No scenes detected.", 4000)
                return
            
            # Grab media duration to keep times within range                   
            duration = float(self._media_duration) or 0.0 

            # --- Iteration 2: Use _rebuild_scene_list() for consistent filtering ---
            # This ensures the "Rank Scenes" filter toggle works properly
            self._rebuild_scene_list()

            # --- Metrics output 
            msg = f"Detected {len(scenes)} scene(s) | Threshold={threshold} | {elapsed_ms:.1f} ms"
            print(msg)
            self.status.showMessage(msg, 6000)  # shows metrics

            # --- Log detection summary for analytics ---  
            self._log_run("detect", {  
                "file": os.path.basename(self.current_file),  
                "operation": "detect",  
                "scenes_found": len(scenes),  
                "threshold": threshold,  
                "elapsed_s": round(payload.get("elapsed_s", 0.0), 3),  
            })  

            # --- per-scene CSV logging for AI / analysis ---
            try:
                import datetime

                ts = datetime.datetime.now().isoformat()
                filename = os.path.basename(self.current_file)

                rows = []
                for sd in scene_data:
                    # Each sd should match SceneDatum from scene_types.py
                    row = {
                        "timestamp": ts,
                        "file": filename,
                        "scene_idx": sd.get("scene_idx", -1),
                        "start_s": sd.get("start_s", 0.0),
                        "end_s": sd.get("end_s", 0.0),
                        "duration_s": sd.get("duration_s", 0.0),
                        "fps": sd.get("fps", 0.0),
                        "threshold": sd.get("threshold", threshold),
                        "source": sd.get("source", "unknown"),
                        "motion_proxy": sd.get("motion_proxy", 0.0),
                        "highlight_score": sd.get("highlight_score", 0.0),
                        "audio_energy": sd.get("audio_energy", 0.0),
                        "ai_detections": sd.get("ai_detections", 0.0),
                    }
                    rows.append(row)

                append_rows("detect_scenes", rows)
            except Exception as e:
                print(f"[LOGGING WARNING] Could not log per-scene metrics: {e}")

        # Wire signals: when the thread starts, run the worker; when done, handle result
        self._detect_worker.finished.connect(on_finished, Qt.ConnectionType.QueuedConnection)  
        self._detect_worker.finished.connect(self._detect_thread.quit)
        self._detect_worker.finished.connect(self._detect_worker.deleteLater)  
        self._detect_thread.finished.connect(self._detect_thread.deleteLater)  
        
        print(f"[DETECTION] Starting {backend_label} detection (no timeout)")

        self._detect_thread.start()

    

    # helper to call ffmpeg directly and bubble up stderr if it fails
    def _run_ffmpeg_slice(self, src: str, start_s: float, end_s: float, dst: str) -> tuple[bool, str]:
        """
        Uses the verified ffmpeg binary to cut [start_s, end_s] into dst.
        Returns (ok, stderr_text).
        """
        # Build the command: seek BEFORE input for speed, then -to absolute time.
        ffmpeg_bin = os.environ.get("IMAGEIO_FFMPEG_EXE") or "ffmpeg"
        cmd = [
            ffmpeg_bin,
            "-y",                         # overwrite without asking
            "-loglevel", "error",         # only errors on stderr
            "-ss", f"{start_s:.3f}",
            "-to", f"{end_s:.3f}",
            "-i", src,
            "-c:v", "libx264",
            "-c:a", "aac",
            dst,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            ok = (proc.returncode == 0) and os.path.exists(dst) and os.path.getsize(dst) > 0
            return ok, (proc.stderr or "").strip()
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    # --- Transport helpers ---
    # Play/pause the preview and keep the button icon in sync
    def _toggle_play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        else:
            self.player.play()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

    # Step the playhead by ±N seconds, clamped to [0, duration]
    def _nudge(self, delta_sec: float):
        pos = max(0, min(self.player.position() + int(delta_sec * 1000), self._media_duration_ms))
        self.player.setPosition(pos)

    # Map slider range and seek
    def _seek_to_ratio(self, val: int):
        # slider 0..1000 > position 0..duration
        if self._media_duration_ms > 0:
            target = int((val / 1000.0) * self._media_duration_ms)
            self.player.setPosition(target)

    # Cache media duration (ms) for consistent slider math
    def _on_duration(self, dur_ms: int):
        self._media_duration_ms = max(0, dur_ms)
        # Update time label (keep current position, refresh total)
        self._update_time_label(self.player.position())

    # Update slider to reflect current playback position (no feedback loop)
    def _on_position(self, pos_ms: int):
        # keep slider synced with playback
        if self._media_duration_ms > 0:
            ratio = pos_ms / self._media_duration_ms
            self.seek.blockSignals(True)
            self.seek.setValue(int(ratio * 1000))
            self.seek.blockSignals(False)

        # Update time label every tick
        self._update_time_label(pos_ms)

        # scene end-stop is set, pause when we pass it
        if self._scene_stop_ms is not None and pos_ms >= self._scene_stop_ms:
            self.player.pause()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self.status.showMessage("Reached scene end (auto-paused).", 2500)
            self._scene_stop_ms = None

    def _update_time_label(self, pos_ms: int) -> None:
        """
        Shows playback time as: MM:SS / MM:SS (or HH:MM:SS when long).
        Uses your existing format_time(seconds) helper.
        """
        pos_s = max(0.0, float(pos_ms) / 1000.0)
        dur_s = max(0.0, float(self._media_duration_ms) / 1000.0)
        self.time_label.setText(f"{self.format_time(pos_s)} / {self.format_time(dur_s)}")

# -- Scene List Click Handlers --
    # single click: seek to a scene's start on  (don't autoplay)
    def _jump_to_scene_start(self, item: QListWidgetItem) -> None:
    # Seek preview player to the start of the selected scene (does not auto-play).
        if not item:
            return

        data = item.data(Qt.ItemDataRole.UserRole)

        # Support both tuple (start_s, end_s) and dict {start_s & end_s}
        try:
            if isinstance(data, dict):
                start_s = float(data.get("start_s", 0.0))
                end_s = float(data.get("end_s", start_s))
            else:
                start_s, end_s = data  # expected tuple
                start_s = float(start_s)
                end_s = float(end_s)
        except Exception:
            self.status.showMessage("Could not read scene timing data.", 3000)
            return

        # Clamp if we know duration
        if getattr(self, "_media_duration_ms", 0) > 0:
            duration_s = float(self._media_duration_ms) / 1000.0
            start_s, end_s = self._clamp_range(start_s, end_s, duration_s)

        # Set auto-stop point (end of scene)
        self._scene_stop_ms = int(end_s * 1000)

        # Seek player
        self.player.setPosition(int(start_s * 1000))

        self.status.showMessage(
            f"Jumped to {start_s:.2f}s (scene ends at {end_s:.2f}s).",
            2500
        )

    # double click: seek & play on 
    def _play_from_scene_start(self, item: QListWidgetItem) -> None:
    # Seek preview player to the start of the selected scene and start playback."""
        if not item:
            return

        data = item.data(Qt.ItemDataRole.UserRole)

        # Support both tuple (start_s, end_s) and dict {start_s & end_s}
        try:
            if isinstance(data, dict):
                start_s = float(data.get("start_s", 0.0))
                end_s = float(data.get("end_s", start_s))
            else:
                start_s, end_s = data  # expected tuple
                start_s = float(start_s)
                end_s = float(end_s)
        except Exception:
            self.status.showMessage("Could not read scene timing data.", 3000)
            return

        # Clamp if we know duration
        if getattr(self, "_media_duration_ms", 0) > 0:
            duration_s = float(self._media_duration_ms) / 1000.0
            start_s, end_s = self._clamp_range(start_s, end_s, duration_s)

        # Set auto-stop point (end of scene)
        self._scene_stop_ms = int(end_s * 1000)

        # Seek then play
        self.player.setPosition(int(start_s * 1000))
        self.player.play()

        # Play button icon (consistent UX)
        self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

        self.status.showMessage(
            f"Playing scene: {start_s:.2f}s → {end_s:.2f}s (auto-stop).",
            2500
        )
    
    def _select_all_scenes(self) -> None:
        """
        Select all scenes in the list for batch export operations.
        Improves usability by avoiding tedious manual selection of many scenes.
        """
        for idx in range(self.scene_list.count()):
            item = self.scene_list.item(idx)
            if item and item.data(Qt.ItemDataRole.UserRole):  # Skip placeholder "No scenes" items
                item.setCheckState(Qt.CheckState.Checked)
        self.status.showMessage(f"Selected all {self.scene_list.count()} scenes", 2000)

    def _deselect_all_scenes(self) -> None:
        """
        Deselect all scenes in the list.
        Allows users to quickly clear selections and start fresh.
        """
        for idx in range(self.scene_list.count()):
            item = self.scene_list.item(idx)
            if item and item.data(Qt.ItemDataRole.UserRole):  # Skip placeholder items
                item.setCheckState(Qt.CheckState.Unchecked)
        self.status.showMessage("Cleared all selections", 2000)

    def _update_selection_count(self) -> None:
        """
        Update the selection counter label to show checked scene count.
        Provides immediate visual feedback on what will be exported.
        Called automatically whenever checkboxes change (itemChanged signal).
        """
        count = sum(
            1 for idx in range(self.scene_list.count())
            if (self.scene_list.item(idx).checkState() == Qt.CheckState.Checked
                and self.scene_list.item(idx).data(Qt.ItemDataRole.UserRole))
        )
        
        # Update label with grammatically correct text
        text = f"{count} scene{'s' if count != 1 else ''} selected"
        self.selection_label.setText(text)
        
        # Visual feedback: Highlight when scenes are selected
        if count > 0:
            self.selection_label.setStyleSheet(
                "font-weight: bold; "
                "padding: 8px; "
                "background-color: #d4edda; "  # Green background when selected
                "border: 1px solid #c3e6cb; "
                "border-radius: 4px; "
                "color: #155724;"
            )
        else:
            self.selection_label.setStyleSheet(
                "font-weight: bold; "
                "padding: 8px; "
                "background-color: #e8f4f8; "  # Blue-gray when none selected
                "border: 1px solid #b8d4e0; "
                "border-radius: 4px; "
                "color: #2c5f7c;"
            )

# --- Progress Bar Helpers ---

    def _progress_busy(self, msg: str):                                                 
        # Indeterminate spinner-style progress with a status message               
        self.status.showMessage(msg)                                                   
        self.progress.setVisible(True)                                                 
        self.progress.setRange(0, 0)   # indeterminate                                 

    def _progress_steps(self, total: int, msg: str):                                     
        # Determinate progress with a known step count                             
        self.status.showMessage(msg)                                                     
        self.progress.setVisible(True)                                                 
        self.progress.setRange(0, max(1, int(total)))                                  
        self.progress.setValue(0)                                                      

    def _progress_done(self, msg: str = ""):                                            
        # Hide progress and optionally set a final status message                
        if msg:                                                                         
            self.status.showMessage(msg, 4000)                                               
        self.progress.setVisible(False)                                                
        self.progress.setRange(0, 1)                                                  
        self.progress.setValue(0)   

    def _toggle_top_highlights(self, checked: bool) -> None:
        """
        Iteration 2: Toggle scene ranking by highlight score.
        When OFF: Scenes shown in chronological order
        When ON: Scenes sorted by score (highest first)
        """
        self.top_highlights_only = bool(checked)
        self._rebuild_scene_list()
        if checked:
            self.status.showMessage("Scenes ranked by score (highest first)", 2500)
        else:
            self.status.showMessage("Scenes shown in chronological order", 2500)


    def _rebuild_scene_list(self) -> None:
        """
        Rebuild scene list using cached detection results.
        Applies sorting by highlight_score and optional filtering.
        """
        self.scene_list.clear()

        scenes = getattr(self, "current_scenes", None) or []
        scene_data = getattr(self, "current_scene_data", None) or []

        if not scenes and not scene_data:
            self.scene_list.addItem(QListWidgetItem("No scenes detected."))
            return

        display_items = []

        if scene_data:
            for sd in scene_data:
                try:
                    scene_idx = int(sd.get("scene_idx", 0))
                    start_s = float(sd.get("start_s", 0.0))
                    end_s = float(sd.get("end_s", 0.0))
                    score = float(sd.get("highlight_score", 0.0))
                except Exception:
                    continue

                if getattr(self, "_media_duration_ms", 0) > 0:
                    dur_s = self._media_duration_ms / 1000.0
                    start_s, end_s = self._clamp_range(start_s, end_s, dur_s)

                display_items.append((scene_idx, start_s, end_s, score))

            # Iteration 2: Only sort by score when "Rank Scenes" is toggled ON
            if self.top_highlights_only:
                # Sort by score (highest first), then by start time
                display_items.sort(key=lambda x: (-x[3], x[1]))
            else:
                # Keep chronological order (sort by start time only)
                display_items.sort(key=lambda x: x[1])

        else:
            for idx, (start, end) in enumerate(scenes):
                start_s = self._to_seconds(start)
                end_s = self._to_seconds(end)
                display_items.append((idx, start_s, end_s, 0.0))

        for rank, (scene_idx, start_s, end_s, score) in enumerate(display_items, start=1):
            label = (
                f"{rank:02d}. Scene {scene_idx + 1} | "
                f"Score {score:.2f} | "
                f"{self.format_time(start_s)} → {self.format_time(end_s)}"
            )
            item = QListWidgetItem(label)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, (start_s, end_s))
            self.scene_list.addItem(item)

        # Update selection counter after rebuilding the list
        self._update_selection_count()

    def export_clips(self):
        """
        Iteration 4 - Commit 3: Enhanced export with directory selection and individual clip naming.
        
        Export workflow:
            1. Validate preconditions (file loaded, scenes detected, selections made)
            2. Let user choose export directory
            3. Show naming dialog for each selected clip
            4. Export with loading animation
        """
        
        # --- 1) Preconditions: ensure a file is loaded and scenes exist
        if not self.current_file:
            self.set_actions_enabled(False)
            QMessageBox.information(
                self, 
                "Export Clips",
                "Please import a video first to export."
            )
            return

        if not self.current_scenes or self.scene_list.count() == 0:
            QMessageBox.information(
                self, 
                "Export Clips", 
                "No detected scenes found. Run detection first."
            )
            return
        
        # --- 2) Tool sanity: confirm ffmpeg is runnable
        if not self._ffmpeg_ok():  
            return 

        # --- 3) Selection: collect ONLY checked rows; skip ~0s segments
        duration = float(self._media_duration)
        if duration <= 0.05:
            QMessageBox.critical(
                self, 
                "Export Clips", 
                "Invalid media duration; cannot export."
            )
            return

        clamped = self._collect_valid_selections(duration)  
        if not clamped:
            return
        
        # ===== Iteration 4 - Commit 3: Directory Selection Dialog =====
        # Let user choose where to save exports instead of hardcoded ./exports
        export_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose Export Directory",
            os.path.expanduser("~"),  # Start in user's home directory
            QFileDialog.Option.ShowDirsOnly
        )
        
        if not export_dir:
            self.status.showMessage("Export cancelled by user.", 3000)
            return
        
        # Verify write permissions
        if not os.access(export_dir, os.W_OK):
            QMessageBox.critical(
                self, 
                "Export Clips", 
                f"No write permission to:\n{export_dir}"
            )
            return
        
        # ===== Iteration 4 - Commit 3: Individual Clip Naming Dialog =====
        # Show dialog for user to name each clip
        basename = os.path.splitext(os.path.basename(self.current_file))[0]
        naming_dialog = ExportNamingDialog(self, clamped, basename)
        naming_dialog.show()
        
        # Wait for dialog to close
        from PyQt6.QtCore import QEventLoop
        loop = QEventLoop()
        naming_dialog.destroyed.connect(loop.quit)
        loop.exec()
        
        # Check if user cancelled
        if naming_dialog.result_names is None:
            self.status.showMessage("Export cancelled by user.", 3000)
            return
        
        custom_names = naming_dialog.result_names
        
        # ===== Iteration 4 - Commit 3: Export Loading Animation =====
        # Use indeterminate progress initially, then switch to determinate
        self._progress_busy("Preparing export...")
        self.status.showMessage("Exporting clips... please wait.")
        self.detect_btn.setEnabled(False)
        self.export_action_menu.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        # --- 7) Run export in a worker thread (no UI freeze)
        self._export_thread = QThread(self)
        self._export_worker = Worker(
            _export_job,
            self._run_ffmpeg_slice,
            custom_names,  # User-provided names
            self.current_file,
            clamped,
            duration,
            export_dir,
        )
        self._export_worker.moveToThread(self._export_thread)

        # ===== Iteration 4 - Commit 3: Enhanced Progress Feedback =====
        # Switch from indeterminate to determinate progress when export starts
        def on_export_progress(payload):
            if not isinstance(payload, dict):
                return
            if payload.get("phase") == "export":
                done = int(payload.get("done", 0))
                total = max(1, int(payload.get("total", 1)))
                
                # Switch to determinate progress bar
                self.progress.setVisible(True)
                self.progress.setRange(0, total)
                self.progress.setValue(min(done, total))
                
                # Update status message with progress
                if done < total:
                    last_ok = payload.get("last_ok", True)
                    scene_num = payload.get("scene", 0)
                    status_icon = "✓" if last_ok else "✗"
                    self.status.showMessage(
                        f"Exporting clip {done}/{total} {status_icon} Scene {scene_num}..."
                    )
        
        self._export_worker.progress.connect(on_export_progress)

        # Start the worker when thread starts
        self._export_thread.started.connect(self._export_worker.run, Qt.ConnectionType.QueuedConnection)

        # --- 8) Finish chain: UI restore > quit thread > delete objects 
        def on_finished(payload):
            self._progress_done("Export complete.")
            self.status.showMessage("Export done! Clips saved to chosen folder", 6000)
            QApplication.restoreOverrideCursor()
            self.detect_btn.setEnabled(True)
            self.export_action_menu.setEnabled(True)

            # Error handling
            if isinstance(payload, Exception):
                QMessageBox.critical(
                    self, 
                    "Export Error", 
                    f"Export failed:\n{payload}"
                )
                return
            
            # Extract metrics from the payload
            requested = int(payload.get("requested", 0))
            ok = int(payload.get("ok", 0))
            failed = int(payload.get("failed", 0))
            errors = payload.get("errors", [])
            elapsed_s = float(payload.get("elapsed_s", 0.0))
            elapsed_ms = elapsed_s * 1000.0

            # --- 9) Metrics: console + status bar + dialogs
            metrics_line = (
                f"Export summary: requested={requested} | ok={ok} | "
                f"failed={failed} | elapsed={elapsed_ms:.1f} ms ({elapsed_s:.2f}s)"
            )

            # Log export summary 
            self._log_run("export", {
                "file": os.path.basename(self.current_file),
                "operation": "export", 
                "requested": requested,
                "ok": ok,
                "failed": failed,
                "elapsed_s": round(elapsed_s, 3),
                "export_dir": export_dir,
            })

            # Print results to console
            print("\n[Export Metrics]")
            print(f"File: {os.path.basename(self.current_file)}")
            print(metrics_line)

            if failed:
                n, s, e, err = errors[0]
                snippet = (err or "").strip().splitlines()
                snippet = snippet[0] if snippet else "(no stderr)"
                print(f"First failure: Scene {n} {s:.2f}s→{e:.2f}s")
                print(f"stderr: {snippet}")
            print("-" * 60)

            # Keep metrics visible in the status bar
            self.status.showMessage(metrics_line, 8000)

            # --- 10) User-facing dialogs summarizing outcome 
            if ok > 0 and failed == 0:
                QMessageBox.information(
                    self,
                    "Export Complete",
                    f"Successfully exported {ok} clip(s) to:\n{export_dir}\n\n{metrics_line}",
                )
            elif ok > 0 and failed > 0:
                n, s, e, err = errors[0]
                QMessageBox.warning(
                    self,
                    "Export Partially Complete",
                    f"Exported {ok} clip(s), {failed} failed.\n"
                    f"First failure (Scene {n} {s:.2f}s→{e:.2f}s):\n"
                    f"{err or '(no stderr)'}\n\n{metrics_line}",
                )
            else:
                QMessageBox.critical(
                    self,
                    "Export Error",
                    "No clips were successfully exported.\nPlease verify ffmpeg and try again.",
                )

        # --- 12) Connect worker to completion handler 
        self._export_worker.finished.connect(on_finished)
        self._export_worker.finished.connect(self._export_thread.quit)
        self._export_thread.finished.connect(self._export_worker.deleteLater)
        self._export_thread.finished.connect(self._export_thread.deleteLater)
        self._export_thread.start()

    def open_settings(self):
        # Placeholder for app settings dialog.
        QMessageBox.information(
            self, "Settings", "Settings dialog coming soon!"
        )
        print("Settings opened (placeholder).")

    def show_about(self):
        # Show a simple About dialog.
        QMessageBox.information(
            self,
            "About Aura Clip",
            "Aura Clip (PP4 Iteration 3 Build)\n\n"
            "Developed by Arianna Miller-Paul (Full Sail University)\n"
            "Scene detection tool with PySceneDetect + AI-powered highlight ranking.\n\n"
        "Features: Audio analysis, YOLO object detection, automated export."
        )
        print("Displayed About dialog.")

    def show_glossary(self):
        """
        ===== Display in-app glossary of technical terms =====
        Usability improvement:
        - Users found terms like "threshold", "highlight score" confusing
        - This glossary provides clear definitions without leaving the app
        - Accessible via Help menu → Glossary
        """
        glossary_text = """<h3>Aura Clip Glossary</h3>

<p><b>Scene Detection:</b> The process of identifying cuts or transitions in video where content changes significantly (camera angles, locations, action).</p>

<p><b>Threshold:</b> Sensitivity level for detecting scene changes (1-100 scale). 
<br>• Lower values (10-20) = More sensitive, detects subtle changes, creates more scenes
<br>• Higher values (30-50) = Less sensitive, only detects major changes, fewer scenes
<br>• Default: 27 works well for most gameplay videos</p>

<p><b>Highlight Score:</b> Automatic ranking (0.0-1.0) of how "interesting" a scene is.
<br>• Calculated from: Audio energy (60%) + Duration bonus (40%)
<br>• Higher score = More likely to be exciting/exportable moment
<br>• AI mode also includes object detections in scoring</p>

<p><b>Audio Energy:</b> Measure of sound loudness/intensity (RMS) in a scene.
<br>• Higher values = Louder moments (gunshots, explosions, excitement)
<br>• Normalized to 0.0-1.0 scale (0 = silent, 1 = very loud)</p>

<p><b>AI Detections:</b> Count of action-related objects found by YOLO AI (people, vehicles, weapons).
<br>• Higher count = More visible action in the scene
<br>• Only available in AI detection mode</p>

<p><b>Detection Modes:</b>
<br>• <b>PySceneDetect:</b> Fast traditional detection (2-5 seconds) using frame content analysis
<br>• <b>AI Mode:</b> Slower but smarter (2-3 minutes) using YOLO object detection + audio analysis
<br>• <b>Manual:</b> Currently falls back to PySceneDetect behavior</p>

<p><b>FPS (Frames Per Second):</b> Video playback speed. Standard rates:
<br>• 24fps = Cinema, 30fps = Standard video, 60fps = Smooth gameplay</p>

<p><b>Export:</b> Save selected scenes as separate MP4 video files to ./exports folder.
<br>• Only checked scenes are exported
<br>• Original video quality is preserved</p>
"""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Glossary - Technical Terms")
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        msg_box.setText(glossary_text)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()
        print("[Glossary] Displayed technical term definitions to user.")

    # ===== Iteration 4 - Commit 1: New UI Helper Methods =====

    def _select_all_scenes(self) -> None:
        """Select all scenes in the list for export."""
        for idx in range(self.scene_list.count()):
            item = self.scene_list.item(idx)
            if item.data(Qt.ItemDataRole.UserRole):  # Skip placeholder items
                item.setCheckState(Qt.CheckState.Checked)
        self._update_selection_counter()

    def _deselect_all_scenes(self) -> None:
        """Deselect all scenes in the list."""
        for idx in range(self.scene_list.count()):
            item = self.scene_list.item(idx)
            if item.data(Qt.ItemDataRole.UserRole):  # Skip placeholder items
                item.setCheckState(Qt.CheckState.Unchecked)
        self._update_selection_counter()

    def _toggle_rank_from_button(self, checked: bool) -> None:
        """Handle rank toggle button state and update scene list."""
        self.top_highlights_only = checked
        # Update button text to show current state
        if checked:
            self.rank_toggle_btn.setText("★ Ranked by Score")
            self.status.showMessage("Scenes ranked by score (highest first)", 2500)
        else:
            self.rank_toggle_btn.setText("☆ Rank Scenes by Score")
            self.status.showMessage("Scenes shown in chronological order", 2500)
        self._rebuild_scene_list()

    def _update_selection_counter(self) -> None:
        """Update the selection counter label showing how many scenes are checked."""
        selected_count = 0
        for idx in range(self.scene_list.count()):
            item = self.scene_list.item(idx)
            if item.checkState() == Qt.CheckState.Checked:
                selected_count += 1
        
        # Update label with color coding
        self.selection_label.setText(f"{selected_count} scenes selected")
        if selected_count == 0:
            self.selection_label.setStyleSheet("color: gray;")
        else:
            self.selection_label.setStyleSheet("color: #0A84FF;")  # Premiere Pro blue

    def show_glossary(self) -> None:
        """Show the glossary dialog (placeholder for Commit 5)."""
        QMessageBox.information(
            self,
            "Glossary",
            "Glossary content will be populated in Commit 5.\n\n"
            "This will include:\n"
            "• Technical term definitions\n"
            "• Workflow tips\n"
            "• Keyboard shortcuts\n"
            "• UI interaction guide"
        )

    def closeEvent(self, event):
        """
        Ensure background threads are stopped before the window is destroyed,
        but be tolerant if Qt already deleted them (avoids RuntimeError).
        """
        def _safe_stop(name: str):
            t = getattr(self, name, None)
            if not t:
                return
            try:
                # t may already be C++-deleted; any attribute access can raise RuntimeError
                running = False
                try:
                    running = t.isRunning()
                except RuntimeError:
                    running = False

                if running:
                    try:
                        t.requestInterruption()
                    except Exception:
                        pass
                    try:
                        t.quit()
                    except Exception:
                        pass
                    try:
                        t.wait(3000)
                    except Exception:
                        pass
            except RuntimeError:
                # The wrapper is pointing at a deleted C++ object; ignore.
                pass
            finally:
                # Clear our reference no matter what
                setattr(self, name, None)

        _safe_stop("_detect_thread")
        _safe_stop("_export_thread")

        super().closeEvent(event)



# --- Application Entry Point ---

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AuraClipApp()
    window.show()
    sys.exit(app.exec())

#scripts + test folder creation