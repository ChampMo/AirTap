from PyQt6.QtCore import QObject, QPoint
from pynput import keyboard as pkeyboard
from pynput import mouse as pmouse

from core.config import ConfigManager
from core.gestures import GestureEngine, FINGER_TIPS, THUMB_TIP, _coords
from core.mouse_controller import MouseController
from ui.keyboard_widget import VirtualKeyboard


# Maps virtual-keyboard glyphs to pynput special keys. Plain letters fall
# through to .type().
_SPECIAL_KEYS = {
    "SPACE": pkeyboard.Key.space,
    "⌫": pkeyboard.Key.backspace,
    "⏎": pkeyboard.Key.enter,
}

_TIP_INDICES = (THUMB_TIP, *FINGER_TIPS)  # 4, 8, 12, 16, 20


class AppController(QObject):
    """
    Central coordinator wiring CVThread landmark frames to OS actions.

    Responsibilities per frame:
      * run gesture detection (GestureEngine),
      * show/hide the virtual keyboard (Top-Down mode only),
      * pinch -> click / press-and-hold / drag on the desktop,
      * one-hand fist -> grab and drag the keyboard window,
      * Z-axis tap -> flash + type on the virtual keyboard,
      * draw glowing fingertip points on the keyboard.
    """

    def __init__(self, config: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self._config = config

        self.mouse_controller = MouseController(
            smoothing=config.get("cursor_smoothing"),
            mirror_x=config.get("mirror_x"),
            rotation_angle=config.get("rotation_angle"),
            boundary=(
                config.get("boundary_xmin"),
                config.get("boundary_xmax"),
                config.get("boundary_ymin"),
                config.get("boundary_ymax"),
            ),
            long_press_duration=config.get("long_press_duration"),
        )
        self.keyboard = VirtualKeyboard()
        self.engine = GestureEngine()
        self._grabbing = False

        # Independent pynput controllers for the click/type actions.
        self._pkb = pkeyboard.Controller()
        self._pmouse = pmouse.Controller()

    # ------------------------------------------------------------------
    # CVThread slot
    # ------------------------------------------------------------------

    def on_landmarks(self, hands: list) -> None:
        """Slot for ``CVThread.landmarks_ready``."""
        result = self.engine.process(hands)

        # --- Keyboard show/hide (Top-Down mode only) ---
        if result.keyboard_event == "show":
            if (
                self._config.get("mode") == "topdown"
                and self._config.get("enable_keyboard", True)
            ):
                self.keyboard.show_in_boundary(self._config)
        elif result.keyboard_event == "hide":
            self.keyboard.hide()

        kb_visible = self.keyboard.isVisible()

        # --- One-hand fist grabs and drags the keyboard window ---
        self._grabbing = kb_visible and result.grab_xy is not None
        if self._grabbing:
            self._drag_keyboard(result.grab_xy)

        # --- Pinch: desktop click / press-hold / drag (keyboard hidden) ---
        if result.pinch_event == "start" and not kb_visible and self.mouse_controller.enabled:
            self.mouse_controller.pinch_down()
        elif result.pinch_event == "end":
            # Always release on end so a drag can never get stuck.
            self.mouse_controller.pinch_up()

        # --- Cursor motion (drives both desktop control and key hover) ---
        if hands and not self._grabbing:
            self.mouse_controller.update(_coords(hands[0]))

        # --- Z-axis tap types on the visible keyboard ---
        if result.tapped and kb_visible and self.mouse_controller.enabled:
            self._handle_type()

        # --- Glowing fingertip points while not dragging the keyboard ---
        if kb_visible and not self._grabbing:
            self.keyboard.update_fingertips(self._fingertip_points(hands))
        elif kb_visible:
            self.keyboard.update_fingertips([])

    # ------------------------------------------------------------------
    # Keyboard interactions
    # ------------------------------------------------------------------

    def _drag_keyboard(self, grab_xy: tuple[float, float]) -> None:
        x, y = self.mouse_controller.map_to_screen(grab_xy[0], grab_xy[1])
        self.keyboard.move_center(x, y)

    def _fingertip_points(self, hands: list) -> list[tuple[int, int]]:
        points: list[tuple[int, int]] = []
        for hand in hands:
            lm = _coords(hand)
            if len(lm) < 21:
                continue
            for idx in _TIP_INDICES:
                points.append(
                    self.mouse_controller.map_to_screen(
                        float(lm[idx][0]), float(lm[idx][1])
                    )
                )
        return points

    def _handle_type(self) -> None:
        x, y = self._pmouse.position
        label = self.keyboard.key_at(QPoint(int(x), int(y)))
        if label is not None:
            # Flash first (visual confirmation), then send the keystroke.
            self.keyboard.flash_key(label)
            self._type_key(label)

    def _type_key(self, label: str) -> None:
        special = _SPECIAL_KEYS.get(label)
        if special is not None:
            self._pkb.press(special)
            self._pkb.release(special)
        else:
            self._pkb.type(label.lower())
