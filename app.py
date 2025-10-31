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


class AuraClipApp(QMainWindow):
    """
    Main application window for Aura Clip.

    In this early version, it only contains:
    - Menu bar (Import, Detect, Export, Settings)
    - Central placeholder label
    - Status bar for showing messages

    As I progress through the project, I'll replace the placeholder
    label with our video player, detection results, and export controls.
    """

    def __init__(self):
        super().__init__()

        # --- Window Setup ---
        self.setWindowTitle("Aura Clip - Scene Detection R&D")
        self.setGeometry(200, 200, 900, 600)

        # --- Central Label ---
        # Placeholder until I add real UI elements.
        self.label = QLabel(
            "Welcome to Aura Clip\n\nUse the menu to Import, Detect, or Export."
        )
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(self.label)

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
        detect_action = tools_menu.addAction("Detect Scenes")
        detect_action.triggered.connect(self.detect_scenes)

        export_action = tools_menu.addAction("Export Clips")
        export_action.triggered.connect(self.export_clips)

        # Settings Menu
        settings_menu = menubar.addMenu("Settings")
        settings_action = settings_menu.addAction("Preferences")
        settings_action.triggered.connect(self.open_settings)

        # Help Menu
        help_menu = menubar.addMenu("Help")
        about_action = help_menu.addAction("About Aura Clip")
        about_action.triggered.connect(self.show_about)

        print("Aura Clip initialized successfully.")

    # --- Placeholder Actions ---

    def import_video(self):
        # Open a file dialog to select a local video file.
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", "Video Files (*.mp4 *.mov *.mkv *.avi)"
        )
        if file_path:
            self.status.showMessage(f"Imported: {os.path.basename(file_path)}", 5000)
            self.label.setText(f"Loaded file:\n{file_path}")
            print(f"Imported video: {file_path}")
        else:
            print("Import canceled by user.")

    def detect_scenes(self):
        # Placeholder for scene detection logic.
        QMessageBox.information(
            self, "Detect Scenes", "Scene detection will be added soon!"
        )
        print("Detect Scenes clicked (placeholder).")

    def export_clips(self):
        # Placeholder for export logic.
        QMessageBox.information(
            self, "Export Clips", "Export functionality will be added later!"
        )
        print("Export Clips clicked (placeholder).")

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
