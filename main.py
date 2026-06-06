import sys

from PyQt6.QtWidgets import QApplication

from core.config import ConfigManager
from core.cv_thread import CVThread
from controller import AppController
from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # keep running if settings window closes
    config = ConfigManager()

    # Flips are a Top-Down-only feature. If we launch in Front-Facing mode,
    # clear any stale flips so they can't invert the cursor mapping.
    if config.get("mode") != "topdown":
        config.set("flip_horizontal", False)
        config.set("flip_vertical", False)

    # Coordinator owns the MouseController (with the persisted Top-Down angle),
    # the gesture engine, and the virtual keyboard.
    controller = AppController(config)
    controller.mouse_controller.start_emergency_stop_listener()

    # Build the window first: it scans for cameras and resolves which one to use
    # (the saved index if still present, otherwise the first available).
    window = MainWindow(config)

    # Two hands are needed for the keyboard show/hide gestures.
    cv_thread = CVThread(
        camera_index=window.current_camera_index(),
        max_hands=2,
        emit_frames=True,  # Dashboard is the default tab on launch
        mirror_x=config.get("mirror_x"),
        flip_vertical=config.get("flip_vertical"),
        flip_horizontal=config.get("flip_horizontal"),
    )
    cv_thread.landmarks_ready.connect(controller.on_landmarks)
    cv_thread.camera_error.connect(lambda msg: print(f"[camera] {msg}"))

    # Mirror the preview AND the cursor mapping live on mode switch, so they
    # stay consistent without an app restart.
    window.mirror_changed.connect(cv_thread.set_mirror_enabled)
    window.mirror_changed.connect(controller.mouse_controller.set_mirror_x)
    # Camera flips (top/bottom and left/right) toggled from the Dashboard.
    window.flip_changed.connect(cv_thread.set_flip_vertical)
    window.flip_h_changed.connect(cv_thread.set_flip_horizontal)

    # Live camera preview on the Dashboard, with the skeleton drawn on the frame
    # itself (no separate overlay window — guarantees a perfect alignment).
    cv_thread.landmarks_ready.connect(window.update_landmarks)
    cv_thread.frame_ready.connect(window.update_camera_frame)

    # Only spend the resize/convert/copy cost while the Dashboard is visible.
    DASHBOARD_INDEX = 0
    window.stack.currentChanged.connect(
        lambda i: cv_thread.set_frame_emission(i == DASHBOARD_INDEX)
    )

    # Live-apply the smoothing slider to the running controller.
    window.smoothing_slider.valueChanged.connect(
        lambda v: controller.mouse_controller.set_smoothing(v / 100.0)
    )

    def switch_camera(index: int) -> None:
        # Safely stop the running capture, repoint it, and restart so the feed
        # switches without an app restart. QThread can be re-started once run()
        # has returned, which stop() guarantees via wait().
        cv_thread.stop()
        cv_thread.set_camera_index(index)
        cv_thread.start()

    window.camera_changed.connect(switch_camera)

    def shutdown() -> None:
        cv_thread.stop()
        controller.mouse_controller.stop_emergency_stop_listener()

    app.aboutToQuit.connect(shutdown)

    window.show()
    cv_thread.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
