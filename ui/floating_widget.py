import time

from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen, QRadialGradient, QBrush
from PyQt6.QtWidgets import QWidget


# MediaPipe hand topology: pairs of landmark indices that form bones.
HAND_CONNECTIONS = [
    # Thumb
    (0, 1), (1, 2), (2, 3), (3, 4),
    # Index
    (0, 5), (5, 6), (6, 7), (7, 8),
    # Middle
    (5, 9), (9, 10), (10, 11), (11, 12),
    # Ring
    (9, 13), (13, 14), (14, 15), (15, 16),
    # Pinky
    (13, 17), (17, 18), (18, 19), (19, 20),
    # Palm base
    (0, 17),
]

# Fingertip landmarks get the accent colour for emphasis.
FINGERTIPS = {4, 8, 12, 16, 20}

NEON_BLUE = QColor(40, 170, 255)
NEON_ORANGE = QColor(255, 140, 30)


class FloatingWidget(QWidget):
    """
    Frameless, transparent, always-on-top overlay that paints a glowing hand
    skeleton from CVThread landmark data.

    No video frame is ever rendered — only QPainter vector strokes — to keep the
    overlay lightweight. When no hand has been seen for ``HOLD_MS`` the widget
    gradually fades to invisible, then snaps back to full opacity on the next
    detection.
    """

    HOLD_MS = 3000      # full visibility window after the last detection
    FADE_MS = 600       # fade-out duration once the hold expires
    TICK_MS = 33        # ~30 FPS housekeeping/repaint cadence

    def __init__(self, mirror_x: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._mirror_x = mirror_x

        # Each entry is an (21, 3) array-like of normalized landmark coords.
        self._hands: list = []
        self._last_seen: float = 0.0  # monotonic timestamp of last detection

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool                       # keep off the taskbar
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWindowOpacity(0.0)

        self.resize(280, 220)

        # Drive fade + repaint on a steady timer rather than per-frame paints.
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------------
    # CVThread integration
    # ------------------------------------------------------------------

    def on_landmarks(self, hands: list) -> None:
        """
        Slot for ``CVThread.landmarks_ready``.

        ``hands`` is a list of HandLandmarks (or empty). We only stash the raw
        coordinate arrays; painting happens on the timer tick.
        """
        if hands:
            # Accept either HandLandmarks objects or raw arrays defensively.
            self._hands = [
                getattr(h, "landmarks", h) for h in hands
            ]
            self._last_seen = time.monotonic()
        else:
            self._hands = []

    def set_mirror_enabled(self, enabled: bool) -> None:
        """Match the preview's mirror so the skeleton reads the same way."""
        self._mirror_x = enabled

    # ------------------------------------------------------------------
    # Fade / opacity housekeeping
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        # _last_seen only advances when a hand is present, so elapsed time
        # since it is a direct measure of how long we've been hand-less.
        elapsed_ms = (time.monotonic() - self._last_seen) * 1000.0

        if elapsed_ms <= self.HOLD_MS:
            target = 1.0
        elif elapsed_ms >= self.HOLD_MS + self.FADE_MS:
            target = 0.0
        else:
            # Linear ramp from 1 -> 0 across the fade window.
            into_fade = elapsed_ms - self.HOLD_MS
            target = 1.0 - (into_fade / self.FADE_MS)

        if abs(self.windowOpacity() - target) > 0.001:
            self.setWindowOpacity(max(0.0, min(1.0, target)))

        # Only repaint while something is visible.
        if self.windowOpacity() > 0.0:
            self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        if not self._hands or self.windowOpacity() <= 0.0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = self.width(), self.height()
        pad = 24  # inset so glowing strokes near edges aren't clipped

        for landmarks in self._hands:
            points = self._to_pixels(landmarks, w, h, pad)
            self._draw_skeleton(painter, points)

        painter.end()

    def _to_pixels(self, landmarks, w: int, h: int, pad: int) -> list[QPointF]:
        usable_w = w - 2 * pad
        usable_h = h - 2 * pad
        points: list[QPointF] = []
        for lm in landmarks:
            nx, ny = float(lm[0]), float(lm[1])
            if self._mirror_x:
                nx = 1.0 - nx
            nx = min(max(nx, 0.0), 1.0)
            ny = min(max(ny, 0.0), 1.0)
            points.append(QPointF(pad + nx * usable_w, pad + ny * usable_h))
        return points

    def _draw_skeleton(self, painter: QPainter, points: list[QPointF]) -> None:
        if len(points) < 21:
            return

        # --- Bones: a wide soft glow underlay, then a bright core line. ---
        glow_pen = QPen(QColor(NEON_BLUE.red(), NEON_BLUE.green(),
                               NEON_BLUE.blue(), 70))
        glow_pen.setWidth(9)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        core_pen = QPen(QColor(150, 220, 255, 235))
        core_pen.setWidth(3)
        core_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        core_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        for pen in (glow_pen, core_pen):
            painter.setPen(pen)
            for a, b in HAND_CONNECTIONS:
                painter.drawLine(points[a], points[b])

        # --- Joints: glowing dots, fingertips accented in neon orange. ---
        painter.setPen(Qt.PenStyle.NoPen)
        for idx, pt in enumerate(points):
            color = NEON_ORANGE if idx in FINGERTIPS else NEON_BLUE
            radius = 7.0 if idx in FINGERTIPS else 5.0
            self._draw_glow_dot(painter, pt, radius, color)

    def _draw_glow_dot(
        self, painter: QPainter, center: QPointF, radius: float, color: QColor
    ) -> None:
        gradient = QRadialGradient(center, radius)
        inner = QColor(color)
        inner.setAlpha(255)
        outer = QColor(color)
        outer.setAlpha(0)
        gradient.setColorAt(0.0, inner)
        gradient.setColorAt(1.0, outer)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(center, radius, radius)
