"""
Aura Clip (PP4 R&D Build)
-------------------------
Week-1 Project base with end-to-end tech stack:

- UI: PyQt6 (menus, status, list view, preview player)
- Detection: PySceneDetect (supports v0.6+ and legacy v0.5 API)
- Metadata: MoviePy (read-only probe for duration / fps / size)
- Export: ffmpeg (via imageio-ffmpeg binary; direct subprocess calls)

User flow:
  Import → Detect → (Select scenes) → Export
Plus: preview player with play/pause, ±/-5s, seek; click scene to seek; double-click to play.
"""

# -------- Aura Clip - Base Application Window -------

# Third-party libraries & Qt widgets used to build the UI
# PyQt6 drives the desktop UI to create the base window.
from PyQt6.QtCore import Qt, QUrl, QThread, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QStatusBar, QMenuBar,
    QFileDialog, QMessageBox, QWidget, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QSlider, QStyle,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

# --- Standard Library ---
import sys, os, subprocess, time

class Worker(QObject):
    """
    Generic worker that runs a callable in a background thread.
    Emits `finished` with either the result dict or an Exception.
    """
    finished = pyqtSignal(object)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit(e)


# --- Scene detection (PySceneDetect) ---
# Importing scenedetect safely
SCENEDETECT_AVAILABLE = False            
SCENEDETECT_API = None  

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

def _detect_job(api, filepath, threshold=27.0):
    """
        Background job for scene detection.
        Runs outside the GUI thread via QtConcurrent to avoid UI freezes.

        Parameters:
        api: "v0.6+" or "v0.5" — which PySceneDetect API to use
        filepath: path to the video file
        threshold: ContentDetector threshold (higher = fewer scenes)

        Returns:
        dict with:
            - scenes: list of (start, end) timecodes from PySceneDetect
            - threshold: the threshold used
            - elapsed_s: total wall time in seconds
    """
    start_time = time.perf_counter()        # start timing

    if api == "v0.6+":
        # v0.6+ API: open video, configure manager, add detector, run
        video = open_video(filepath)
        sm = SceneManager()
        sm.add_detector(ContentDetector(threshold=threshold, luma_only=True))
        sm.detect_scenes(video)
        scenes = sm.get_scene_list()
    elif api == "v0.5":
        # v0.5 API: need a VideoManager explicitly, start(), detect, then release
        vm = VideoManager([filepath])
        sm = SceneManager()
        sm.add_detector(ContentDetector(threshold=threshold))
        vm.set_downscale_factor()       # speed-up: will process fewer pixels
        vm.start()
        sm.detect_scenes(frame_source=vm)
        scenes = sm.get_scene_list()
        vm.release()
    else:
        # In case our import shim mis-detected the API version
        raise RuntimeError("Unsupported PySceneDetect API version.")
    
    elapsed_s = time.perf_counter() - start_time        # total detection time
    return {"scenes": scenes, "threshold": threshold, "elapsed_s": elapsed_s}

def _export_job(run_ffmpeg_slice, scene_count, basename, src_file, selections, duration, export_dir):
    """
        Background job for exporting selected scenes via ffmpeg.
        Runs outside the GUI thread via QtConcurrent to avoid UI freezes.

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

    # Pad scene index in filenames so they sort nicely
    pad = max(2, len(str(scene_count)))

    # Export each selected scene using the provided ffmpeg helper
    for (idx, start_s, end_s) in selections:
        scene_num = idx + 1
        out_path = os.path.join(export_dir, f"{basename}_scene_{scene_num:0{pad}d}.mp4")

        # Run ffmpeg slice; returns (ok, stderr)
        ok, err = run_ffmpeg_slice(src_file, start_s, end_s, out_path)
        if ok:
            exported_ok += 1
        else:
            # Keep enough context to show useful diagnostics to the user
            errors.append((scene_num, start_s, end_s, err))

    elapsed_s = time.perf_counter() - start_wall        # total export time

    return {
        "requested": len(selections),
        "ok": exported_ok,
        "failed": len(errors),
        "errors": errors,
        "elapsed_s": elapsed_s,
        "export_dir": export_dir,
    }

# ----- MAIN WINDOW -----
class AuraClipApp(QMainWindow):
    
    def __init__(self):
        super().__init__()

        # --- Window chrome & state ---
        self.setWindowTitle("Aura Clip - Iteration 1")
        self.setGeometry(200, 200, 900, 600)

        # Track the currently selected file path + detected scenes in memory
        self.current_file: str | None = None
        self.current_scenes: list | None = None

        # --- Main content area ---
        """ 
            [Left-Top] Video preview panel + file metadata 
            [Left-Bottom]Transport Bar (video playback buttons and slider)
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

        t.addWidget(self.btn_back)
        t.addWidget(self.btn_play)
        t.addWidget(self.btn_fwd)
        t.addWidget(self.seek, stretch=1)
        left_v.addWidget(transport)

        # Right: scenes list (checkable items; export only the checked ones)
        self.scene_list = QListWidget(self.container)           
        self.scene_list.setFixedWidth(350)                  
        self.layout.addWidget(self.scene_list) 
        # clicking a scene seeks to its start; double-click plays from there   
        self.scene_list.itemClicked.connect(self._jump_to_scene_start)       
        self.scene_list.itemDoubleClicked.connect(self._play_from_scene_start)             

        # --- Status Bar ---
        # Displays messages to the user, such as file loaded or task complete.
        self.status = QStatusBar(self)
        self.setStatusBar(self.status)

        # --- Menu Bar ---
        # The menu bar gives the user structured access to actions.
        menubar = QMenuBar(self)
        self.setMenuBar(menubar)

        # File Menu (Import + Exit buttons)
        file_menu = menubar.addMenu("File")

        import_action = file_menu.addAction("Import Video")
        import_action.triggered.connect(self.import_video)

        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

        # Tools Menu (Detect / Export buttons)
        tools_menu = menubar.addMenu("Tools")

        self.detect_action = tools_menu.addAction("Detect Scenes")
        self.detect_action.triggered.connect(self.detect_scenes)

        self.export_action = tools_menu.addAction("Export Clips")
        self.export_action.triggered.connect(self.export_clips)

         # Disabled at startup until a file is loaded
        self.detect_action.setEnabled(False)                        
        self.export_action.setEnabled(False)                        

        # Settings Menu
        settings_menu = menubar.addMenu("Settings")
        settings_action = settings_menu.addAction("Preferences")
        settings_action.triggered.connect(self.open_settings)

        # Help Menu
        help_menu = menubar.addMenu("Help")
        about_action = help_menu.addAction("About Aura Clip")
        about_action.triggered.connect(self.show_about)

        print("Aura Clip initialized successfully.")

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

    # Helper to enable/disable both actions at once
    def set_actions_enabled(self, loaded: bool) -> None:
        self.detect_action.setEnabled(loaded) 
        self.export_action.setEnabled(loaded)  

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
            QMessageBox.critical(self, "Media Error", f"Could not read media info:\n{e}")
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
        info = self.get_media_info(file_path)
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
        self.status.showMessage("Video loaded. Next: Tools → Detect Scenes.", 5000)  

        self.scene_list.clear() # to clear previous detections
        self.status.showMessage(f"Imported: {basename}", 5000)  

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
        if not SCENEDETECT_AVAILABLE:
            QMessageBox.critical(
                self, 
                "Missing Library",
                "PySceneDetect not available.\nInstall with:\n  pip install scenedetect"
            )
            return

        # Immediate user feedback + block re-entrancy while running
        self.status.showMessage("Detecting scenes... please wait.")
        self.detect_action.setEnabled(False)
        self.export_action.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        # Spin up a one-off worker thread for detection
        self._detect_thread = QThread(self)
        self._detect_worker = Worker(_detect_job, SCENEDETECT_API, self.current_file, 27.0)
        self._detect_worker.moveToThread(self._detect_thread)
        
        def on_finished(payload):
            # Back on the GUI thread
            QApplication.restoreOverrideCursor()
            self.detect_action.setEnabled(True)
            self.export_action.setEnabled(bool(self.current_file))
            self._detect_thread.finished.connect(lambda: setattr(self, "_detect_thread", None))
            self._detect_thread.destroyed.connect(lambda: setattr(self, "_detect_thread", None))


            if isinstance(payload, Exception):
                QMessageBox.critical(self, "Detection Error", f"Failed to detect scenes:\n{payload}")
                self.status.showMessage("Scene detection failed.", 5000)
                return

            scenes = payload["scenes"]
            threshold = payload["threshold"]
            elapsed_s = payload["elapsed_s"]
            elapsed_ms = elapsed_s * 1000.0  # milliseconds
                
            # --- Update UI list ---
            self.current_scenes = scenes
            self.scene_list.clear()

            if not scenes:
                # Handle no-detection case cleanly
                self.scene_list.addItem("No scenes detected.")
                msg = f"No scenes found | threshold={threshold} | elapsed={elapsed_ms:.1f} ms"
                print(msg)                      # console record for empirical logs
                self.status.showMessage(msg)    # may add auto-disappearing in the future
                return

                # Populate list with checkable items + store raw (start_s, end_s)
            for i, (start, end) in enumerate(scenes, start=1):
                start_s = self._to_seconds(start)
                end_s   = self._to_seconds(end)
                item = QListWidgetItem(
                    f"Scene {i}: {self.format_time(start_s)} → {self.format_time(end_s)}"
                )
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setData(Qt.ItemDataRole.UserRole, (start_s, end_s))
                self.scene_list.addItem(item)

            # --- Metrics output 
            msg = (f"Detected {len(scenes)} scene(s) | threshold={threshold} | "
                f"elapsed={elapsed_ms:.1f} ms ({elapsed_s:.2f}s)")
            print("\n[Detection Metrics]")
            print(f"File: {os.path.basename(self.current_file)}")
            print(msg)
            print("-" * 60)
            self.status.showMessage(msg)  # shows metrics; may add auto-disappearing in the future

        # Wire signals: when the thread starts, run the worker; when done, handle result
        self._detect_thread.started.connect(self._detect_worker.run)
        self._detect_worker.finished.connect(on_finished)
        self._detect_worker.finished.connect(self._detect_thread.quit)   # stop the thread
        self._detect_thread.finished.connect(self._detect_worker.deleteLater)   # safe cleanup
        self._detect_thread.finished.connect(self._detect_thread.deleteLater)
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

    # Map slider range [0..1000] to [0..duration_ms] and seek
    def _seek_to_ratio(self, val: int):
        # slider 0..1000 → position 0..duration
        if self._media_duration_ms > 0:
            target = int((val / 1000.0) * self._media_duration_ms)
            self.player.setPosition(target)

    # Cache media duration (ms) for consistent slider math
    def _on_duration(self, dur_ms: int):
        self._media_duration_ms = max(0, dur_ms)

    # Update slider to reflect current playback position (no feedback loop)
    def _on_position(self, pos_ms: int):
        # keep slider synced with playback
        if self._media_duration_ms > 0:
            ratio = pos_ms / self._media_duration_ms
            self.seek.blockSignals(True)
            self.seek.setValue(int(ratio * 1000))
            self.seek.blockSignals(False)

# -- Scene List Click Handlers --
    # single click: seek to a scene's start on  (don't autoplay)
    def _jump_to_scene_start(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        start_s, _ = data
        # Clamp & seek
        pos = max(0, int(float(start_s) * 1000))
        self.player.pause()
        self.player.setPosition(pos)
        # Set play button icon back to "Play"
        self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.status.showMessage(f"Jumped to {start_s:.2f}s.", 2000)

    # double click: seek & play on 
    def _play_from_scene_start(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        start_s, _ = data
        pos = max(0, int(float(start_s) * 1000))
        self.player.setPosition(pos)
        self.player.play()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self.status.showMessage(f"Playing from {start_s:.2f}s.", 2000)


    def export_clips(self):
        """
            Export all CHECKED scenes to ./exports as MP4 using ffmpeg, without freezing the UI
            Uses QThread + Worker to run ffmpeg work off the GUI thread

            Metrics added (Iteration 1 - Commit: Export Summary + Timings):
            - requested (selected after clamping) vs ok vs failed
            - total elapsed wall time
            - first stderr snippet if any failures
            - status-bar summary + console block
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
        ffmpeg_bin = os.environ.get("IMAGEIO_FFMPEG_EXE") or "ffmpeg" 
        try:                                                          
            probe = subprocess.run([ffmpeg_bin, "-version"], capture_output=True, text=True)
            if probe.returncode != 0:
                raise RuntimeError("ffmpeg not runnable")
        except Exception:
            QMessageBox.critical(
                self, 
                "Missing ffmpeg", 
                "ffmpeg is not runnable. Reinstall imageio-ffmpeg or system ffmpeg."
                )
            return

        # --- 3) Selection: collect ONLY checked rows; skip ~0s segments; scene number given in detect 
        # stays the same during export to avoid user confusion
        selections = []  # (idx, start_s, end_s)  
        for idx in range(self.scene_list.count()):                                        
            item = self.scene_list.item(idx)                                              
            if item.checkState() == Qt.CheckState.Checked:                                
                data = item.data(Qt.ItemDataRole.UserRole)
                if not data:
                    continue
                start_s, end_s = data                     
                # Skip invalid or near-zero-length segments
                if (end_s - start_s) > 0.05:
                    selections.append((idx, start_s, end_s))                               

        if not selections:                                                               
            QMessageBox.information(
                self, 
                "Export Clips", 
                "No scenes selected to export."
                )
            return     

        # --- 4) Safety: clamp (start,end) to the media duration to avoid out-of-range/OOB writes
        info = self.get_media_info(self.current_file)                  
        duration = float(info.get("duration", 0.0)) if info else 0.0   
        if duration <= 0.05:                                            
            QMessageBox.critical(
                self, 
                "Export Clips", 
                "Invalid media duration; cannot export."
                )  
            return                                                     

        clamped = [] 
        for idx, s, e in selections:  
            # Ensure times are within [0, duration]                                 
            s2 = max(0.0, min(s, duration))                            
            e2 = max(0.0, min(e, duration))                             
            if e2 - s2 > 0.05:                                          
                clamped.append((idx, s2, e2))                          
        
        if not clamped:                                                 
            QMessageBox.information(
                self, 
                "Export Clips", 
                "Nothing to export after clamping times."
                ) 
            return             

        # --- 5) IO prep: create ./exports and verify we can write there
        basename = os.path.splitext(os.path.basename(self.current_file))[0]
        export_dir = os.path.join(os.getcwd(), "exports")
        os.makedirs(export_dir, exist_ok=True)

        # Check write permission to ensure we can export files
        if not os.access(export_dir, os.W_OK):
            QMessageBox.critical(
                self, "Export Clips", f"No write permission to:\n{export_dir}"
            )
            return                                           

        # --- 6) Work: for each segment, run ffmpeg and update the list row text
        self.status.showMessage("Exporting clips... please wait.")
        self.detect_action.setEnabled(False)
        self.export_action.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        # --- 7) Run export in a worker thread (no UI freeze)
        self._export_thread = QThread(self)
        self._export_worker = Worker(
            _export_job,                     # background function
            self._run_ffmpeg_slice,          # ffmpeg helper
            self.scene_list.count(),         # total scene count (for file naming)
            basename,                        # base name for output files
            self.current_file,               # source video
            clamped,                         # validated time ranges
            duration,                        # duration (for context)
            export_dir,                      # destination folder
        )
        self._export_worker.moveToThread(self._export_thread)

        # --- 8) Define what happens when export finishes 
        def on_finished(payload):
            # Called automatically when the background export job completes.
            # Restore UI controls and cursor
            QApplication.restoreOverrideCursor()
            self.detect_action.setEnabled(True)
            self.export_action.setEnabled(True)
            self._export_thread.finished.connect(lambda: setattr(self, "_export_thread", None))
            self._export_thread.destroyed.connect(lambda: setattr(self, "_export_thread", None))


            if isinstance(payload, Exception):
                QMessageBox.critical(self, "Export Error", f"Export failed:\n{payload}")
                self.status.showMessage("Export failed.", 5000)
                return
            
            # Extract metrics from the payload
            requested = payload["requested"]
            ok = payload["ok"]
            failed = payload["failed"]
            errors = payload["errors"]
            elapsed_s = payload["elapsed_s"]
            elapsed_ms = elapsed_s * 1000.0
            export_dir_local = payload["export_dir"]

            # --- 9) Metrics: console + status bar + dialogs
            metrics_line = (
                f"Export summary: requested={requested} | ok={ok} | "
                f"failed={failed} | elapsed={elapsed_ms:.1f} ms ({elapsed_s:.2f}s)"
            )

            # Print results to console for empirical data logging
            print("\n[Export Metrics]")
            print(f"File: {os.path.basename(self.current_file)}")
            print(metrics_line)

            # If any scenes failed, print the first stderr snippet
            if failed:
                n, s, e, err = errors[0]
                snippet = (err or "").strip().splitlines()
                snippet = snippet[0] if snippet else "(no stderr)"
                print(f"First failure: Scene {n} {s:.2f}s→{e:.2f}s")
                print(f"stderr: {snippet}")
            print("-" * 60)

            # Keep metrics visible in the status bar; may add auto disappear in future
            self.status.showMessage(metrics_line)

            # --- 10) User-facing dialogs summarizing outcome 
            if ok > 0 and failed == 0:
                # All exports succeeded
                QMessageBox.information(
                    self,
                    "Export Complete",
                    f"Exported {ok} scene(s) to:\n{export_dir_local}\n\n{metrics_line}",
                )

            elif ok > 0 and failed > 0:
                # Some succeeded, some failed; partial completion
                n, s, e, err = errors[0]
                QMessageBox.warning(
                    self,
                    "Export Partially Complete",
                    f"Exported {ok} clip(s), {failed} failed.\n"
                    f"First failure (Scene {n} {s:.2f}s→{e:.2f}s):\n"
                    f"{err or '(no stderr)'}\n\n{metrics_line}",
                )

            else:
                # No successful exports
                hint = errors[0][3] if errors else "ffmpeg returned a non-zero code."
                QMessageBox.critical(
                    self,
                    "Export Error",
                    "No clips were exported.\n\n"
                    f"ffmpeg stderr (first failure):\n{hint or '(no stderr)'}\n\n"
                    f"Directory:\n{export_dir_local}\n\n{metrics_line}",
                )

            # --- 11) Cosmetic: visually mark exported scenes in the UI 
            for (idx, s, e) in clamped:
                if idx < self.scene_list.count():
                    self.scene_list.item(idx).setText(
                        f"Exported Scene {idx+1}: {s:.2f}s → {e:.2f}s"
                    )

        # --- 12) Connect worker to completion handler 
        self._export_thread.started.connect(self._export_worker.run)
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
            "Aura Clip (PP4 Iteration 1 Build)\n\n"
            "Developed by Arianna Miller-Paul (Full Sail University)\n"
            "This app demonstrates the integration of PyQt6 + MoviePy + PySceneDetect."
        )
        print("Displayed About dialog.")

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
