from dataclasses import dataclass
from enum import Enum, auto

class DetectionMode(Enum):
    MANUAL = auto()          # user-only cuts (future); detects nothing
    PYSDETECT = auto()       # current, stable path: PySceneDetect
    AI_EXPERIMENTAL = auto() # placeholder for Iteration 3 model

@dataclass
class AppSettings:
    detection_mode: DetectionMode = DetectionMode.PYSDETECT

# a shared, simple settings object for now
settings = AppSettings()
