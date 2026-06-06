import json
import os
from pathlib import Path
from typing import Any


# Default configuration. Mirrors the tunables exposed in the settings UI.
DEFAULTS: dict[str, Any] = {
    "cursor_smoothing": 0.30,   # EMA weight, range (0, 1]
    "camera_index": 0,
    "max_hands": 1,
    "mirror_x": True,
    "rotation_angle": 0.0,      # Top-Down calibration deviation theta, radians
    "mode": "front",            # tracking mode: "front" | "topdown"
    "tap_threshold": 0.70,      # Z-velocity tap threshold (lower = more sensitive)
    "enable_keyboard": True,    # allow the two-hand virtual keyboard gesture
    "auto_hide_widget": True,   # fade the floating status widget when idle
    "widget_mode": "skeleton",  # floating widget: "minimal" | "skeleton" | "full"
    "skeleton_opacity": 0.90,   # floating skeleton opacity, range [0, 1]
    "sniper_speed_reduction": 0.50,  # precision-mode slowdown, range [0, 1]
    "long_press_duration": 1.0,  # seconds a pinch must hold to become a drag
    "flip_vertical": False,      # flip the camera frame top/bottom (Top-Down)
    "flip_horizontal": False,    # flip the camera frame left/right (Top-Down)
    # Active boundary as fractions of the full camera frame. Landmarks are
    # clamped to this sub-rectangle, then re-normalized to drive the full screen.
    "boundary_xmin": 0.10,
    "boundary_xmax": 0.90,
    "boundary_ymin": 0.10,
    "boundary_ymax": 0.90,
}


class ConfigManager:
    """
    Tiny JSON-backed settings store with instant, popup-free persistence.

    Loads ``config.json`` on construction (creating it from DEFAULTS if absent),
    and writes to disk on every :meth:`set` so UI changes survive a restart with
    no explicit save step.
    """

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        if path is None:
            # Project-root config.json, next to this package.
            path = Path(__file__).resolve().parent.parent / "config.json"
        self._path = Path(path)
        self._data: dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                # Merge so new DEFAULTS keys appear for old config files.
                self._data.update(
                    {k: v for k, v in stored.items() if k in DEFAULTS}
                )
            except (json.JSONDecodeError, OSError):
                # Corrupt or unreadable: fall back to defaults and rewrite.
                self._data = dict(DEFAULTS)
        self.save()

    def save(self) -> None:
        """Atomically write the current config to disk."""
        tmp = self._path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, self._path)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Update a key and immediately persist (instant-save)."""
        self._data[key] = value
        self.save()
