from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap, QRadialGradient
from PyQt6.QtMultimedia import QMediaDevices
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.config import ConfigManager
from .styles import LIGHT_THEME


# The smoothing config value lives in (0, 1]; the slider works in integer
# percent. These helpers convert between the two representations.
def _smoothing_to_slider(value: float) -> int:
    return max(1, min(100, round(value * 100)))


def _slider_to_smoothing(value: int) -> float:
    return value / 100.0


# Tap "sensitivity" runs opposite to the raw Z-velocity threshold: a high
# sensitivity means a low threshold (easier to trigger). These map the 1-100
# slider onto the threshold's usable range.
_TAP_MIN, _TAP_MAX = 0.20, 1.50


def _sensitivity_to_threshold(value: int) -> float:
    frac = (value - 1) / 99.0
    return round(_TAP_MAX - frac * (_TAP_MAX - _TAP_MIN), 3)


def _threshold_to_sensitivity(threshold: float) -> int:
    frac = (_TAP_MAX - threshold) / (_TAP_MAX - _TAP_MIN)
    return max(1, min(100, round(frac * 99) + 1))


# MediaPipe hand topology for drawing the skeleton onto the preview frame.
_HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),          # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),          # index
    (5, 9), (9, 10), (10, 11), (11, 12),     # middle
    (9, 13), (13, 14), (14, 15), (15, 16),   # ring
    (13, 17), (17, 18), (18, 19), (19, 20),  # pinky
    (0, 17),                                  # palm base
]
_FINGERTIPS = {4, 8, 12, 16, 20}
_NEON_BLUE = QColor(40, 170, 255)
_NEON_ORANGE = QColor(255, 140, 30)


def draw_skeleton_on_image(image: QImage, hands: list, mirror_x: bool) -> None:
    """
    Paint neon skeletons directly onto ``image`` (in place).

    Landmarks are normalized 0-1 against the full camera frame, so scaling by
    the image's own pixel size yields a perfectly aligned overlay. When the
    preview is mirrored, X is flipped to match the flipped frame.
    """
    if not hands:
        return

    w, h = image.width(), image.height()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    for hand in hands:
        landmarks = getattr(hand, "landmarks", hand)
        if len(landmarks) < 21:
            continue

        points: list[QPointF] = []
        for lm in landmarks:
            nx = float(lm[0])
            if mirror_x:
                nx = 1.0 - nx
            points.append(QPointF(nx * w, float(lm[1]) * h))

        # Bones: soft wide glow underlay, then a bright thin core line.
        glow = QPen(QColor(_NEON_BLUE.red(), _NEON_BLUE.green(), _NEON_BLUE.blue(), 70))
        glow.setWidth(8)
        glow.setCapStyle(Qt.PenCapStyle.RoundCap)
        core = QPen(QColor(150, 220, 255, 235))
        core.setWidth(2)
        core.setCapStyle(Qt.PenCapStyle.RoundCap)
        for pen in (glow, core):
            painter.setPen(pen)
            for a, b in _HAND_CONNECTIONS:
                painter.drawLine(points[a], points[b])

        # Joints: glowing dots, fingertips accented in neon orange.
        painter.setPen(Qt.PenStyle.NoPen)
        for idx, pt in enumerate(points):
            color = _NEON_ORANGE if idx in _FINGERTIPS else _NEON_BLUE
            radius = 6.0 if idx in _FINGERTIPS else 4.0
            gradient = QRadialGradient(pt, radius)
            inner = QColor(color)
            inner.setAlpha(255)
            outer = QColor(color)
            outer.setAlpha(0)
            gradient.setColorAt(0.0, inner)
            gradient.setColorAt(1.0, outer)
            painter.setBrush(QBrush(gradient))
            painter.drawEllipse(pt, radius, radius)

    painter.end()


class BoundaryOverlay(QWidget):
    """
    Transparent overlay drawn on top of the camera preview that traces the
    active screen-area boundary (the red rectangle) from config percentages.
    """

    def __init__(self, config: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def refresh(self) -> None:
        """Repaint after the boundary config changes."""
        self.update()

    def paintEvent(self, _event) -> None:
        xmin = float(self._config.get("boundary_xmin", 0.1))
        xmax = float(self._config.get("boundary_xmax", 0.9))
        ymin = float(self._config.get("boundary_ymin", 0.1))
        ymax = float(self._config.get("boundary_ymax", 0.9))

        w, h = self.width(), self.height()
        rect = QRectF(xmin * w, ymin * h, (xmax - xmin) * w, (ymax - ymin) * h)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Faint, semi-transparent red so it doesn't dominate the preview.
        pen = QPen(QColor(255, 0, 0, 50), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        painter.end()


class MainWindow(QWidget):
    """AirDesk settings window: sidebar navigation + stacked content panes."""

    # Emitted (with the new camera index) when the user picks a different camera.
    camera_changed = pyqtSignal(int)
    # Emitted with the new mirror state when the tracking mode changes.
    mirror_changed = pyqtSignal(bool)
    # Emitted with the new vertical-flip state.
    flip_changed = pyqtSignal(bool)
    # Emitted with the new horizontal-flip state.
    flip_h_changed = pyqtSignal(bool)

    NAV_ITEMS = ["Dashboard", "Movement", "Gestures", "Widget"]

    def __init__(self, config: ConfigManager | None = None) -> None:
        super().__init__()
        self.config = config or ConfigManager()

        # Most recent landmarks, drawn onto the next preview frame.
        self._latest_hands: list = []

        self.setObjectName("MainWindow")
        self.setWindowTitle("AirDesk")
        self.resize(840, 560)
        self.setStyleSheet(LIGHT_THEME)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_content(), stretch=1)

        # Open on Dashboard.
        self._nav_buttons[0].setChecked(True)
        self.stack.setCurrentIndex(0)

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(200)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 20, 12, 20)
        layout.setSpacing(6)

        title = QLabel("AirDesk")
        title.setObjectName("AppTitle")
        layout.addWidget(title)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []

        for index, name in enumerate(self.NAV_ITEMS):
            btn = QPushButton(name)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, i=index: self.stack.setCurrentIndex(i))
            self._nav_group.addButton(btn, index)
            self._nav_buttons.append(btn)
            layout.addWidget(btn)

        layout.addStretch(1)
        return sidebar

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def _build_content(self) -> QWidget:
        container = QWidget()
        container.setObjectName("ContentArea")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(32, 28, 32, 28)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        self.stack.addWidget(self._build_dashboard_page())
        self.stack.addWidget(self._build_movement_page())
        self.stack.addWidget(self._build_gestures_page())
        self.stack.addWidget(self._build_widget_page())

        return container

    # ------------------------------------------------------------------
    # Shared page helpers
    # ------------------------------------------------------------------

    def _page_scaffold(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        """Build a page with a title + subtitle header; return (page, layout)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        sub = QLabel(subtitle)
        sub.setObjectName("PageHint")
        layout.addWidget(heading)
        layout.addWidget(sub)
        layout.addSpacing(24)
        return page, layout

    def _add_slider_section(
        self,
        layout: QVBoxLayout,
        title: str,
        helper_text: str,
        init_value: int,
        on_change,
    ) -> tuple[QSlider, QLabel]:
        """Append a labelled 1-100 slider row with a live value badge."""
        label_row = QHBoxLayout()
        setting_label = QLabel(title)
        setting_label.setObjectName("SettingLabel")
        badge = QLabel(f"{init_value}%")
        badge.setObjectName("ValueBadge")
        label_row.addWidget(setting_label)
        label_row.addStretch(1)
        label_row.addWidget(badge)
        layout.addLayout(label_row)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(1)
        slider.setMaximum(100)
        slider.setValue(init_value)
        slider.setCursor(Qt.CursorShape.PointingHandCursor)
        slider.valueChanged.connect(lambda v: badge.setText(f"{v}%"))
        slider.valueChanged.connect(on_change)
        layout.addWidget(slider)

        helper = QLabel(helper_text)
        helper.setObjectName("MutedText")
        layout.addWidget(helper)
        return slider, badge

    def _build_movement_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        heading = QLabel("Movement")
        heading.setObjectName("PageTitle")
        subtitle = QLabel("Tune how the cursor responds to your hand.")
        subtitle.setObjectName("PageHint")
        layout.addWidget(heading)
        layout.addWidget(subtitle)
        layout.addSpacing(24)

        # --- Cursor Smoothing row ---
        label_row = QHBoxLayout()
        setting_label = QLabel("Cursor Smoothing")
        setting_label.setObjectName("SettingLabel")

        stored = float(self.config.get("cursor_smoothing", 0.30))
        self.smoothing_value = QLabel()
        self.smoothing_value.setObjectName("ValueBadge")

        label_row.addWidget(setting_label)
        label_row.addStretch(1)
        label_row.addWidget(self.smoothing_value)
        layout.addLayout(label_row)

        self.smoothing_slider = QSlider(Qt.Orientation.Horizontal)
        self.smoothing_slider.setMinimum(1)
        self.smoothing_slider.setMaximum(100)
        self.smoothing_slider.setValue(_smoothing_to_slider(stored))
        self.smoothing_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.smoothing_slider.valueChanged.connect(self._on_smoothing_changed)
        layout.addWidget(self.smoothing_slider)

        helper = QLabel(
            "Higher = more responsive (more jitter). "
            "Lower = smoother (more lag)."
        )
        helper.setObjectName("MutedText")
        layout.addWidget(helper)

        # Initialise the badge text.
        self._refresh_smoothing_label(self.smoothing_slider.value())

        layout.addSpacing(28)

        # --- Sniper Mode Speed Reduction row ---
        sniper_init = round(float(self.config.get("sniper_speed_reduction", 0.5)) * 100)
        self.sniper_slider, _ = self._add_slider_section(
            layout,
            "Sniper Mode Speed Reduction",
            "How much the cursor slows for precision when the hand moves slowly.",
            max(1, min(100, sniper_init)),
            self._on_sniper_changed,
        )

        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Dashboard page
    # ------------------------------------------------------------------

    def _build_dashboard_page(self) -> QWidget:
        page, layout = self._page_scaffold(
            "Dashboard", "Live tracking status and quick controls."
        )

        # --- Camera selection row ---
        cam_row = QHBoxLayout()
        cam_label = QLabel("Select Camera")
        cam_label.setObjectName("SettingLabel")
        self.camera_combo = QComboBox()
        self.camera_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._populate_cameras()
        # Connect after populating so initial setup doesn't trigger a save.
        self.camera_combo.currentIndexChanged.connect(self._on_camera_changed)
        cam_row.addWidget(cam_label)
        cam_row.addWidget(self.camera_combo)
        cam_row.addStretch(1)
        layout.addLayout(cam_row)
        layout.addSpacing(12)

        # Camera preview placeholder (filled by CVThread.frame_ready).
        self.camera_preview = QLabel("Camera Preview")
        self.camera_preview.setObjectName("CameraPreview")
        self.camera_preview.setFixedSize(640, 480)
        self.camera_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.camera_preview, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Persistent red boundary rectangle drawn on top of the preview.
        self.boundary_overlay = BoundaryOverlay(self.config, self.camera_preview)
        self.boundary_overlay.setGeometry(self.camera_preview.rect())
        self.boundary_overlay.raise_()

        layout.addSpacing(20)

        # Mode toggles + auto-calibrate, in a single row.
        controls = QHBoxLayout()
        controls.setSpacing(12)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        current_mode = self.config.get("mode", "front")

        self._mode_buttons: dict[str, QPushButton] = {}
        for label, mode_key in (("Front-Facing Mode", "front"),
                                ("Top-Down Mode", "topdown")):
            btn = QPushButton(label)
            btn.setObjectName("ModeToggle")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setChecked(current_mode == mode_key)
            btn.clicked.connect(lambda _, m=mode_key: self._on_mode_changed(m))
            self.mode_group.addButton(btn)
            self._mode_buttons[mode_key] = btn
            controls.addWidget(btn)

        controls.addStretch(1)

        self.calibrate_button = QPushButton("Auto-Calibrate Camera")
        self.calibrate_button.setObjectName("ActionButton")
        self.calibrate_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.calibrate_button.clicked.connect(self._on_auto_calibrate)
        controls.addWidget(self.calibrate_button)

        layout.addLayout(controls)

        # Camera-flip controls — only meaningful (and visible) in Top-Down mode.
        layout.addSpacing(16)
        self.flip_controls = self._build_flip_controls(current_mode)
        layout.addWidget(self.flip_controls)

        layout.addStretch(1)
        return page

    def _build_flip_controls(self, current_mode: str) -> QWidget:
        """A compact 'Camera Flip' row with horizontal/vertical pill toggles."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        label = QLabel("Camera Flip")
        label.setObjectName("SettingLabel")
        row.addWidget(label)

        self.flip_h_button = QPushButton("⇆  Horizontal")
        self.flip_h_button.setObjectName("FlipToggle")
        self.flip_h_button.setCheckable(True)
        self.flip_h_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.flip_h_button.setChecked(bool(self.config.get("flip_horizontal", False)))
        self.flip_h_button.toggled.connect(self._on_flip_h_toggled)
        row.addWidget(self.flip_h_button)

        self.flip_v_button = QPushButton("⇅  Vertical")
        self.flip_v_button.setObjectName("FlipToggle")
        self.flip_v_button.setCheckable(True)
        self.flip_v_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.flip_v_button.setChecked(bool(self.config.get("flip_vertical", False)))
        self.flip_v_button.toggled.connect(self._on_flip_v_toggled)
        row.addWidget(self.flip_v_button)

        row.addStretch(1)
        container.setVisible(current_mode == "topdown")
        return container

    def _populate_cameras(self) -> None:
        """
        Fill the combo box with real camera names via QMediaDevices.

        The list position is used as the OpenCV index (cv2.VideoCapture(N)),
        since QMediaDevices enumerates video inputs in the same order.
        """
        cameras = QMediaDevices.videoInputs()
        if not cameras:
            self.camera_combo.addItem("No camera found", -1)
            self.camera_combo.setEnabled(False)
            return

        for opencv_index, device in enumerate(cameras):
            self.camera_combo.addItem(device.description(), opencv_index)

        saved = int(self.config.get("camera_index", 0))
        pos = self.camera_combo.findData(saved)
        self.camera_combo.setCurrentIndex(pos if pos >= 0 else 0)

    def _on_camera_changed(self, _pos: int) -> None:
        index = self.camera_combo.currentData()
        if index is None or index < 0:
            return
        index = int(index)
        # Instant-save, then ask the app to restart the capture thread.
        self.config.set("camera_index", index)
        self.camera_changed.emit(index)

    def current_camera_index(self) -> int:
        """The camera the UI currently has selected (falls back to config)."""
        data = self.camera_combo.currentData()
        if data is None or data < 0:
            return int(self.config.get("camera_index", 0))
        return int(data)

    def update_landmarks(self, hands: list) -> None:
        """Slot for CVThread.landmarks_ready — stash for the next frame draw."""
        self._latest_hands = hands

    def update_camera_frame(self, image: QImage) -> None:
        """Slot for CVThread.frame_ready — draw the skeleton, then render."""
        # Draw the skeleton straight onto the frame for a pixel-perfect overlay.
        draw_skeleton_on_image(
            image, self._latest_hands, bool(self.config.get("mirror_x"))
        )
        pixmap = QPixmap.fromImage(image)
        self.camera_preview.setPixmap(
            pixmap.scaled(
                self.camera_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    # ------------------------------------------------------------------
    # Gestures page
    # ------------------------------------------------------------------

    def _build_gestures_page(self) -> QWidget:
        page, layout = self._page_scaffold(
            "Gestures", "Tune tap detection and gesture features."
        )

        tap_init = _threshold_to_sensitivity(
            float(self.config.get("tap_threshold", 0.70))
        )
        self.tap_slider, _ = self._add_slider_section(
            layout,
            "Tap Sensitivity (Z-Axis)",
            "Higher = lighter taps register more easily (lower Z threshold).",
            tap_init,
            self._on_tap_sensitivity_changed,
        )

        layout.addSpacing(20)

        self.keyboard_checkbox = QCheckBox("Enable Virtual Keyboard")
        self.keyboard_checkbox.setChecked(bool(self.config.get("enable_keyboard", True)))
        self.keyboard_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.keyboard_checkbox.toggled.connect(
            lambda on: self.config.set("enable_keyboard", bool(on))
        )
        layout.addWidget(self.keyboard_checkbox)

        self.autohide_checkbox = QCheckBox("Auto-Hide Floating Status")
        self.autohide_checkbox.setChecked(bool(self.config.get("auto_hide_widget", True)))
        self.autohide_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.autohide_checkbox.toggled.connect(
            lambda on: self.config.set("auto_hide_widget", bool(on))
        )
        layout.addWidget(self.autohide_checkbox)

        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Widget page
    # ------------------------------------------------------------------

    def _build_widget_page(self) -> QWidget:
        page, layout = self._page_scaffold(
            "Widget", "Floating status widget appearance."
        )

        mode_label = QLabel("Widget Display Mode")
        mode_label.setObjectName("SettingLabel")
        layout.addWidget(mode_label)

        self.widget_mode_group = QButtonGroup(self)
        self.widget_mode_group.setExclusive(True)
        current = self.config.get("widget_mode", "skeleton")

        for label, mode_key in (("Minimal Icon", "minimal"),
                                ("Transparent Skeleton", "skeleton"),
                                ("Full Camera", "full")):
            radio = QRadioButton(label)
            radio.setChecked(current == mode_key)
            radio.setCursor(Qt.CursorShape.PointingHandCursor)
            radio.toggled.connect(
                lambda on, m=mode_key: self._on_widget_mode_changed(m, on)
            )
            self.widget_mode_group.addButton(radio)
            layout.addWidget(radio)

        layout.addSpacing(24)

        opacity_init = round(float(self.config.get("skeleton_opacity", 0.9)) * 100)
        self.opacity_slider, _ = self._add_slider_section(
            layout,
            "Skeleton Opacity",
            "Transparency of the glowing skeleton on the floating widget.",
            max(1, min(100, opacity_init)),
            self._on_skeleton_opacity_changed,
        )

        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Instant-save handlers
    # ------------------------------------------------------------------

    def _on_smoothing_changed(self, slider_value: int) -> None:
        smoothing = _slider_to_smoothing(slider_value)
        self._refresh_smoothing_label(slider_value)
        # Instant-save: persist immediately, no confirmation dialog.
        self.config.set("cursor_smoothing", round(smoothing, 2))

    def _refresh_smoothing_label(self, slider_value: int) -> None:
        self.smoothing_value.setText(f"{slider_value}%")

    def _on_sniper_changed(self, slider_value: int) -> None:
        self.config.set("sniper_speed_reduction", round(slider_value / 100.0, 2))

    def _on_mode_changed(self, mode_key: str) -> None:
        self.config.set("mode", mode_key)
        # Front-Facing mode mirrors the view; Top-Down does not.
        mirror = mode_key == "front"
        self.config.set("mirror_x", mirror)
        self.mirror_changed.emit(mirror)
        # The flip controls are only relevant in Top-Down mode.
        self.flip_controls.setVisible(mode_key == "topdown")

    def _on_flip_v_toggled(self, checked: bool) -> None:
        self.config.set("flip_vertical", bool(checked))
        self.flip_changed.emit(bool(checked))

    def _on_flip_h_toggled(self, checked: bool) -> None:
        self.config.set("flip_horizontal", bool(checked))
        self.flip_h_changed.emit(bool(checked))

    def _on_auto_calibrate(self) -> None:
        # Backend calibration is intentionally not wired here yet.
        pass

    def _on_tap_sensitivity_changed(self, slider_value: int) -> None:
        self.config.set("tap_threshold", _sensitivity_to_threshold(slider_value))

    def _on_widget_mode_changed(self, mode_key: str, checked: bool) -> None:
        if checked:  # toggled fires for both the newly-on and newly-off buttons
            self.config.set("widget_mode", mode_key)

    def _on_skeleton_opacity_changed(self, slider_value: int) -> None:
        self.config.set("skeleton_opacity", round(slider_value / 100.0, 2))
