from PyQt6.QtCore import Qt, QRectF, QRect, QTimer, QPoint, QPointF
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QWidget
from typing import Optional


# Logical layout. Special keys carry a display glyph; their typed action is
# resolved by the caller (see AppController._type_key).
_ROWS = [
    list("QWERTYUIOP"),
    list("ASDFGHJKL"),
    list("ZXCVBNM"),
    ["⌫", "SPACE", "⏎"],
]

# Relative widths within a row (most keys = 1 unit; space bar is wide).
_WIDE = {"SPACE": 6.0, "⌫": 2.0, "⏎": 2.0}

# Fingertip dot colour — neon orange, complementing the skeleton's neon blue.
_NEON_ORANGE = QColor(255, 140, 30)


class VirtualKeyboard(QWidget):
    """
    Frameless, modern light-theme QWERTY overlay rendered with QPainter.

    Styled after the Windows touch keyboard: a light title bar with a label and
    a (cosmetic) close glyph, off-white rounded keycaps, high-contrast black
    text, and an accent-blue flash on the tapped key. It is click-through (taps
    are resolved by hit-testing the cursor, not Qt mouse events) and can be
    positioned within the configured boundary or grab-dragged by the caller.
    """

    KEY_GAP = 8
    PAD = 16
    TITLE_H = 38
    HIGHLIGHT_MS = 160

    # Palette (light theme).
    PANEL_BG = QColor(232, 234, 237, 240)
    TITLE_BG = QColor(245, 246, 248, 245)
    KEYCAP_BG = QColor(252, 252, 253, 255)
    KEYCAP_BORDER = QColor(208, 211, 215)
    KEY_TEXT = QColor(26, 26, 26)
    ACCENT = QColor(45, 108, 255)
    TITLE_TEXT = QColor(60, 64, 72)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.resize(820, 320)

        self._key_rects: dict[str, QRectF] = {}
        self._active_key: Optional[str] = None
        self._fingertips: list[tuple[int, int]] = []  # global screen points

        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.timeout.connect(self._clear_highlight)

    # ------------------------------------------------------------------
    # Visibility / positioning
    # ------------------------------------------------------------------

    def show_in_boundary(self, config) -> None:
        """
        Show docked at the bottom of the boundary box, spanning its width. The
        boundary is stored as camera-frame fractions; we apply them to the
        primary screen so the keyboard lands inside the red box region.
        """
        screen = QGuiApplication.primaryScreen().geometry()
        xmin = float(config.get("boundary_xmin", 0.1))
        xmax = float(config.get("boundary_xmax", 0.9))
        ymax = float(config.get("boundary_ymax", 0.9))

        box_w = max(int((xmax - xmin) * screen.width()), 480)
        self.resize(box_w, self.height())

        x = screen.x() + int(xmin * screen.width())
        y = screen.y() + int(ymax * screen.height()) - self.height() - 16
        y = max(screen.y(), y)
        self.move(x, y)
        self.show()
        self.raise_()

    def move_center(self, global_x: int, global_y: int) -> None:
        """Move the window so its centre sits at a global point (clamped)."""
        screen = QGuiApplication.primaryScreen().geometry()
        w, h = self.width(), self.height()
        x = min(max(global_x - w // 2, screen.x()), screen.x() + screen.width() - w)
        y = min(max(global_y - h // 2, screen.y()), screen.y() + screen.height() - h)
        self.move(x, y)

    # ------------------------------------------------------------------
    # Hit testing / feedback
    # ------------------------------------------------------------------

    def key_at(self, global_pos: QPoint) -> Optional[str]:
        """Return the key label under a global (screen) point, or None."""
        local = self.mapFromGlobal(global_pos)
        lx, ly = float(local.x()), float(local.y())
        for label, rect in self._key_rects.items():
            if rect.contains(lx, ly):
                return label
        return None

    def flash_key(self, label: str) -> None:
        """Briefly highlight a key in accent blue (confirms a tap)."""
        self._active_key = label
        self.update()
        self._highlight_timer.start(self.HIGHLIGHT_MS)

    def _clear_highlight(self) -> None:
        self._active_key = None
        self.update()

    def update_fingertips(self, global_points: list[tuple[int, int]]) -> None:
        """Set the glowing fingertip points (global screen coords) to draw."""
        self._fingertips = global_points
        self.update()

    # ------------------------------------------------------------------
    # Layout + painting
    # ------------------------------------------------------------------

    def resizeEvent(self, _event) -> None:
        self._recompute_layout()

    def _recompute_layout(self) -> None:
        self._key_rects.clear()
        top = self.TITLE_H + self.PAD
        usable_w = self.width() - 2 * self.PAD
        usable_h = self.height() - top - self.PAD
        row_h = (usable_h - self.KEY_GAP * (len(_ROWS) - 1)) / len(_ROWS)

        for r, row in enumerate(_ROWS):
            units = sum(_WIDE.get(k, 1.0) for k in row)
            gaps = self.KEY_GAP * (len(row) - 1)
            unit_w = (usable_w - gaps) / units

            x = self.PAD
            y = top + r * (row_h + self.KEY_GAP)
            for label in row:
                w = unit_w * _WIDE.get(label, 1.0)
                self._key_rects[label] = QRectF(x, y, w, row_h)
                x += w + self.KEY_GAP

    def paintEvent(self, _event) -> None:
        if not self._key_rects:
            self._recompute_layout()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = self.width(), self.height()

        # Panel.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.PANEL_BG)
        painter.drawRoundedRect(QRectF(0, 0, w, h), 14, 14)

        self._paint_title_bar(painter, w)
        self._paint_keys(painter)
        self._paint_fingertips(painter, w, h)

        painter.end()

    def _paint_title_bar(self, painter: QPainter, w: int) -> None:
        # Rounded top strip acting as the title bar / move handle.
        bar = QRectF(0, 0, w, self.TITLE_H + 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.TITLE_BG)
        painter.drawRoundedRect(bar, 14, 14)
        # Square off the bottom of the strip so only the top is rounded.
        painter.drawRect(QRectF(0, self.TITLE_H, w, 12))

        painter.setPen(QPen(self.TITLE_TEXT))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(14, 0, w - 28, self.TITLE_H),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "AirTap Keyboard",
        )
        # Cosmetic close glyph (hide is gesture-driven: two-hand fist).
        painter.drawText(
            QRectF(w - 38, 0, 24, self.TITLE_H),
            Qt.AlignmentFlag.AlignCenter,
            "✕",
        )

    def _paint_keys(self, painter: QPainter) -> None:
        painter.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        for label, rect in self._key_rects.items():
            active = label == self._active_key
            if active:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self.ACCENT)
            else:
                painter.setPen(QPen(self.KEYCAP_BORDER, 1))
                painter.setBrush(self.KEYCAP_BG)
            painter.drawRoundedRect(rect, 7, 7)

            painter.setPen(QColor(255, 255, 255) if active else self.KEY_TEXT)
            text = "space" if label == "SPACE" else label
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_fingertips(self, painter: QPainter, w: int, h: int) -> None:
        if not self._fingertips:
            return
        bounds = QRect(0, 0, w, h)
        painter.setPen(Qt.PenStyle.NoPen)
        for gx, gy in self._fingertips:
            local = self.mapFromGlobal(QPoint(int(gx), int(gy)))
            if not bounds.contains(local):
                continue
            center = QPointF(local)
            radius = 12.0
            gradient = QRadialGradient(center, radius)
            inner = QColor(_NEON_ORANGE)
            inner.setAlpha(235)
            outer = QColor(_NEON_ORANGE)
            outer.setAlpha(0)
            gradient.setColorAt(0.0, inner)
            gradient.setColorAt(1.0, outer)
            painter.setBrush(QBrush(gradient))
            painter.drawEllipse(center, radius, radius)
