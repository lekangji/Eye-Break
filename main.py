import configparser
import os
import threading
import time
from getpass import getuser

from playsound import PlaysoundException, playsound
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QFrame, QGridLayout, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget


class ReminderDialog(QWidget):
    def __init__(self, break_interval, remind_early_interval_mins, parent=None):
        super().__init__(parent, Qt.Window)
        self.break_interval = break_interval
        self.remaining_time = break_interval
        self.remind_early_interval_mins = remind_early_interval_mins
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("20-20-20 Rule")
        self.setFixedSize(500, 150)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout()

        message = QLabel(f"Time to take a break! Look at something 20 feet away for {self.break_interval} seconds.")
        message.setStyleSheet("font-size: 12pt;")
        layout.addWidget(message)

        self.countdown_label = QLabel()
        self.countdown_label.setStyleSheet("font-size: 12pt;")
        layout.addWidget(self.countdown_label)

        remind_button = QPushButton(f"Remind me in {self.remind_early_interval_mins} minutes")
        remind_button.clicked.connect(self.remind_later)
        layout.addWidget(remind_button)

        self.setLayout(layout)

        # Setup timer for countdown
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_countdown)
        self.timer.start(1000)  # Update every second
        self.update_countdown()

    def update_countdown(self):
        if self.remaining_time > 0:
            self.countdown_label.setText(f"Time remaining: {self.remaining_time} seconds")
            self.remaining_time -= 1
        else:
            self.close()

    def remind_later(self):
        self.parent().remind_early = True
        self.close()


class EyeBreakReminder(QMainWindow):
    def __init__(self, username, config_file="config.txt"):
        super().__init__()
        self.username = username

        # Defaults
        self.work_interval = 20 * 60  # 20 minutes in seconds
        self.break_interval = 20  # 20 seconds
        self.remind_early_interval = 5 * 60  # 5 minutes
        self.sound_file_path = "sounds\\default_notification.mp3"

        self.running = True  # Changed to True by default
        self.remind_early = False
        self.reminder_thread = None

        # Parse config
        self.parse_config(config_file)
        self.remind_early_interval_mins = self.remind_early_interval // 60

        self.setup_ui()

        # Start reminder thread immediately
        self.start_reminders()

        # Make sure the window is visible
        self.show()

    def parse_config(self, config_file):
        config = configparser.ConfigParser()
        try:
            if os.path.exists(config_file):
                config.read(config_file)
                self.work_interval = int(config.get("Intervals", "WORK_INTERVAL", fallback=self.work_interval))
                self.break_interval = int(config.get("Intervals", "BREAK_INTERVAL", fallback=self.break_interval))
                self.remind_early_interval = int(
                    config.get("Intervals", "REMIND_EARLY_INTERVAL", fallback=self.remind_early_interval)
                )
                self.sound_file_path = config.get("Sound", "SOUND_FILE_PATH", fallback=self.sound_file_path)
        except Exception as e:
            print(f"Error reading config file: {e}")

    def setup_ui(self):
        self.setWindowTitle("20-20-20 Rule Reminder")
        self.setFixedSize(300, 150)

        if os.path.exists("icon.ico"):
            self.setWindowIcon(QIcon("icon.ico"))

        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # Create button frame
        button_frame = QFrame()
        button_layout = QGridLayout()
        button_frame.setLayout(button_layout)

        # Create buttons
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_reminders)
        self.start_button.setEnabled(False)  # Disabled initially since we start automatically

        self.stop_button = QPushButton("Pause")
        self.stop_button.clicked.connect(self.stop_reminders)
        self.stop_button.setEnabled(True)  # Enabled initially since we start automatically

        self.add_startup_button = QPushButton("Add to Startup")
        self.add_startup_button.clicked.connect(self.add_to_startup)

        self.remove_startup_button = QPushButton("Remove from Startup")
        self.remove_startup_button.clicked.connect(self.remove_from_startup)

        # Add buttons to layout
        button_layout.addWidget(self.start_button, 0, 0)
        button_layout.addWidget(self.stop_button, 0, 1)
        button_layout.addWidget(self.add_startup_button, 1, 0)
        button_layout.addWidget(self.remove_startup_button, 1, 1)

        layout.addWidget(button_frame)

    def play_sound(self):
        try:
            threading.Thread(target=lambda: playsound(self.sound_file_path)).start()
        except PlaysoundException:
            print("Error with playing sound. Please make sure file path is correct.")

    def show_reminder(self):
        self.play_sound()
        dialog = ReminderDialog(self.break_interval, self.remind_early_interval_mins, self)
        dialog.show()

    def reminder_loop(self):
        while self.running:
            # Use invokeMethod to safely call show_reminder from another thread
            QTimer.singleShot(0, self.show_reminder)
            if self.remind_early:
                time.sleep(self.remind_early_interval)
                self.remind_early = False
            else:
                time.sleep(self.work_interval)

    def start_reminders(self):
        if not self.reminder_thread or not self.reminder_thread.is_alive():
            self.running = True
            self.reminder_thread = threading.Thread(target=self.reminder_loop, daemon=True)
            self.reminder_thread.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def stop_reminders(self):
        self.running = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def add_to_startup(self):
        file_path = os.path.realpath(__file__)
        bat_path = rf"C:\Users\{self.username}\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\open.bat"

        try:
            with open(bat_path, "a+") as bat_file:
                bat_file.seek(0)
                if f'start "" "{file_path}"\n' in bat_file:
                    return
                bat_file.write(f'start "" "{file_path}"\n')
        except PermissionError:
            print("Permission denied. Run the script as an administrator.")

    def remove_from_startup(self):
        file_path = os.path.realpath(__file__)
        bat_path = rf"C:\Users\{self.username}\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\open.bat"

        if not os.path.exists(bat_path):
            return

        with open(bat_path, "r") as bat_file:
            lines = bat_file.readlines()

        remaining_lines = [line for line in lines if not line.startswith(f'start "" "{file_path}"')]

        try:
            with open(bat_path, "w") as bat_file:
                bat_file.writelines(remaining_lines)
        except PermissionError:
            print("Permission denied. Run the script as an administrator.")


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    username = getuser()
    window = EyeBreakReminder(username=username)
    sys.exit(app.exec_())
