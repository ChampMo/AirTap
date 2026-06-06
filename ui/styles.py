"""Minimal light-theme QSS for the AirDesk settings window."""

LIGHT_THEME = """
* {
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 14px;
    color: #1a1a1a;
}

QWidget#MainWindow,
QWidget#ContentArea {
    background-color: #ffffff;
}

/* ---------------- Sidebar ---------------- */

QWidget#Sidebar {
    background-color: #f4f5f7;
    border-right: 1px solid #e3e5e8;
}

QPushButton#NavButton {
    background-color: transparent;
    border: none;
    border-radius: 10px;
    padding: 12px 16px;
    text-align: left;
    color: #4a4f57;
    font-size: 15px;
}

QPushButton#NavButton:hover {
    background-color: #e9ebee;
}

QPushButton#NavButton:checked {
    background-color: #ffffff;
    color: #0a0a0a;
    font-weight: 600;
    border: 1px solid #e3e5e8;
}

QLabel#AppTitle {
    font-size: 18px;
    font-weight: 700;
    color: #0a0a0a;
    padding: 8px 16px 16px 16px;
}

/* ---------------- Content ---------------- */

QLabel#PageTitle {
    font-size: 22px;
    font-weight: 700;
    color: #0a0a0a;
}

QLabel#PageHint,
QLabel#MutedText {
    color: #8a9099;
    font-size: 13px;
}

QLabel#SettingLabel {
    font-size: 15px;
    font-weight: 600;
    color: #1a1a1a;
}

QLabel#ValueBadge {
    background-color: #f0f1f3;
    border-radius: 8px;
    padding: 4px 10px;
    color: #0a0a0a;
    font-weight: 600;
}

/* ---------------- Slider ---------------- */

QSlider::groove:horizontal {
    height: 6px;
    background: #e3e5e8;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: #2d6cff;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #ffffff;
    border: 2px solid #2d6cff;
    width: 16px;
    height: 16px;
    margin: -7px 0;
    border-radius: 9px;
}

QSlider::handle:horizontal:hover {
    background: #2d6cff;
}

/* ---------------- Camera preview ---------------- */

QLabel#CameraPreview {
    background-color: #eef0f2;
    border: 1px solid #e3e5e8;
    border-radius: 12px;
    color: #8a9099;
    font-size: 15px;
}

/* ---------------- Combo box ---------------- */

QComboBox {
    background-color: #ffffff;
    border: 1px solid #e3e5e8;
    border-radius: 8px;
    padding: 6px 12px;
    min-width: 140px;
    color: #1a1a1a;
}

QComboBox:hover {
    border: 1px solid #2d6cff;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #e3e5e8;
    border-radius: 8px;
    selection-background-color: #2d6cff;
    selection-color: #ffffff;
    outline: none;
}

/* ---------------- Toggle / action buttons ---------------- */

QPushButton#ModeToggle {
    background-color: #ffffff;
    border: 1px solid #e3e5e8;
    border-radius: 10px;
    padding: 10px 18px;
    color: #4a4f57;
}

QPushButton#ModeToggle:hover {
    background-color: #f0f1f3;
}

QPushButton#ModeToggle:checked {
    background-color: #2d6cff;
    border: 1px solid #2d6cff;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#ActionButton {
    background-color: #1a1a1a;
    border: none;
    border-radius: 10px;
    padding: 10px 18px;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#ActionButton:hover {
    background-color: #333333;
}

/* ---------------- Flip pill toggles ---------------- */

QPushButton#FlipToggle {
    background-color: #ffffff;
    border: 1px solid #e3e5e8;
    border-radius: 17px;
    padding: 8px 18px;
    color: #4a4f57;
    font-size: 14px;
}

QPushButton#FlipToggle:hover {
    background-color: #f0f1f3;
    border: 1px solid #2d6cff;
}

QPushButton#FlipToggle:checked {
    background-color: #2d6cff;
    border: 1px solid #2d6cff;
    color: #ffffff;
    font-weight: 600;
}

/* ---------------- Check boxes / radio buttons ---------------- */

QCheckBox, QRadioButton {
    spacing: 10px;
    color: #1a1a1a;
    font-size: 15px;
    padding: 6px 0;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 20px;
    height: 20px;
}

QCheckBox::indicator {
    border: 2px solid #c4c8cd;
    border-radius: 6px;
    background: #ffffff;
}

QCheckBox::indicator:hover {
    border: 2px solid #2d6cff;
}

QCheckBox::indicator:checked {
    border: 2px solid #2d6cff;
    background: #2d6cff;
}

QRadioButton::indicator {
    border: 2px solid #c4c8cd;
    border-radius: 10px;
    background: #ffffff;
}

QRadioButton::indicator:hover {
    border: 2px solid #2d6cff;
}

QRadioButton::indicator:checked {
    border: 6px solid #2d6cff;
    border-radius: 10px;
    background: #ffffff;
}
"""
