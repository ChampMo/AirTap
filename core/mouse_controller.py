import time

import numpy as np
from pynput import mouse, keyboard
from typing import Optional

from .calibration import RotationCorrector


# MediaPipe hand-landmark index for the index-finger tip.
INDEX_FINGER_TIP = 8


def _detect_screen_size() -> tuple[int, int]:
    """
    Best-effort screen-resolution detection without a hard GUI dependency.

    Tries Windows ctypes first, then falls back to a 1920x1080 default so the
    module never crashes on a headless or unusual setup.
    """
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:
        return 1920, 1080


class MouseController:
    """
    Translates a single normalized hand landmark into smoothed OS cursor motion.

    The caller feeds per-frame landmark arrays via :meth:`update`; this class
    extracts the index-finger tip (landmark 8), applies an Exponential Moving
    Average (EMA) filter to suppress jitter, maps the normalized coordinate into
    screen space, and drives the cursor through pynput.

    A global Esc-key listener toggles an ``enabled`` flag so the user can
    instantly halt all cursor control (Emergency Stop).
    """

    def __init__(
        self,
        smoothing: float = 0.3,
        screen_width: Optional[int] = None,
        screen_height: Optional[int] = None,
        mirror_x: bool = True,
        rotation_angle: float = 0.0,
        boundary: tuple[float, float, float, float] = (0.0, 1.0, 0.0, 1.0),
        long_press_duration: float = 1.0,
    ) -> None:
        """
        Parameters
        ----------
        smoothing
            EMA factor in (0, 1]. This is the weight given to each *new* sample;
            lower values smooth more aggressively (more lag), higher values
            track more responsively (more jitter). 0.3 is a balanced default.
        screen_width, screen_height
            Target screen dimensions in pixels. Auto-detected when omitted.
        mirror_x
            Flip the X axis. A non-flipped webcam image is mirrored relative to
            the user, so flipping makes leftward hand motion move the cursor
            left. Set False if your capture pipeline already flips the frame.
        rotation_angle
            Top-Down calibration deviation theta (radians). Incoming coordinates
            are rotated by -theta to correct camera misalignment. Typically
            loaded from config on startup.
        boundary
            Active camera sub-rectangle as fractions ``(xmin, xmax, ymin, ymax)``
            of the frame. Landmarks are clamped to this box, then re-normalized so
            the box spans the full screen — motion outside it pins to a screen edge.
        """
        if not 0.0 < smoothing <= 1.0:
            raise ValueError("smoothing must be in the range (0, 1].")

        self._alpha = smoothing
        self._mirror_x = mirror_x
        self._corrector = RotationCorrector(rotation_angle)
        self._boundary = boundary

        detected_w, detected_h = _detect_screen_size()
        self._screen_w = screen_width if screen_width is not None else detected_w
        self._screen_h = screen_height if screen_height is not None else detected_h

        self._mouse = mouse.Controller()

        # EMA state in normalized [0, 1] space; None until the first sample.
        self._smooth_nx: Optional[float] = None
        self._smooth_ny: Optional[float] = None
        # Last pixel position written — memorized when sticky engages.
        self._last_pos: Optional[tuple[int, int]] = None

        # Sticky-mouse state for pinch-to-click: while sticky, the cursor is
        # frozen at _sticky_pos so the click lands where the pinch began.
        self._sticky: bool = False
        self._sticky_pos: Optional[tuple[int, int]] = None

        # Press-and-hold / drag state.
        self._long_press_duration = long_press_duration
        self._pinching: bool = False
        self._dragging: bool = False
        self._pinch_start: float = 0.0

        # Emergency-stop flag. True = cursor control active.
        self.enabled: bool = True

        self._key_listener: Optional[keyboard.Listener] = None

    # ------------------------------------------------------------------
    # Emergency Stop
    # ------------------------------------------------------------------

    def start_emergency_stop_listener(self) -> None:
        """Start the global keyboard listener for the Esc emergency toggle."""
        if self._key_listener is not None:
            return
        self._key_listener = keyboard.Listener(on_press=self._on_key_press)
        self._key_listener.start()

    def stop_emergency_stop_listener(self) -> None:
        if self._key_listener is not None:
            self._key_listener.stop()
            self._key_listener = None

    def _on_key_press(self, key) -> None:
        if key == keyboard.Key.esc:
            self.enabled = not self.enabled
            # Reset the filter so re-enabling doesn't snap from a stale point.
            if not self.enabled:
                self._smooth_x = None
                self._smooth_y = None

    # ------------------------------------------------------------------
    # Cursor control
    # ------------------------------------------------------------------

    def update(self, landmarks: np.ndarray) -> None:
        """
        Process one frame's landmarks and move the cursor accordingly.

        Parameters
        ----------
        landmarks
            A ``(21, 3)`` array of normalized x, y, z coordinates as produced by
            HandTracker. Ignored when control is disabled or the array is
            malformed.
        """
        if not self.enabled:
            return

        # Promote a held pinch into a drag: press the button once and release the
        # sticky freeze so the cursor can carry the dragged item.
        if self._pinching and not self._dragging:
            if (time.monotonic() - self._pinch_start) >= self._long_press_duration:
                self._mouse.press(mouse.Button.left)
                self._dragging = True
                self._sticky = False

        # Sticky mouse: during the pre-drag hold, freeze the cursor entirely —
        # skip both the EMA update and the mouse.position write.
        if self._sticky:
            return
        if landmarks is None or len(landmarks) <= INDEX_FINGER_TIP:
            return

        nx, ny = float(landmarks[INDEX_FINGER_TIP][0]), float(
            landmarks[INDEX_FINGER_TIP][1]
        )

        # Correct camera misalignment (Top-Down mode) before anything else,
        # since the deviation lives in raw camera space.
        nx, ny = self._corrector.apply(nx, ny)

        if self._mirror_x:
            nx = 1.0 - nx

        # Exponential Moving Average in normalized space: s_t = a*x + (1-a)*s_{t-1}
        # EMA smoothing is maintained here for both plain motion and dragging.
        if self._smooth_nx is None or self._smooth_ny is None:
            self._smooth_nx, self._smooth_ny = nx, ny
        else:
            self._smooth_nx = self._alpha * nx + (1 - self._alpha) * self._smooth_nx
            self._smooth_ny = self._alpha * ny + (1 - self._alpha) * self._smooth_ny

        px, py = self._to_screen(self._smooth_nx, self._smooth_ny)
        self._last_pos = (px, py)
        self._mouse.position = (px, py)

    def _to_screen(self, nx: float, ny: float) -> tuple[int, int]:
        """Clamp normalized coords to the boundary box, re-normalize, map to px."""
        xmin, xmax, ymin, ymax = self._boundary
        span_x = max(xmax - xmin, 1e-6)
        span_y = max(ymax - ymin, 1e-6)
        cx = min(max(nx, xmin), xmax)
        cy = min(max(ny, ymin), ymax)
        mapped_x = (cx - xmin) / span_x
        mapped_y = (cy - ymin) / span_y
        px = min(int(mapped_x * self._screen_w), self._screen_w - 1)
        py = min(int(mapped_y * self._screen_h), self._screen_h - 1)
        return px, py

    def map_to_screen(self, nx: float, ny: float) -> tuple[int, int]:
        """
        Map a raw normalized landmark to a screen pixel using the same pipeline
        as the cursor (rotation, mirror, boundary clamp) but without EMA. Used
        for fingertip dots and keyboard grab-dragging.
        """
        nx, ny = self._corrector.apply(nx, ny)
        if self._mirror_x:
            nx = 1.0 - nx
        return self._to_screen(nx, ny)

    # ------------------------------------------------------------------
    # Pinch: click, press-and-hold, drag
    # ------------------------------------------------------------------

    def pinch_down(self) -> None:
        """
        A pinch began. Freeze the cursor (sticky) and start the hold timer. A
        quick release fires a click; holding past long_press_duration becomes a
        drag (see update()).
        """
        if self._pinching:
            return
        self._pinching = True
        self._dragging = False
        self._pinch_start = time.monotonic()
        self._sticky = True
        self._sticky_pos = self._last_pos or self._mouse.position

    def pinch_up(self) -> None:
        """
        The pinch ended. Release a drag, or fire a single click for a quick
        pinch. The button release always happens (even under emergency stop) so
        a drag can never get stuck down; the click respects the enabled flag.
        """
        if not self._pinching:
            return
        if self._dragging:
            self._mouse.release(mouse.Button.left)
        elif self.enabled:
            pos = self._sticky_pos or self._last_pos or self._mouse.position
            self._mouse.position = (int(pos[0]), int(pos[1]))
            self._mouse.click(mouse.Button.left, 1)
        self._pinching = False
        self._dragging = False
        self._sticky = False
        self._sticky_pos = None

    @property
    def is_dragging(self) -> bool:
        return self._dragging

    @property
    def sticky_position(self) -> Optional[tuple[int, int]]:
        """The frozen click position, or None when not sticky."""
        return self._sticky_pos

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_boundary(self, boundary: tuple[float, float, float, float]) -> None:
        """Update the active camera box (xmin, xmax, ymin, ymax fractions)."""
        self._boundary = boundary

    def set_smoothing(self, smoothing: float) -> None:
        """Update the EMA factor at runtime (e.g. from a settings slider)."""
        if not 0.0 < smoothing <= 1.0:
            raise ValueError("smoothing must be in the range (0, 1].")
        self._alpha = smoothing

    def set_rotation_angle(self, theta: float) -> None:
        """Apply a new Top-Down calibration angle (e.g. after recalibration)."""
        self._corrector.set_angle(theta)
        self.reset_filter()

    def reset_filter(self) -> None:
        """Clear EMA state so the next sample is taken verbatim."""
        self._smooth_nx = None
        self._smooth_ny = None
