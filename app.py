"""
Aura Clip - Base Application Window

"""

# --- Library Imports ---
# Import QApplication and QMainWindow to create the base window.
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QLabel,
    QStatusBar,
    QMenuBar,
    QFileDialog,
    QMessageBox,
    QWidget,
    QHBoxLayout,
    QListWidget,        
    QListWidgetItem,
)
import sys
import os

SCENEDETECT_AVAILABLE = False              # ✅ FIX
SCENEDETECT_API = None  
# Importing scenedetect safely
try:
    # v0.6+ API
    from scenedetect import SceneManager, open_video        # ✅ FIX
    from scenedetect.detectors import ContentDetector       # ✅ FIX
    SCENEDETECT_AVAILABLE = True                            # ✅ FIX
    SCENEDETECT_API = "v0.6+"                               # ✅ FIX
except Exception:
    try:
        # v0.5.x Legacy API
        from scenedetect import VideoManager, SceneManager  # ✅ FIX
        from scenedetect.detectors import ContentDetector   # ✅ FIX
        SCENEDETECT_AVAILABLE = True                        # ✅ FIX
        SCENEDETECT_API = "v0.5"                            # ✅ FIX
    except Exception:
        # Leave SCENEDETECT_AVAILABLE=False / SCENEDETECT_API=None
        pass          

# import VideoFileClip the moviepy package as a namespace and detect availability
try:
    from moviepy.video.io.VideoFileClip import VideoFileClip              
    MOVIEPY_AVAILABLE = True 
except Exception:
    VideoFileClip = None                          
    MOVIEPY_AVAILABLE = False          

class AuraClipApp(QMainWindow):
    
    def __init__(self):
        super().__init__()

        # --- Window Setup ---
        self.setWindowTitle("Aura Clip - Scene Detection R&D")
        self.setGeometry(200, 200, 900, 600)

        # Track the currently selected file path in memory
        self.current_file: str | None = None
        self.current_scenes: list | None = None

         # Create a main container widget with horizontal layout
        self.container = QWidget(self)                      
        self.layout = QHBoxLayout(self.container)                    
        self.container.setLayout(self.layout)                  
        self.setCentralWidget(self.container)           

        # Create a left info panel (QLabel)
        self.info_label = QLabel("No file loaded.", self.container) 
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignTop)  
        self.info_label.setFixedWidth(260)        
        self.layout.addWidget(self.info_label) 

        # Right side = scene list instead of just a message label
        self.scene_list = QListWidget(self.container)           
        self.scene_list.setFixedWidth(300)                  
        self.layout.addWidget(self.scene_list)                 
         

        # --- Central Label ---
        # central message label in between 
        self.main_label = QLabel("Welcome to Aura Clip\n\nUse the menu to Import, Detect, or Export.")
        self.main_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.insertWidget(1, self.main_label, stretch=1)

        # --- Status Bar ---
        # Displays messages to the user, such as file loaded or task complete.
        self.status = QStatusBar(self)
        self.setStatusBar(self.status)

        # --- Menu Bar ---
        # The menu bar gives us structured access to actions.
        menubar = QMenuBar(self)
        self.setMenuBar(menubar)

        # File Menu (Import + Exit)
        file_menu = menubar.addMenu("File")

        # Add actions
        import_action = file_menu.addAction("Import Video")
        import_action.triggered.connect(self.import_video)

        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

        # Tools Menu (Detect / Export)
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

    # Small helper to enable/disable both actions at once
    def set_actions_enabled(self, loaded: bool) -> None:
        self.detect_action.setEnabled(loaded) 
        self.export_action.setEnabled(loaded)  

    # small helper to extract media info with MoviePy
    # use namespaced class mp.VideoFileClip so the name always exists
    def get_media_info(self, file_path: str) -> dict:  
        """
        Return a dict with duration (s), fps, and resolution (w, h).
        MoviePy opens the file briefly to read metadata.
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
            # Keep it simple for now: show an error message and return empty info.
            QMessageBox.critical(self, "Media Error", f"Could not read media info:\n{e}")
            return {"duration": 0.0, "fps": 0.0, "width": 0, "height": 0}    

    # --- Actions ---

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

        # Show a friendlier message on the right
        self.main_label.setText(                            
            "Video loaded successfully.\n\n"
            "Next: choose 'Tools > Detect Scenes' to test detection."
        )

        self.scene_list.clear() # to clear previous detections
        self.status.showMessage(f"Imported: {basename}", 5000)  

        # enable Detect/Export now that a file is loaded
        self.set_actions_enabled(True)

    # Scene detection implementation
    def detect_scenes(self):
        # Run PySceneDetect and populate the scene list (will support v0.6+ and v0.5.x).
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

            # Populate list with readable timecodes
            for i, (start, end) in enumerate(scenes, start=1):
                start_s = start.get_seconds()
                end_s = end.get_seconds()
                item_text = f"Scene {i}: {start_s:.2f}s → {end_s:.2f}s"
                self.scene_list.addItem(QListWidgetItem(item_text))

            self.status.showMessage(f"Detected {len(scenes)} scenes.", 5000)
            self.main_label.setText("Scenes detected! Review them on the right panel.")

        except Exception as e:
            QMessageBox.critical(self, "Detection Error", f"Failed to detect scenes:\n{e}")
            self.status.showMessage("Scene detection failed.", 5000)

    def export_clips(self):
        if not self.current_file:
            self.set_actions_enabled(False)
            QMessageBox.information(
                self, 
                "Export Clips", 
                "Please import a video first so I know what to export."
            )
            return
        
        QMessageBox.information(
            self, "Export Clips", "Export functionality will be added later!"
        )

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
            "Developed by Arianna Miller (Full Sail University)\n"
            "This app demonstrates the integration of PyQt6 + MoviePy + PySceneDetect."
        )
        print("Displayed About dialog.")


# --- Application Entry Point ---

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AuraClipApp()
    window.show()
    sys.exit(app.exec())
