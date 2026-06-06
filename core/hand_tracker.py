import mediapipe as mp
import cv2
import numpy as np
from dataclasses import dataclass
from typing import Optional


@dataclass
class HandLandmarks:
    """Container for a single detected hand's data."""
    landmarks: np.ndarray  # shape (21, 3) — x, y, z normalized [0..1]
    handedness: str        # 'Left' or 'Right'


class HandTracker:
    """
    Wraps MediaPipe Hands to process individual frames.

    Designed to be instantiated once and reused across frames. Not thread-safe;
    each CVThread should own its own instance.
    """

    def __init__(
        self,
        max_hands: int = 1,
        detection_confidence: float = 0.7,
        tracking_confidence: float = 0.7,
    ) -> None:
        self._mp_hands = mp.solutions.hands
        self._hands = self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=max_hands,
            min_detection_confidence=detection_confidence,
            min_tracking_confidence=tracking_confidence,
        )

    def process(self, frame_bgr: np.ndarray) -> list[HandLandmarks]:
        """
        Process a BGR frame and return detected hand landmarks.

        Returns an empty list when no hands are detected.
        """
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = self._hands.process(rgb)

        if not results.multi_hand_landmarks:
            return []

        detected: list[HandLandmarks] = []
        for hand_lm, hand_info in zip(
            results.multi_hand_landmarks,
            results.multi_handedness,
        ):
            coords = np.array(
                [[lm.x, lm.y, lm.z] for lm in hand_lm.landmark],
                dtype=np.float32,
            )
            label = hand_info.classification[0].label  # 'Left' or 'Right'
            detected.append(HandLandmarks(landmarks=coords, handedness=label))

        return detected

    def close(self) -> None:
        self._hands.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
