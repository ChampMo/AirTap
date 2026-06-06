import math
import time
from enum import Enum, auto
from typing import Optional

import numpy as np


# Rotation is performed about the normalized frame centre so the workspace
# stays centred instead of pivoting around the (0, 0) corner.
_CENTER = 0.5


def compute_deviation_angle(
    start: tuple[float, float], end: tuple[float, float]
) -> float:
    """
    Deviation angle (radians) of a drag stroke from the straight Y-axis.

    The user, in Top-Down mode, drags the index finger in the direction they
    consider "straight forward/up". The vector from ``start`` to ``end`` should
    ideally lie on the Y-axis (dx == 0). Any horizontal component means the
    camera is rotated relative to the desk.

    theta is defined as the rotation the *camera* introduced: the observed
    stroke equals the intended vertical stroke passed through the forward matrix
    R(theta), i.e. (dx, dy) = (-L*sin(theta), L*cos(theta)). Solving gives
    theta = atan2(-dx, dy). Correcting incoming coordinates by -theta (per the
    project spec) therefore exactly undoes the tilt. A degenerate
    (near-zero-length) stroke yields 0.0.
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if math.hypot(dx, dy) < 1e-6:
        return 0.0
    return math.atan2(-dx, dy)


class RotationCorrector:
    """
    Applies a 2D rotation of ``-theta`` to incoming coordinates to undo a known
    camera misalignment, pivoting about the normalized frame centre.

    Forward rotation by theta (per project spec):
        x' = x*cos(theta) - y*sin(theta)
        y' = x*sin(theta) + y*cos(theta)

    Correction rotates by ``-theta``, so with c = cos(theta), s = sin(theta):
        x' =  x*c + y*s
        y' = -x*s + y*c
    """

    def __init__(self, theta: float = 0.0) -> None:
        self.set_angle(theta)

    def set_angle(self, theta: float) -> None:
        self._theta = theta
        self._cos = math.cos(theta)
        self._sin = math.sin(theta)

    @property
    def theta(self) -> float:
        return self._theta

    def apply(self, x: float, y: float) -> tuple[float, float]:
        """Rotate a single normalized (x, y) by -theta about the centre."""
        if self._theta == 0.0:
            return x, y
        ox, oy = x - _CENTER, y - _CENTER
        rx = ox * self._cos + oy * self._sin
        ry = -ox * self._sin + oy * self._cos
        return rx + _CENTER, ry + _CENTER

    def apply_landmarks(self, landmarks: np.ndarray) -> np.ndarray:
        """
        Return a copy of an ``(N, 3)`` landmark array with X/Y corrected and Z
        left untouched.
        """
        if self._theta == 0.0:
            return landmarks
        out = np.array(landmarks, dtype=np.float32, copy=True)
        ox = out[:, 0] - _CENTER
        oy = out[:, 1] - _CENTER
        out[:, 0] = ox * self._cos + oy * self._sin + _CENTER
        out[:, 1] = -ox * self._sin + oy * self._cos + _CENTER
        return out


class CalibrationState(Enum):
    IDLE = auto()
    RECORDING = auto()
    DONE = auto()


class TopDownCalibrator:
    """
    Frame-driven calibration sequence for Top-Down mode.

    Usage (one instance per calibration run):
        cal.begin(index_tip_xy)          # records the start point + timestamp
        ...                              # each subsequent frame:
        theta = cal.update(index_tip_xy) # returns theta once ~1s has elapsed,
                                         # else None while still recording

    Time is measured with ``time.monotonic`` so the logic is independent of the
    GUI/CV framework. ``duration`` is the hold time between start and end
    samples (default 1.0s per spec).
    """

    def __init__(self, duration: float = 1.0) -> None:
        self._duration = duration
        self._state = CalibrationState.IDLE
        self._start_pt: Optional[tuple[float, float]] = None
        self._start_time: float = 0.0
        self._last_pt: Optional[tuple[float, float]] = None
        self._theta: Optional[float] = None

    @property
    def state(self) -> CalibrationState:
        return self._state

    @property
    def result(self) -> Optional[float]:
        return self._theta

    def begin(self, index_tip_xy: tuple[float, float]) -> None:
        """Record the stroke's start point and start the 1-second timer."""
        self._start_pt = (float(index_tip_xy[0]), float(index_tip_xy[1]))
        self._last_pt = self._start_pt
        self._start_time = time.monotonic()
        self._theta = None
        self._state = CalibrationState.RECORDING

    def update(self, index_tip_xy: tuple[float, float]) -> Optional[float]:
        """
        Feed the current index-tip position. Returns the computed theta once the
        hold duration has elapsed (transitioning to DONE), otherwise None.
        """
        if self._state is not CalibrationState.RECORDING:
            return self._theta

        self._last_pt = (float(index_tip_xy[0]), float(index_tip_xy[1]))
        if (time.monotonic() - self._start_time) >= self._duration:
            assert self._start_pt is not None
            self._theta = compute_deviation_angle(self._start_pt, self._last_pt)
            self._state = CalibrationState.DONE
            return self._theta
        return None

    def reset(self) -> None:
        self._state = CalibrationState.IDLE
        self._start_pt = None
        self._last_pt = None
        self._theta = None
