"""EyeBreak: a system-tray reminder for the 20-20-20 rule."""

import argparse
import configparser
import ctypes
import ctypes.wintypes
import getpass
import hashlib
import io
import math
import os
import sys
import time
from pathlib import Path

# Keep Qt's FFmpeg startup details out of the normal app output.
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg.info=false")

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QIODevice,
    QPropertyAnimation,
    QSaveFile,
    Qt,
    QTimer,
    QUrl,
    QVariantAnimation,
)
from PyQt6.QtGui import QAction, QColor, QIcon
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

APP_DIR = Path(__file__).resolve().parent
DEFAULTS_FILE = APP_DIR / "defaults.ini"
CONFIG_FILE = APP_DIR / "config.txt"
MIN_WORK_INTERVAL = 20 * 60
MILLISECONDS_PER_SECOND = 1000
PROGRESS_MAX = 10000
UI_REFRESH_MS = 100
WATCHDOG_INTERVAL_MS = 5000
TRAY_MESSAGE_DURATION_MS = 10000

WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x4
PBT_APMRESUMESUSPEND = 0x7
PBT_APMRESUMEAUTOMATIC = 0x12

APP_STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 13px; color: #172033; }
QFrame#surface { background: #ffffff; border: 1px solid #dbe3ef; border-radius: 12px; }
QLabel { background: transparent; }
QLabel#appName { font-size: 13px; font-weight: 700; color: #26354d; }
QLabel#status { font-size: 13px; color: #526179; }
QLabel#timer { font-size: 40px; font-weight: 700; color: #1d4ed8; }
QLabel#alertTitle { font-size: 18px; font-weight: 700; color: #172033; }
QProgressBar { background: #e6edfa; border: 0; border-radius: 4px; }
QProgressBar::chunk { border-radius: 4px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #64b5f6, stop:0.5 #4388f0, stop:1 #315fe4); }
QLineEdit, QSpinBox { background: #ffffff; border: 1px solid #cbd5e1;
    border-radius: 6px; padding: 5px; min-height: 23px; }
QLineEdit:focus, QSpinBox:focus { border-color: #2563eb; }
QCheckBox { spacing: 8px; }
QSlider::groove:horizontal { background: #dbe5f5; height: 5px; border-radius: 2px; }
QSlider::handle:horizontal { background: #2563eb; width: 15px; margin: -5px 0; border-radius: 7px; }
"""


def set_text_if_changed(widget, value):
    if widget.text() != value:
        widget.setText(value)


def set_value_if_changed(widget, value):
    if widget.value() != value:
        widget.setValue(value)


def set_enabled_if_changed(widget, enabled):
    if widget.isEnabled() != enabled:
        widget.setEnabled(enabled)


def surface_layout(window, margins, spacing):
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    window.setStyleSheet(APP_STYLE)
    outer = QVBoxLayout(window)
    outer.setContentsMargins(4, 4, 4, 4)
    surface = QFrame()
    surface.setObjectName("surface")
    outer.addWidget(surface)
    layout = QVBoxLayout(surface)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def progress_bar(name):
    bar = QProgressBar()
    bar.setRange(0, PROGRESS_MAX)
    bar.setTextVisible(False)
    bar.setFixedHeight(8)
    bar.setAccessibleName(name)
    return bar


def button(text, callback, kind="secondary"):
    control = AnimatedButton(text, kind)
    control.clicked.connect(callback)
    return control


def stop_button_animations(window):
    for control in window.findChildren(AnimatedButton):
        if control.window() is window:
            control.animation.stop()


def show_activated(window, center=False, restore=False):
    if center:
        screen = QApplication.primaryScreen()
        if screen is not None:
            window.move(screen.availableGeometry().center() - window.rect().center())
    if restore:
        window.showNormal()
    else:
        window.show()
    window.raise_()
    window.activateWindow()


def make_timer(parent, callback, interval=None, single_shot=False):
    timer = QTimer(parent)
    if single_shot:
        timer.setSingleShot(True)
    timer.timeout.connect(callback)
    if interval is not None:
        timer.start(interval)
    return timer


class AnimatedButton(QPushButton):
    reduce_motion = False
    COLORS = {
        "primary": ("#2563eb", "#1d4ed8", "#ffffff"),
        "secondary": ("#eef3fb", "#dfe9f8", "#25436f"),
        "chrome": ("#ffffff", "#e9eef6", "#526179"),
        "close": ("#ffffff", "#fee2e2", "#b42332"),
    }

    def __init__(self, text, kind="secondary", parent=None):
        super().__init__(text, parent)
        self.kind = kind
        self.base, self.hover, self.text_color = self.COLORS[kind]
        self.current_color = QColor(self.base)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self.apply_color)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_color(self.current_color)

    def apply_color(self, color):
        self.current_color = QColor(color)
        background = self.current_color.name()
        border = "none" if self.kind in ("primary", "chrome", "close") else "1px solid #d7e2f2"
        self.setStyleSheet(
            f"QPushButton {{ background: {background}; color: {self.text_color}; border: {border}; "
            "border-radius: 7px; font-weight: 600; padding: 3px 12px; min-height: 28px; }"
            "QPushButton:disabled { background: #f0f3f8; color: #9aa7ba; }"
        )

    def transition_to(self, color):
        window = self.window()
        if not self.isEnabled() or not window.isVisible() or window.isMinimized():
            return
        if self.reduce_motion:
            self.apply_color(QColor(color))
            return
        self.animation.stop()
        self.animation.setStartValue(self.current_color)
        self.animation.setEndValue(QColor(color))
        self.animation.start()

    def enterEvent(self, event):
        self.transition_to(self.hover)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.transition_to(self.base)
        super().leaveEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange and hasattr(self, "animation"):
            self.transition_to(self.base)


class TitleBar(QWidget):
    def __init__(self, owner, close_action, minimize_action=None, close_tooltip="Close"):
        super().__init__(owner)
        self.owner = owner
        self.drag_offset = None
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 0, 0, 0)
        row.setSpacing(4)
        name = QLabel("EyeBreak")
        name.setObjectName("appName")
        name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(name)
        row.addStretch()
        if minimize_action is not None:
            minimize = AnimatedButton("−", "chrome")
            minimize.setFixedSize(32, 28)
            minimize.setToolTip("Hide to tray")
            minimize.clicked.connect(minimize_action)
            row.addWidget(minimize)
        close = AnimatedButton("×", "close")
        close.setFixedSize(32, 28)
        close.setToolTip(close_tooltip)
        close.clicked.connect(close_action)
        row.addWidget(close)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.owner.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.owner.move(event.globalPosition().toPoint() - self.drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None
        super().mouseReleaseEvent(event)


class ReminderDialog(QDialog):
    def __init__(self, seconds, parent):
        super().__init__(
            parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowTitle("EyeBreak")
        self.resize(390, 245)
        self.total_seconds = seconds
        self.deadline = time.monotonic() + seconds
        self.last_tick = time.monotonic()
        self.paused_remaining = None

        layout = surface_layout(self, (20, 12, 20, 18), 7)
        layout.addWidget(TitleBar(self, self.reject, close_tooltip="Skip this break"))

        title = QLabel("Take an eye break")
        title.setObjectName("alertTitle")
        layout.addWidget(title)
        message = QLabel(f"Look at something 20 feet away for {seconds} seconds.")
        message.setObjectName("status")
        message.setWordWrap(True)
        layout.addWidget(message)

        self.countdown = QLabel()
        self.countdown.setObjectName("timer")
        self.countdown.setAccessibleName("Break time remaining")
        layout.addWidget(self.countdown)

        self.progress = progress_bar("Break progress")
        layout.addWidget(self.progress)

        layout.addWidget(button("Skip this break", self.reject))

        self.ui_timer = make_timer(self, self.on_ui_tick)
        self.expiry_timer = make_timer(self, self.on_expired, math.ceil(seconds * MILLISECONDS_PER_SECOND), True)
        self.watchdog_timer = make_timer(self, self.adjust_for_elapsed_gap, WATCHDOG_INTERVAL_MS)

    def calculate_remaining_time(self):
        if self.paused_remaining is not None:
            return self.paused_remaining
        return max(0, self.deadline - time.monotonic())

    def adjust_for_elapsed_gap(self):
        # A long event-loop gap likely means sleep; keep the break countdown paused.
        now = time.monotonic()
        gap = now - self.last_tick
        self.last_tick = now
        if gap > 5 and self.paused_remaining is None:
            self.deadline += gap
            self.expiry_timer.start(math.ceil(self.calculate_remaining_time() * MILLISECONDS_PER_SECOND))

    def update_ui(self):
        if not self.isVisible() or self.isMinimized() or self.paused_remaining is not None:
            return
        exact_remaining = self.calculate_remaining_time()
        remaining = math.ceil(exact_remaining)
        minutes, seconds = divmod(remaining, 60)
        set_text_if_changed(self.countdown, f"{minutes:02d}:{seconds:02d}")
        set_value_if_changed(self.progress, round(PROGRESS_MAX * (1 - exact_remaining / self.total_seconds)))

    def on_ui_tick(self):
        self.adjust_for_elapsed_gap()
        if self.calculate_remaining_time() <= 0:
            self.accept()
        else:
            self.update_ui()

    def on_expired(self):
        self.adjust_for_elapsed_gap()
        if self.calculate_remaining_time() <= 0:
            self.accept()
        else:
            self.expiry_timer.start(math.ceil(self.calculate_remaining_time() * MILLISECONDS_PER_SECOND))

    def showEvent(self, event):
        super().showEvent(event)
        if self.paused_remaining is None:
            self.ui_timer.start(UI_REFRESH_MS)
        self.update_ui()

    def hideEvent(self, event):
        self.ui_timer.stop()
        stop_button_animations(self)
        super().hideEvent(event)

    def pause_for_system(self):
        if self.paused_remaining is None:
            self.paused_remaining = self.calculate_remaining_time()
            self.ui_timer.stop()
            self.expiry_timer.stop()

    def resume_after_system(self):
        if self.paused_remaining is not None:
            self.deadline = time.monotonic() + self.paused_remaining
            self.last_tick = time.monotonic()
            self.paused_remaining = None
            self.expiry_timer.start(math.ceil(self.calculate_remaining_time() * MILLISECONDS_PER_SECOND))
            if self.isVisible() and not self.isMinimized():
                self.ui_timer.start(UI_REFRESH_MS)
                self.update_ui()

    def done(self, result):
        self.ui_timer.stop()
        self.expiry_timer.stop()
        self.watchdog_timer.stop()
        super().done(result)


class SettingsDialog(QDialog):
    @staticmethod
    def interval_control(minimum, maximum, value, suffix):
        control = QSpinBox()
        control.setRange(minimum, maximum)
        control.setValue(value)
        control.setSuffix(suffix)
        return control

    @staticmethod
    def checkbox(label, checked, available=True, tooltip=None):
        control = QCheckBox(label)
        control.setChecked(checked)
        control.setEnabled(available)
        if tooltip:
            control.setToolTip(tooltip)
        return control

    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.owner = owner
        self.setWindowTitle("EyeBreak Settings")
        self.resize(440, 405)
        layout = surface_layout(self, (20, 12, 20, 18), 10)
        layout.addWidget(TitleBar(self, self.reject, close_tooltip="Close settings"))

        title = QLabel("Settings")
        title.setObjectName("alertTitle")
        layout.addWidget(title)

        self.sound_enabled = self.checkbox("Play a sound at break time", owner.sound_enabled)
        layout.addWidget(self.sound_enabled)

        sound_row = QHBoxLayout()
        self.sound_file = QLineEdit(str(owner.sound_path))
        self.sound_file.setPlaceholderText("Choose an MP3 or WAV file")
        sound_row.addWidget(self.sound_file)
        sound_row.addWidget(button("Browse", self.browse_sound))
        layout.addLayout(sound_row)

        volume_row = QHBoxLayout()
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(owner.volume)
        self.volume_label = QLabel(f"{owner.volume}%")
        self.volume.valueChanged.connect(lambda value: self.volume_label.setText(f"{value}%"))
        volume_row.addWidget(QLabel("Volume"))
        volume_row.addWidget(self.volume)
        volume_row.addWidget(self.volume_label)
        layout.addLayout(volume_row)

        self.tray_notifications = self.checkbox(
            "Tray notification",
            owner.tray_notifications,
            owner.tray is not None,
            "Also show a Windows notification when a break starts",
        )
        layout.addWidget(self.tray_notifications)

        form = QFormLayout()
        self.work_minutes = self.interval_control(20, 180, math.ceil(owner.work_interval / 60), " min")
        form.addRow("Work interval", self.work_minutes)
        self.break_seconds = self.interval_control(20, 120, owner.break_interval, " sec")
        form.addRow("Break length", self.break_seconds)
        layout.addLayout(form)

        self.start_hidden = self.checkbox("Start hidden in the tray", owner.start_hidden, owner.tray is not None)
        layout.addWidget(self.start_hidden)
        self.reduce_motion = self.checkbox("Reduce animations", owner.reduce_motion)
        layout.addWidget(self.reduce_motion)

        actions = QHBoxLayout()
        actions.addWidget(button("Test sound", self.preview_sound))
        actions.addStretch()
        actions.addWidget(button("Cancel", self.reject))
        actions.addWidget(button("Save", self.save, "primary"))
        layout.addLayout(actions)

    def browse_sound(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose notification sound", self.sound_file.text(), "Audio files (*.mp3 *.wav);;All files (*)"
        )
        if path:
            self.sound_file.setText(path)

    def preview_sound(self):
        path = self.selected_sound_path()
        if not path.is_file():
            QMessageBox.warning(self, "Sound not found", "Choose an existing audio file first.")
            return
        self.owner.play_sound(path, self.volume.value(), preview=True)

    def selected_sound_path(self):
        path = Path(self.sound_file.text().strip()).expanduser()
        return (path if path.is_absolute() else APP_DIR / path).resolve()

    def save(self):
        path = self.selected_sound_path()
        if self.sound_enabled.isChecked() and not path.is_file():
            QMessageBox.warning(self, "Sound not found", "Choose an existing audio file first.")
            return
        self.sound_file.setText(str(path))
        if self.owner.apply_settings(self):
            self.accept()

    def hideEvent(self, event):
        stop_button_animations(self)
        super().hideEvent(event)


class EyeBreakReminder(QWidget):
    def __init__(self, test_mode=False):
        super().__init__()
        self.load_settings()
        AnimatedButton.reduce_motion = self.reduce_motion

        self.sound_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.sound_player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(self.volume / 100)
        self.sound_player.errorOccurred.connect(self.handle_sound_error)
        self.sound_preview = False

        self.deadline = time.monotonic() + self.work_interval
        self.seconds_left = self.work_interval
        self.cycle_length = self.work_interval
        self.manual_paused = False
        self.system_holds = set()
        self.dialog = None
        self.tray = None
        self.settings_dialog = None
        self.wts_registered = False
        self.setup_ui()

        self.ui_timer = make_timer(self, self.update_ui)
        self.break_timer = make_timer(self, self.on_work_elapsed, single_shot=True)
        self.watchdog_timer = make_timer(self, self.check_elapsed_gap, WATCHDOG_INTERVAL_MS)
        self.tray_timer = make_timer(self, self.update_tray)
        if self.tray is not None:
            self.tray_timer.start(MILLISECONDS_PER_SECOND)
        self.last_tick = time.monotonic()
        self.schedule(self.work_interval)
        if test_mode:
            QTimer.singleShot(0, self.show_reminder)

        if not self.start_hidden or self.tray is None:
            self.show_controls()
        self.register_session_notifications()

    def load_settings(self):
        defaults = self.read_settings_file(DEFAULTS_FILE)
        current = self.read_settings_file(CONFIG_FILE)

        def integer(section, key, fallback, minimum, maximum):
            for source in (current, defaults):
                try:
                    value = source.getint(section, key)
                    if minimum <= value <= maximum:
                        return value
                except (configparser.Error, ValueError):
                    pass
            return fallback

        def boolean(section, key, fallback):
            for source in (current, defaults):
                try:
                    return source.getboolean(section, key)
                except (configparser.Error, ValueError):
                    pass
            return fallback

        def string(section, key, fallback):
            for source in (current, defaults):
                value = source.get(section, key, fallback="").strip()
                if value:
                    return value
            return fallback

        self.work_interval = integer("Intervals", "WORK_INTERVAL", MIN_WORK_INTERVAL, MIN_WORK_INTERVAL, 180 * 60)
        self.break_interval = integer("Intervals", "BREAK_INTERVAL", 20, 20, 120)
        self.volume = integer("Sound", "VOLUME", 70, 0, 100)
        sound = Path(string("Sound", "SOUND_FILE_PATH", "sounds/default_notification.mp3")).expanduser()
        self.sound_path = sound if sound.is_absolute() else APP_DIR / sound
        self.sound_enabled = boolean("Sound", "ENABLED", True)
        self.tray_notifications = boolean("Notifications", "TRAY", False)
        self.start_hidden = boolean("Window", "START_HIDDEN", False)
        self.reduce_motion = boolean("Window", "REDUCE_MOTION", False)

    @staticmethod
    def read_settings_file(path):
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str.upper
        try:
            parser.read(path, encoding="utf-8")
        except (OSError, configparser.Error) as exc:
            print(f"Could not read {path.name}: {exc}", file=sys.stderr)
        return parser

    def adjust_current_interval(self, previous_work_interval):
        if previous_work_interval != self.work_interval and self.dialog is None:
            elapsed = max(0, self.cycle_length - self.calculate_remaining_time())
            self.cycle_length = self.work_interval
            self.seconds_left = max(1, self.work_interval - elapsed)
            if not self.is_paused():
                self.deadline = time.monotonic() + self.seconds_left
                self.arm_break_timer()

    def write_config(self, dialog):
        # Start with saved settings so options absent from this dialog survive.
        config = self.read_settings_file(CONFIG_FILE if CONFIG_FILE.exists() else DEFAULTS_FILE)
        for section in ("Intervals", "Sound", "Notifications", "Window"):
            if not config.has_section(section):
                config.add_section(section)
        if not config.has_option("Intervals", "REMIND_EARLY_INTERVAL"):
            config.set("Intervals", "REMIND_EARLY_INTERVAL", "300")

        sound_path = dialog.selected_sound_path()
        try:
            sound_in_config = str(sound_path.relative_to(APP_DIR))
        except ValueError:
            sound_in_config = str(sound_path)
        config.set("Intervals", "WORK_INTERVAL", str(dialog.work_minutes.value() * 60))
        config.set("Intervals", "BREAK_INTERVAL", str(dialog.break_seconds.value()))
        config.set("Sound", "SOUND_FILE_PATH", sound_in_config)
        config.set("Sound", "ENABLED", str(dialog.sound_enabled.isChecked()).lower())
        config.set("Sound", "VOLUME", str(dialog.volume.value()))
        config.set("Notifications", "TRAY", str(dialog.tray_notifications.isChecked()).lower())
        config.set("Window", "START_HIDDEN", str(dialog.start_hidden.isChecked()).lower())
        config.set("Window", "REDUCE_MOTION", str(dialog.reduce_motion.isChecked()).lower())

        buffer = io.StringIO()
        config.write(buffer)
        data = buffer.getvalue().encode("utf-8")
        # QSaveFile replaces the config only after the full write succeeds.
        saved = QSaveFile(str(CONFIG_FILE))
        if not saved.open(QIODevice.OpenModeFlag.WriteOnly | QIODevice.OpenModeFlag.Text):
            raise OSError(saved.errorString())
        if saved.write(data) != len(data):
            saved.cancelWriting()
            raise OSError(saved.errorString())
        if not saved.commit():
            raise OSError(saved.errorString())

    def register_session_notifications(self):
        if sys.platform != "win32":
            return
        try:
            self.wts_api = ctypes.WinDLL("wtsapi32", use_last_error=True)
            register = self.wts_api.WTSRegisterSessionNotification
            register.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.DWORD)
            register.restype = ctypes.wintypes.BOOL
            self.wts_registered = bool(register(int(self.winId()), 0))
            if self.wts_registered:
                QApplication.instance().aboutToQuit.connect(self.unregister_session_notifications)
            else:
                print("Could not register for Windows lock notifications.", file=sys.stderr)
        except (AttributeError, OSError) as exc:
            print(f"Could not register for Windows lock notifications: {exc}", file=sys.stderr)

    def unregister_session_notifications(self):
        if self.wts_registered:
            unregister = self.wts_api.WTSUnRegisterSessionNotification
            unregister.argtypes = (ctypes.wintypes.HWND,)
            unregister.restype = ctypes.wintypes.BOOL
            unregister(int(self.winId()))
            self.wts_registered = False

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_WTSSESSION_CHANGE:
                if msg.wParam == WTS_SESSION_LOCK:
                    self.add_system_hold("lock")
                elif msg.wParam == WTS_SESSION_UNLOCK:
                    self.release_system_hold("lock")
            elif msg.message == WM_POWERBROADCAST:
                if msg.wParam == PBT_APMSUSPEND:
                    self.add_system_hold("sleep")
                elif msg.wParam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                    self.release_system_hold("sleep")
        return False, 0

    def add_system_hold(self, reason):
        if reason in self.system_holds:
            return
        if not self.is_paused() and self.dialog is None:
            self.seconds_left = self.calculate_remaining_time()
            self.break_timer.stop()
        self.system_holds.add(reason)
        self.ui_timer.stop()
        self.time_animation.stop()
        for window in (self, self.dialog, self.settings_dialog):
            if window is not None:
                stop_button_animations(window)
        self.last_tick = time.monotonic()
        if self.dialog is not None:
            self.dialog.pause_for_system()
        self.refresh_visible_surfaces()

    def release_system_hold(self, reason):
        if reason not in self.system_holds:
            return
        self.system_holds.remove(reason)
        self.last_tick = time.monotonic()
        if not self.system_holds:
            if self.dialog is not None:
                self.dialog.resume_after_system()
            elif not self.manual_paused:
                self.deadline = time.monotonic() + self.seconds_left
                self.arm_break_timer()
            if self.isVisible() and not self.isMinimized():
                self.ui_timer.start(UI_REFRESH_MS)
        self.refresh_visible_surfaces()

    def setup_ui(self):
        self.setWindowTitle("EyeBreak")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.resize(330, 180)

        icon_path = APP_DIR / "icon.ico"
        icon = (
            QIcon(str(icon_path))
            if icon_path.exists()
            else self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        )
        self.setWindowIcon(icon)

        layout = surface_layout(self, (18, 10, 18, 14), 5)
        layout.addWidget(TitleBar(self, QApplication.instance().quit, self.hide_to_tray, close_tooltip="Quit EyeBreak"))

        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        layout.addWidget(self.status_label)

        self.time_label = QLabel()
        self.time_label.setObjectName("timer")
        layout.addWidget(self.time_label)
        self.time_effect = QGraphicsOpacityEffect(self.time_label)
        self.time_label.setGraphicsEffect(self.time_effect)
        self.time_animation = QPropertyAnimation(self.time_effect, b"opacity", self)
        self.time_animation.setDuration(180)
        self.time_animation.setStartValue(0.55)
        self.time_animation.setEndValue(1.0)

        self.progress = progress_bar("Work session progress")
        layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 5, 0, 0)
        buttons.addWidget(button("Settings", self.show_settings))
        buttons.addStretch()
        self.pause_button = button("Pause", self.toggle_pause, "primary")
        buttons.addWidget(self.pause_button)
        layout.addLayout(buttons)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icon, self)
            menu = QMenu(self)
            self.status_action = QAction(self)
            self.status_action.setEnabled(False)
            menu.addAction(self.status_action)
            self.pause_action = menu.addAction("Pause", self.toggle_pause)
            menu.addAction("Show controls", self.show_controls)
            menu.addAction("Settings", self.show_settings)
            menu.addSeparator()
            menu.addAction("Quit", QApplication.instance().quit)
            menu.aboutToShow.connect(self.update_tray)
            self.tray_menu = menu
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self.tray_activated)
            self.tray.show()

    def show_controls(self):
        show_activated(self, center=not self.isVisible(), restore=True)

    def hide_to_tray(self):
        if self.tray is not None:
            self.hide()
        else:
            self.showMinimized()

    def show_settings(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self)
            self.settings_dialog.finished.connect(self.settings_closed)
            show_activated(self.settings_dialog, center=True)
        else:
            show_activated(self.settings_dialog)

    def settings_closed(self):
        self.settings_dialog.deleteLater()
        self.settings_dialog = None

    def apply_settings(self, dialog):
        try:
            self.write_config(dialog)
        except OSError as exc:
            QMessageBox.warning(dialog, "Could not save settings", f"{CONFIG_FILE.name} could not be saved:\n{exc}")
            return False

        previous_work_interval = self.work_interval
        self.sound_enabled = dialog.sound_enabled.isChecked()
        self.sound_path = dialog.selected_sound_path()
        self.volume = dialog.volume.value()
        self.tray_notifications = dialog.tray_notifications.isChecked() and self.tray is not None
        self.work_interval = dialog.work_minutes.value() * 60
        self.break_interval = dialog.break_seconds.value()
        self.start_hidden = dialog.start_hidden.isChecked() and self.tray is not None
        self.reduce_motion = dialog.reduce_motion.isChecked()
        AnimatedButton.reduce_motion = self.reduce_motion
        if self.reduce_motion:
            self.time_animation.stop()
            if self.isVisible() and not self.isMinimized():
                self.time_effect.setOpacity(1.0)
        self.audio_output.setVolume(self.volume / 100)

        self.adjust_current_interval(previous_work_interval)
        self.refresh_visible_surfaces()
        return True

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_controls()

    def schedule(self, seconds):
        self.seconds_left = seconds
        self.cycle_length = seconds
        self.deadline = time.monotonic() + seconds
        self.manual_paused = False
        self.arm_break_timer()
        if self.isVisible() and not self.isMinimized() and not self.system_holds:
            self.ui_timer.start(UI_REFRESH_MS)
        self.refresh_visible_surfaces()

    def is_paused(self):
        return self.manual_paused or bool(self.system_holds)

    def calculate_remaining_time(self):
        if self.is_paused():
            return self.seconds_left
        return max(0, self.deadline - time.monotonic())

    def arm_break_timer(self):
        self.break_timer.stop()
        if not self.is_paused() and self.dialog is None:
            self.break_timer.start(max(1, math.ceil(self.calculate_remaining_time() * MILLISECONDS_PER_SECOND)))

    def check_elapsed_gap(self):
        # Treat long event-loop gaps as sleep so the work countdown stays fair.
        now = time.monotonic()
        gap = now - self.last_tick
        self.last_tick = now
        if gap > 7 and not self.is_paused() and self.dialog is None:
            self.deadline += gap
            self.arm_break_timer()

    def on_work_elapsed(self):
        self.check_elapsed_gap()
        if self.is_paused() or self.dialog is not None:
            return
        if self.calculate_remaining_time() > 0:
            self.arm_break_timer()
        else:
            self.show_reminder()

    def display_state(self):
        if self.dialog is not None:
            status = "Take your eye break"
            return status, "Now", PROGRESS_MAX
        elif self.is_paused():
            if "lock" in self.system_holds:
                status = "Paused while PC is locked"
            elif "sleep" in self.system_holds:
                status = "Paused while PC sleeps"
            else:
                status = "Work timer paused"
        else:
            status = "Next break in"

        remaining = self.calculate_remaining_time()
        minutes, seconds = divmod(math.ceil(remaining), 60)
        progress = round(PROGRESS_MAX * (1 - remaining / self.cycle_length))
        return status, f"{minutes:02d}:{seconds:02d}", max(0, min(PROGRESS_MAX, progress))

    def update_ui(self):
        if not self.isVisible() or self.isMinimized() or self.system_holds:
            return
        status, time_text, progress = self.display_state()
        set_text_if_changed(self.status_label, status)
        set_text_if_changed(self.time_label, time_text)
        set_value_if_changed(self.progress, progress)
        set_text_if_changed(self.pause_button, "Resume" if self.manual_paused else "Pause")
        set_enabled_if_changed(self.pause_button, self.dialog is None)

    def update_tray(self):
        if self.tray is None or not self.tray.isVisible() or self.system_holds:
            return
        status, time_text, _ = self.display_state()
        set_text_if_changed(self.status_action, f"{status} {time_text}")
        set_text_if_changed(self.pause_action, "Resume" if self.manual_paused else "Pause")
        set_enabled_if_changed(self.pause_action, self.dialog is None)
        tooltip = f"EyeBreak - {status} {time_text}"
        if self.tray.toolTip() != tooltip:
            self.tray.setToolTip(tooltip)

    def refresh_visible_surfaces(self):
        self.update_ui()
        self.update_tray()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.system_holds and not self.manual_paused and self.dialog is None:
            self.ui_timer.start(UI_REFRESH_MS)
        for button in self.findChildren(AnimatedButton):
            if button.window() is self:
                button.apply_color(QColor(button.base))
        self.time_effect.setOpacity(1.0)
        self.update_ui()

    def hideEvent(self, event):
        self.ui_timer.stop()
        self.time_animation.stop()
        stop_button_animations(self)
        super().hideEvent(event)

    def toggle_pause(self):
        if self.dialog is not None:
            return
        if self.manual_paused:
            self.manual_paused = False
            if not self.system_holds:
                self.deadline = time.monotonic() + self.seconds_left
                self.arm_break_timer()
                if self.isVisible() and not self.isMinimized():
                    self.ui_timer.start(UI_REFRESH_MS)
        else:
            if not self.system_holds:
                self.seconds_left = self.calculate_remaining_time()
                self.break_timer.stop()
            self.manual_paused = True
            self.ui_timer.stop()
        self.refresh_visible_surfaces()
        self.time_animation.stop()
        if not self.reduce_motion and self.isVisible() and not self.isMinimized():
            self.time_effect.setOpacity(0.55)
            self.time_animation.start()

    def report_sound_failure(self, message):
        print(f"Could not play reminder sound: {message}", file=sys.stderr)
        if self.sound_preview:
            self.sound_preview = False
            QTimer.singleShot(
                0,
                lambda: QMessageBox.warning(self.settings_dialog or self, "Could not play sound", message),
            )

    def handle_sound_error(self, error):
        if error != QMediaPlayer.Error.NoError:
            self.report_sound_failure(self.sound_player.errorString() or "The audio format is not supported.")

    def play_sound(self, path=None, volume=None, preview=False):
        self.sound_preview = preview
        path = Path(path or self.sound_path)
        if not path.is_file():
            self.report_sound_failure(f"File not found: {path}")
            return
        try:
            self.sound_player.stop()
            self.audio_output.setVolume((self.volume if volume is None else volume) / 100)
            self.sound_player.setSource(QUrl.fromLocalFile(str(path.resolve())))
            self.sound_player.play()
        except Exception as exc:
            self.report_sound_failure(str(exc))

    def show_reminder(self):
        if self.dialog is not None:
            return
        self.break_timer.stop()
        self.ui_timer.stop()
        self.dialog = ReminderDialog(
            self.break_interval,
            self,
        )
        self.dialog.finished.connect(self.reminder_finished)
        self.refresh_visible_surfaces()
        show_activated(self.dialog, center=True)
        if self.system_holds:
            self.dialog.pause_for_system()
        if self.sound_enabled:
            self.play_sound()
        if self.tray_notifications and self.tray is not None and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(
                "EyeBreak",
                "Look at something 20 feet away.",
                QSystemTrayIcon.MessageIcon.Information,
                TRAY_MESSAGE_DURATION_MS,
            )

    def reminder_finished(self):
        self.dialog.deleteLater()
        self.dialog = None
        self.schedule(self.work_interval)


def instance_name():
    identity = f"{getpass.getuser()}|{APP_DIR}".encode()
    return "EyeBreak-" + hashlib.sha256(identity).hexdigest()[:20]


def forward_to_running(name, test_mode, timeout=300):
    client = QLocalSocket()
    client.connectToServer(name)
    if not client.waitForConnected(timeout):
        return False
    client.write(b"test" if test_mode else b"show")
    client.waitForBytesWritten(timeout)
    client.disconnectFromServer()
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="20-20-20 eye break reminder")
    parser.add_argument("--test", action="store_true", help="play the sound and show a break alert immediately")
    args = parser.parse_args()

    app = QApplication([sys.argv[0]])
    name = instance_name()
    if forward_to_running(name, args.test):
        sys.exit(0)

    server = QLocalServer()
    if not server.listen(name):
        if forward_to_running(name, args.test, timeout=1000):
            sys.exit(0)
        print(f"Could not start the EyeBreak instance server: {server.errorString()}", file=sys.stderr)
        sys.exit(1)

    window = EyeBreakReminder(test_mode=args.test)
    app.setQuitOnLastWindowClosed(window.tray is None)

    def receive_request(socket):
        request = bytes(socket.readAll()).decode("ascii", errors="ignore")
        if request == "test":
            window.show_reminder()
        window.show_controls()
        socket.disconnectFromServer()

    def accept_connection():
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: receive_request(s))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                receive_request(socket)

    server.newConnection.connect(accept_connection)
    accept_connection()
    sys.exit(app.exec())
