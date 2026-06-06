import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

from .hand_tracker import HandTracker, HandLandmarks


class CVThread(QThread):
    """
    Background thread that owns the webcam and MediaPipe pipeline.

    Signals
    -------
    landmarks_ready
        Emitted each frame with the list of detected HandLandmarks (may be
        empty if no hand is visible).
    frame_ready
        Emitted each frame with a scaled-down RGB QImage of the camera feed,
        only while frame emission is enabled (off by default to save resources).
    camera_error
        Emitted once if the camera cannot be opened or is lost mid-session.
    """

    landmarks_ready: pyqtSignal = pyqtSignal(list)
    frame_ready: pyqtSignal = pyqtSignal(QImage)
    camera_error: pyqtSignal = pyqtSignal(str)

    def __init__(
        self,
        camera_index: int = 0,
        target_fps: int = 30,
        max_hands: int = 1,
        detection_confidence: float = 0.7,
        tracking_confidence: float = 0.7,
        emit_frames: bool = False,
        preview_width: int = 480,
        mirror_x: bool = True,
        flip_vertical: bool = False,
        flip_horizontal: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._camera_index = camera_index
        self._frame_delay_ms = max(1, int(1000 / target_fps))
        self._max_hands = max_hands
        self._detection_confidence = detection_confidence
        self._tracking_confidence = tracking_confidence
        self._emit_frames = emit_frames
        self._preview_width = preview_width
        self._mirror_x = mirror_x
        self._flip_vertical = flip_vertical
        self._flip_horizontal = flip_horizontal
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_frame_emission(self, enabled: bool) -> None:
        """
        Toggle preview-frame emission at runtime. Disable it when the Dashboard
        isn't visible so we skip the resize/convert/copy work entirely.
        """
        self._emit_frames = enabled

    def set_camera_index(self, index: int) -> None:
        """
        Change which camera the thread opens. Takes effect on the next run, so
        stop() the thread, call this, then start() it again to switch feeds.
        """
        self._camera_index = index

    def set_mirror_enabled(self, enabled: bool) -> None:
        """
        Toggle the horizontal flip of the *preview* frame (Front-Facing mode).
        Affects only the emitted QImage, never the tracked coordinates.
        """
        self._mirror_x = enabled

    def set_flip_vertical(self, enabled: bool) -> None:
        """
        Toggle a top/bottom flip applied to the raw frame *before* landmark
        detection (for an inverted Top-Down camera). Takes effect live — no
        thread restart needed since it's a per-frame operation.
        """
        self._flip_vertical = enabled

    def set_flip_horizontal(self, enabled: bool) -> None:
        """
        Toggle a left/right flip applied to the raw frame *before* landmark
        detection (Top-Down camera mounted rotated). Live, no restart needed.
        """
        self._flip_horizontal = enabled

    def stop(self) -> None:
        """Signal the thread to exit its loop and wait for it to finish."""
        self._running = False
        self.wait()

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            self.camera_error.emit(
                f"Cannot open camera at index {self._camera_index}."
            )
            return

        self._running = True
        with HandTracker(
            max_hands=self._max_hands,
            detection_confidence=self._detection_confidence,
            tracking_confidence=self._tracking_confidence,
        ) as tracker:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    self.camera_error.emit(
                        "Camera read failed — device may have been disconnected."
                    )
                    break

                # Flips apply to both tracking and preview, so do them on the
                # source frame before anything else consumes it.
                if self._flip_vertical:
                    frame = cv2.flip(frame, 0)
                if self._flip_horizontal:
                    frame = cv2.flip(frame, 1)

                detected: list[HandLandmarks] = tracker.process(frame)
                self.landmarks_ready.emit(detected)

                if self._emit_frames:
                    self._emit_preview(frame)

                # Honour target FPS; msleep yields the GIL cooperatively.
                self.msleep(self._frame_delay_ms)

        cap.release()

    # ------------------------------------------------------------------
    # Preview frame conversion
    # ------------------------------------------------------------------

    def _emit_preview(self, frame_bgr: np.ndarray) -> None:
        """Downscale a BGR frame, convert to an RGB QImage, and emit it.

        Tracking has already consumed the original frame upstream; cv2.resize and
        cv2.flip below both return *new* arrays, so nothing here mutates the
        frame the tracker/MouseController saw.
        """
        h, w = frame_bgr.shape[:2]
        if w > self._preview_width:
            scale = self._preview_width / float(w)
            frame_bgr = cv2.resize(
                frame_bgr,
                (self._preview_width, max(1, int(h * scale))),
                interpolation=cv2.INTER_AREA,
            )

        # Front-Facing mode: mirror the preview so it reads like a mirror. This
        # is purely cosmetic — coordinate tracking is untouched.
        if self._mirror_x:
            frame_bgr = cv2.flip(frame_bgr, 1)

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        ph, pw = rgb.shape[:2]
        image = QImage(rgb.data, pw, ph, pw * 3, QImage.Format.Format_RGB888)

        # .copy() detaches the QImage from the soon-to-be-freed numpy buffer,
        # which is essential since the signal is delivered on the GUI thread.
        self.frame_ready.emit(image.copy())
