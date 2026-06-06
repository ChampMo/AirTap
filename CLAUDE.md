# Project Context: AirDesk (Hand Tracking OS Controller)

## Overview
AirDesk is a high-performance Python application that controls the operating system (mouse and virtual keyboard) using hand tracking via a webcam. The project emphasizes minimal CPU/RAM usage, high precision, and a modern, clean UI.

## Tech Stack
- **Core Language:** Python 3.10+
- **Computer Vision:** `opencv-python`, `mediapipe` (for precise 21-landmark hand tracking)
- **OS Control:** `pynput` (for mouse and keyboard manipulation)
- **GUI Framework:** `PyQt6` (for both the main settings UI and the transparent floating widget)

## Architecture & Logic Requirements
1. **Cursor Stabilization:** Must use Exponential Moving Average (EMA) to filter MediaPipe coordinates before moving the mouse to prevent jitter.
2. **Top-Down Mode Calibration:** Requires a 2D rotation matrix to fix camera misalignment. The rotation angle ($\theta$) is calculated automatically and saved to a config file.
   Math reference:
   $$x' = x \cos(\theta) - y \sin(\theta)$$
   $$y' = x \sin(\theta) + y \cos(\theta)$$
3. **Z-Axis Tap Detection:** Use MediaPipe's Z-axis depth changes to detect tactile "taps" on the physical table for clicking or typing on the virtual keyboard.
4. **Emergency Stop:** Bind the `Esc` key globally to immediately pause all hand-tracking OS control.

## UI/UX Guidelines (Strict)
- **Aesthetic:** Minimalist, Light Theme. White/Light Gray backgrounds with high-contrast Black text and icons.
- **Instant Save:** No confirmation dialogs or popups. Changes to sliders, toggles, or dropdowns in PyQt6 must be applied and saved to a configuration file immediately.
- **Floating Status Widget:** Must be a `FramelessWindowHint` and `WA_TranslucentBackground` PyQt6 widget. Do not render video frames here; use `QPainter` to draw glowing skeleton lines (neon blue/orange) on the transparent background to save resources.

## Code Conventions
- Use Object-Oriented Programming (OOP) to separate UI components from CV processing.
- Run MediaPipe/OpenCV in a separate `QThread` to prevent freezing the PyQt6 GUI.
- Emit PyQt Signals to communicate between the CV thread and the UI components.