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
)
import sys
import os

# import the moviepy package as a namespace and detect availability
try:
    import moviepy as mp               
    MOVIEPY_AVAILABLE = hasattr(mp, "VideoFileClip")  
except Exception:
    mp = None                          
    MOVIEPY_AVAILABLE = False          

class AuraClipApp(QMainWindow):
    
    def __init__(self):
        super().__init__()

        # --- Window Setup ---
        self.setWindowTitle("Aura Clip - Scene Detection R&D")
        self.setGeometry(200, 200, 900, 600)

        # Track the currently selected file path in memory
        self.current_file: str | None = None

        # --- Central Label ---
        # Placeholder until I add real UI elements.
        msg = "Welcome to Aura Clip\n\nUse the menu to Import, Detect, or Export."
        if not MOVIEPY_AVAILABLE:  
            msg += (
                "\n\n(MoviePy not detected. Install with:\n"
                "  python -m pip install moviepy imageio imageio-ffmpeg numpy)"
            )
        self.label = QLabel(msg)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(self.label)

        if not MOVIEPY_AVAILABLE:  
            msg += (
                "\n\n(MoviePy not detected. Install with:\n"
                "  python -m pip install moviepy imageio imageio-ffmpeg numpy)"
            )

        # --- Status Bar ---
        # Displays messages to the user, such as file loaded or task complete.
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        # --- Menu Bar ---
        # The menu bar gives us structured access to actions.
        menubar = QMenuBar()
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

        try:
            with mp.VideoFileClip(file_path) as clip:
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
        self.label.setText(                    
            f"Loaded file:\n{basename}\n\n"
            f"Duration: {duration_s}s\n"
            f"FPS: {fps}\n"
            f"Resolution: {w} x {h}"
        )
        self.status.showMessage(f"Imported: {basename}", 5000)  

        # enable Detect/Export now that a file is loaded
        self.set_actions_enabled(True)

    def detect_scenes(self):
        # Placeholder for scene detection logic.
        QMessageBox.information(
            self, "Detect Scenes", "Scene detection will be added soon!"
        )
        print("Detect Scenes clicked (placeholder).")

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
