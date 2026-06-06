import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

import numpy as np


# --- Landmark indices (MediaPipe Hands) -------------------------------------
WRIST = 0
THUMB_TIP, THUMB_MCP = 4, 2
INDEX_TIP = 8
MIDDLE_MCP = 9
FINGER_TIPS = (8, 12, 16, 20)
FINGER_PIPS = (6, 10, 14, 18)


class HandPose(Enum):
    OPEN = auto()
    FIST = auto()
    OTHER = auto()


def _xy_dist(a: np.ndarray, b: np.ndarray) -> float:
    """2D (x, y) distance; z is too noisy to use for extension tests."""
    dx = float(a[0]) - float(b[0])
    dy = float(a[1]) - float(b[1])
    return (dx * dx + dy * dy) ** 0.5


def count_extended_fingers(landmarks: np.ndarray) -> int:
    """
    Count extended fingers using distance-from-wrist, which is orientation
    independent (works top-down or upright). A finger is extended when its tip
    is farther from the wrist than its PIP joint.
    """
    wrist = landmarks[WRIST]
    count = 0
    for tip, pip in zip(FINGER_TIPS, FINGER_PIPS):
        if _xy_dist(landmarks[tip], wrist) > _xy_dist(landmarks[pip], wrist):
            count += 1
    # Thumb: compare tip vs MCP distance from wrist.
    if _xy_dist(landmarks[THUMB_TIP], wrist) > _xy_dist(landmarks[THUMB_MCP], wrist):
        count += 1
    return count


def classify_hand(landmarks: np.ndarray) -> HandPose:
    extended = count_extended_fingers(landmarks)
    if extended >= 4:
        return HandPose.OPEN
    if extended <= 1:
        return HandPose.FIST
    return HandPose.OTHER


def _coords(hand) -> np.ndarray:
    """Accept either a HandLandmarks object or a raw (21, 3) array."""
    return getattr(hand, "landmarks", hand)


# --- Keyboard show/hide state machine ---------------------------------------

class KeyboardState(Enum):
    HIDDEN = auto()
    VISIBLE = auto()


class KeyboardGesture:
    """
    Two-hand state machine driving the virtual keyboard.

    Both hands OPEN -> show; both hands FIST -> hide. A gesture must persist for
    ``hold_frames`` consecutive frames before it fires, which debounces noisy
    single-frame misclassifications.
    """

    def __init__(self, hold_frames: int = 5) -> None:
        self._hold = hold_frames
        self.state = KeyboardState.HIDDEN
        self._open_streak = 0
        self._fist_streak = 0

    def update(self, hands: list) -> Optional[str]:
        """Returns 'show', 'hide', or None for this frame."""
        if len(hands) < 2:
            self._open_streak = self._fist_streak = 0
            return None

        poses = [classify_hand(_coords(h)) for h in hands[:2]]
        both_open = all(p is HandPose.OPEN for p in poses)
        both_fist = all(p is HandPose.FIST for p in poses)

        self._open_streak = self._open_streak + 1 if both_open else 0
        self._fist_streak = self._fist_streak + 1 if both_fist else 0

        if (
            self.state is KeyboardState.HIDDEN
            and self._open_streak >= self._hold
        ):
            self.state = KeyboardState.VISIBLE
            self._open_streak = 0
            return "show"

        if (
            self.state is KeyboardState.VISIBLE
            and self._fist_streak >= self._hold
        ):
            self.state = KeyboardState.HIDDEN
            self._fist_streak = 0
            return "hide"

        return None


# --- Z-axis tap detection ---------------------------------------------------

class TapDetector:
    """
    Detects a tactile "tap" from the index fingertip's Z-axis motion.

    In MediaPipe, larger Z means farther from the camera. Pressing down toward
    the physical table moves the fingertip away from a top-down camera, so Z
    rises sharply. We track the smoothed Z velocity and fire when it exceeds a
    threshold, with a cooldown so one press yields one tap.
    """

    def __init__(
        self,
        velocity_threshold: float = 0.7,
        cooldown: float = 0.3,
        smoothing: float = 0.5,
    ) -> None:
        self._threshold = velocity_threshold
        self._cooldown = cooldown
        self._smoothing = smoothing
        self._prev_z: Optional[float] = None
        self._prev_t: Optional[float] = None
        self._velocity = 0.0
        self._last_tap_t = float("-inf")  # allow a tap immediately on startup

    def update(self, z: float, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now

        if self._prev_z is None or self._prev_t is None:
            self._prev_z, self._prev_t = z, now
            return False

        dt = now - self._prev_t
        if dt <= 0:
            # Same timestamp (or clock skew): just refresh the position.
            self._prev_z = z
            return False

        # Positive velocity == moving away from the camera (pressing down).
        raw_v = (z - self._prev_z) / dt
        self._prev_z, self._prev_t = z, now

        # EMA-smooth the velocity so one jittery frame can't fire a phantom tap.
        self._velocity = (
            self._smoothing * raw_v + (1.0 - self._smoothing) * self._velocity
        )

        if (
            self._velocity > self._threshold
            and (now - self._last_tap_t) > self._cooldown
        ):
            self._last_tap_t = now
            self._velocity = 0.0  # consume, so the press isn't double-counted
            return True
        return False

    def reset(self) -> None:
        self._prev_z = None
        self._prev_t = None
        self._velocity = 0.0


# --- Pinch (thumb + index) click detection ----------------------------------

class PinchState(Enum):
    OPEN = auto()
    ENGAGED = auto()   # fingers close — sticky should be active
    CLICKED = auto()   # fully pinched, click already fired this gesture


class PinchDetector:
    """
    Two-stage pinch detector with hysteresis, emitting 'start'/'click'/'end'.

    The thumb-tip↔index-tip distance is normalized by hand scale (wrist↔middle
    MCP) so the thresholds hold regardless of how near the hand is to the camera.

    * 'start' — fingers come within ``start_ratio``: the cursor should go sticky.
    * 'click' — fingers close further to ``click_ratio``: fire one left-click.
    * 'end'   — fingers separate past ``release_ratio``: release the gesture.

    Releasing while only ENGAGED (never reached the click) still emits 'end',
    which clears the sticky state without clicking.
    """

    def __init__(
        self,
        start_ratio: float = 0.35,
        click_ratio: float = 0.20,
        release_ratio: float = 0.45,
    ) -> None:
        self._start = start_ratio
        self._click = click_ratio
        self._release = release_ratio
        self.state = PinchState.OPEN

    def update(self, landmarks: np.ndarray) -> Optional[str]:
        scale = _xy_dist(landmarks[WRIST], landmarks[MIDDLE_MCP])
        if scale < 1e-6:
            return None
        ratio = _xy_dist(landmarks[THUMB_TIP], landmarks[INDEX_TIP]) / scale

        if self.state is PinchState.OPEN:
            if ratio < self._start:
                self.state = PinchState.ENGAGED
                return "start"
        elif self.state is PinchState.ENGAGED:
            if ratio < self._click:
                self.state = PinchState.CLICKED
                return "click"
            if ratio > self._release:
                self.state = PinchState.OPEN
                return "end"
        elif self.state is PinchState.CLICKED:
            if ratio > self._release:
                self.state = PinchState.OPEN
                return "end"
        return None

    def reset(self) -> None:
        self.state = PinchState.OPEN


# --- Combined per-frame engine ----------------------------------------------

@dataclass
class GestureResult:
    keyboard_event: Optional[str]            # 'show' | 'hide' | None
    tapped: bool
    pinch_event: Optional[str]               # 'start' | 'click' | 'end' | None
    index_xy: Optional[tuple[float, float]]  # normalized tip of the active hand
    grab_xy: Optional[tuple[float, float]]   # normalized wrist of a single fist


class GestureEngine:
    """Runs all gesture detectors over one frame's worth of hands."""

    def __init__(
        self,
        hold_frames: int = 5,
        tap_threshold: float = 0.7,
        tap_cooldown: float = 0.3,
    ) -> None:
        self._keyboard = KeyboardGesture(hold_frames=hold_frames)
        self._tap = TapDetector(
            velocity_threshold=tap_threshold, cooldown=tap_cooldown
        )
        self._pinch = PinchDetector()

    @property
    def keyboard_state(self) -> KeyboardState:
        return self._keyboard.state

    def process(self, hands: list) -> GestureResult:
        kb_event = self._keyboard.update(hands)

        tapped = False
        pinch_event: Optional[str] = None
        index_xy: Optional[tuple[float, float]] = None
        grab_xy: Optional[tuple[float, float]] = None
        if hands:
            lm = _coords(hands[0])
            index_xy = (float(lm[INDEX_TIP][0]), float(lm[INDEX_TIP][1]))
            tapped = self._tap.update(float(lm[INDEX_TIP][2]))
            pinch_event = self._pinch.update(lm)

            # Grab = exactly one hand, forming a fist (distinct from the
            # two-hand fist that hides the keyboard). Reported as the wrist.
            if len(hands) == 1 and classify_hand(lm) is HandPose.FIST:
                grab_xy = (float(lm[WRIST][0]), float(lm[WRIST][1]))
        else:
            # Hand lost mid-pinch: drop any sticky state on the next frame.
            self._pinch.reset()

        return GestureResult(kb_event, tapped, pinch_event, index_xy, grab_xy)
