
# -------- Aura Clip - Base Application Window -------

# Third-party libraries & Qt widgets used to build the UI
# PyQt6 drives the desktop UI to create the base window.
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QStatusBar, QMenuBar,
    QFileDialog, QMessageBox, QWidget, QHBoxLayout,
    QListWidget, QListWidgetItem,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import QPushButton, QSlider, QStyle
from PyQt6.QtCore import QUrl

# --- Standard Library ---
import sys
import os
import subprocess

# --- Scene detection (PySceneDetect) ---
# Importing scenedetect safely
SCENEDETECT_AVAILABLE = False            
SCENEDETECT_API = None  
""" This supports EITHER the modern v0.6+ API OR the legacy v0.5 API """
try:
    # v0.6+ API
    from scenedetect import SceneManager, open_video        
    from scenedetect.detectors import ContentDetector      
    SCENEDETECT_AVAILABLE = True                           
    SCENEDETECT_API = "v0.6+"                              
except Exception:
    try:
        # v0.5 Legacy API
        from scenedetect import VideoManager, SceneManager  
        from scenedetect.detectors import ContentDetector  
        SCENEDETECT_AVAILABLE = True                        
        SCENEDETECT_API = "v0.5"                            
    except Exception:
        pass    # remains unavailable; UI will show a friendly message      

# Lightweight MoviePy import for read only metadata; 
# VideoFileClip is only needed to read duration/fps/size, no writing
try:
    from moviepy.video.io.VideoFileClip import VideoFileClip              
    MOVIEPY_AVAILABLE = True 
except Exception:
    VideoFileClip = None                          
    MOVIEPY_AVAILABLE = False      

# --- FFmpeg Setup (for exporting clips) ---
# ensures ffmpeg binary is known to MoviePy/imageio tools
import imageio_ffmpeg
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_EXE


# ----- MAIN WINDOW -----
class AuraClipApp(QMainWindow):
    
    def __init__(self):
        super().__init__()

        # --- Window chrome & state ---
        self.setWindowTitle("Aura Clip - Scene Detection R&D")
        self.setGeometry(200, 200, 900, 600)

        # Track the currently selected file path + detected scenes in memory
        self.current_file: str | None = None
        self.current_scenes: list | None = None

        # --- Main content area ---
        """ 
            [Left]  Video preview panel + file metadata 
            [Bottom]Transport Bar (video playback buttons and slider)
            [Right] Checkable scene list (one row per detected segment) 
        """
        # preview + info + scenes
        self.container = QWidget(self)
        self.layout = QHBoxLayout(self.container)
        self.setCentralWidget(self.container)           

        # Left: video preview (top) + info (bottom) + transport (bottom)
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
          a user-friendly error (the app remains usable).
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
            # Keeping it simple for now: show an error message and return empty info.
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

        # Format a friendly display, rounding values for readability
        duration_s = round(info["duration"], 2)  
        fps = round(info["fps"], 2)              
        w, h = info["width"], info["height"]     

        # Update UI with file + metadata
        basename = os.path.basename(file_path)  
        self.info_label.setText(                    
            f"Loaded file:\n{basename}\n\n"
            f"Duration: {duration_s}s\n"
            f"FPS: {fps}\n"
            f"Resolution: {w} x {h}"
        )

        # Show a message on the right
        self.status.showMessage("Video loaded. Next: Tools → Detect Scenes.", 5000)  

        self.scene_list.clear() # to clear previous detections
        self.status.showMessage(f"Imported: {basename}", 5000)  

        # enable Detect/Export now that a file is loaded
        self.set_actions_enabled(True)

    # Scene detection implementation
    def detect_scenes(self):
        # Run PySceneDetect and populate the scene list (will support v0.6 and v0.5).

        if not self.current_file:
            QMessageBox.information(self, "No File", "Please import a video first.")
            return
        if not SCENEDETECT_AVAILABLE:
            QMessageBox.critical(
                self, "Missing Library",
                "PySceneDetect not available.\nInstall with:\n  pip install scenedetect"
            )
            return

        self.status.showMessage("Detecting scenes... please wait.")
        QApplication.processEvents()    # keep UI responsive

        try:
            # --- Run detection for the appropriate API ---
            if SCENEDETECT_API == "v0.6+":
                video = open_video(self.current_file)          # v0.6+ path
                scene_manager = SceneManager()
                scene_manager.add_detector(ContentDetector(threshold=27.0))
                scene_manager.detect_scenes(video)
                scenes = scene_manager.get_scene_list()

            elif SCENEDETECT_API == "v0.5":
                video_manager = VideoManager([self.current_file])   # v0.5 path
                scene_manager = SceneManager()
                scene_manager.add_detector(ContentDetector(threshold=27.0))
                video_manager.set_downscale_factor()
                video_manager.start()
                scene_manager.detect_scenes(frame_source=video_manager)
                scenes = scene_manager.get_scene_list()
                video_manager.release()

            else:
                raise RuntimeError("Unsupported PySceneDetect API version.")

            # --- Update UI list ---
            self.current_scenes = scenes
            self.scene_list.clear()

            if not scenes:
                self.scene_list.addItem("No scenes detected.")
                self.status.showMessage("No scenes found.", 4000)
                return

            # Populate list with readable timecodes + 
            # checkable scene items and store(start_s, end_s)
            for i, (start, end) in enumerate(scenes, start=1):
                start_s = start.get_seconds()
                end_s = end.get_seconds()
                item_text = f"Scene {i}: {start_s:.2f}s → {end_s:.2f}s"
                item = QListWidgetItem(item_text)
                item.setCheckState(Qt.CheckState.Unchecked)                
                item.setData(Qt.ItemDataRole.UserRole, (start_s, end_s))  
                self.scene_list.addItem(item)

            self.status.showMessage(f"Detected {len(scenes)} scenes.", 5000)
            
        except Exception as e:
            QMessageBox.critical(self, "Detection Error", f"Failed to detect scenes:\n{e}")
            self.status.showMessage("Scene detection failed.", 5000)

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

    # transport helpers
    def _toggle_play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        else:
            self.player.play()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

    def _nudge(self, delta_sec: float):
        pos = max(0, min(self.player.position() + int(delta_sec * 1000), self._media_duration_ms))
        self.player.setPosition(pos)

    def _seek_to_ratio(self, val: int):
        # slider 0..1000 → position 0..duration
        if self._media_duration_ms > 0:
            target = int((val / 1000.0) * self._media_duration_ms)
            self.player.setPosition(target)

    def _on_duration(self, dur_ms: int):
        self._media_duration_ms = max(0, dur_ms)

    def _on_position(self, pos_ms: int):
        # keep slider synced with playback
        if self._media_duration_ms > 0:
            ratio = pos_ms / self._media_duration_ms
            self.seek.blockSignals(True)
            self.seek.setValue(int(ratio * 1000))
            self.seek.blockSignals(False)

    # seek to a scene's start on single click (don't autoplay)
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

    # seek & play on double click
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
        # Export all checked detected scenes to exports as MP4 clips using ffmpeg
        if not self.current_file:
            self.set_actions_enabled(False)
            QMessageBox.information(
                self, "Export Clips",
                "Please import a video first so I know what to export."
            )
            return

        if not self.current_scenes or self.scene_list.count() == 0:
            QMessageBox.information(self, "Export Clips", "No detected scenes found. Run detection first.")
            return
        
        # verify ffmpeg runs (uses imageio-ffmpeg’s binary if set)
        ffmpeg_bin = os.environ.get("IMAGEIO_FFMPEG_EXE") or "ffmpeg" 
        try:                                                          
            probe = subprocess.run([ffmpeg_bin, "-version"], capture_output=True, text=True)
            if probe.returncode != 0:
                raise RuntimeError("ffmpeg not runnable")
        except Exception:
            QMessageBox.critical(self, "Missing ffmpeg", "ffmpeg is not runnable. Reinstall imageio-ffmpeg or system ffmpeg.")
            return

        # Gather only the checked items
        selections = []  # (idx, start_s, end_s)  
        for idx in range(self.scene_list.count()):                                        
            item = self.scene_list.item(idx)                                              
            if item.checkState() == Qt.CheckState.Checked:                                
                start_s, end_s = item.data(Qt.ItemDataRole.UserRole)                     
                if (end_s - start_s) > 0.05:  # tiny guard for 0-length clips   
                    selections.append((idx, start_s, end_s))                               

        if not selections:                                                               
            QMessageBox.information(self, "Export Clips", "No scenes selected to export.")
            return     

        # clamp times into media duration to avoid out-of-range writes
        info = self.get_media_info(self.current_file)                  
        duration = float(info.get("duration", 0.0)) if info else 0.0   
        if duration <= 0.05:                                            
            QMessageBox.critical(self, "Export Clips", "Invalid media duration; cannot export.")  
            return                                                     

        clamped = [] 
        for idx, s, e in selections:                                   
            s2 = max(0.0, min(s, duration))                            
            e2 = max(0.0, min(e, duration))                             
            if e2 - s2 > 0.05:                                          
                clamped.append((idx, s2, e2))                          
        if not clamped:                                                 
            QMessageBox.information(self, "Export Clips", "Nothing to export after clamping times.") 
            return              

        self.status.showMessage("Exporting clips... please wait.")
        QApplication.processEvents()

        basename = os.path.splitext(os.path.basename(self.current_file))[0]
        export_dir = os.path.join(os.getcwd(), "exports")
        os.makedirs(export_dir, exist_ok=True)

        # check write permission before attempting
        if not os.access(export_dir, os.W_OK):                        
            QMessageBox.critical(self, "Export Clips", f"No write permission to:\n{export_dir}")  
            return                                           

        exported = 0
        errors = []

        for n, (idx, start_s, end_s) in enumerate(clamped, start=1): 
            out_path = os.path.join(export_dir, f"{basename}_scene_{n:02d}.mp4")
            ok, err = self._run_ffmpeg_slice(self.current_file, start_s, end_s, out_path)
            if ok:
                self.scene_list.item(idx).setText(                    
                    f"Exported Scene {n}: {start_s:.2f}s → {end_s:.2f}s"
                )
                exported += 1
            else:
                errors.append((n, start_s, end_s, err))  

        if exported > 0 and not errors:
            self.status.showMessage(f"Exported {exported} clip(s).", 6000)
            QMessageBox.information(self, "Export Complete", f"Exported {exported} scene(s) to:\n{export_dir}")
        elif exported > 0 and errors:
            n, s, e, err = errors[0]                                  
            self.status.showMessage(f"Exported {exported} clip(s), {len(errors)} failed.", 8000)
            QMessageBox.warning( 
                self,  
                "Export Partially Complete",
                f"Exported {exported} clip(s), {len(errors)} failed.\n"
                f"First failure (Scene {n} {s:.2f}s→{e:.2f}s):\n{err or '(no stderr)'}"
                )
        else:
            # show the actual ffmpeg stderr to make debugging easy
            hint = errors[0][3] if errors else "ffmpeg returned a non-zero code." 
            QMessageBox.critical(                                                  
                self,
                "Export Error",
                "No clips were exported.\n\n"
                f"ffmpeg stderr (first failure):\n{hint or '(no stderr)'}\n\n"
                f"Check write perms for:\n{export_dir}"
            )
            self.status.showMessage("Export failed.", 5000)

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
            "Aura Clip (PP4 R&D Build)\n\n"
            "Developed by Arianna Miller-Paul (Full Sail University)\n"
            "This app demonstrates the integration of PyQt6 + MoviePy + PySceneDetect."
        )
        print("Displayed About dialog.")


# --- Application Entry Point ---

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AuraClipApp()
    window.show()
    sys.exit(app.exec())
