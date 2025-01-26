import configparser
import threading
import time
import tkinter as tk
import winsound
import os

from getpass import getuser


class EyeBreakReminder:
    def __init__(self, username, config_file="config.txt"):
        self.root = tk.Tk()
        self.root.title("20-20-20 Rule Reminder")
        self.root.geometry("300x150")
        self.root.resizable(False, False)

        self.running = False
        self.remind_early = False
        self.reminder_thread = None

        # Defaults
        self.work_interval = 20 * 60  # 20 minutes in seconds
        self.break_interval = 20  # 20 seconds
        self.remind_early_interval = 5 * 60  # 5 minutes
        self.sound_pitch = 1000
        self.sound_length = 1000  # in milliseconds

        # Username
        self.username = username

        # Parse config
        self.parse_config(config_file)
        self.remind_early_interval_mins = self.remind_early_interval // 60

        self.setup_ui()

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
                self.sound_pitch = int(config.get("Sound", "PITCH", fallback=self.sound_pitch))
                self.sound_length = int(config.get("Sound", "LENGTH", fallback=self.sound_length))
        except Exception as e:
            print(f"Error reading config file: {e}")

    def setup_ui(self):
        frame = tk.Frame(self.root)
        frame.pack(expand=True, fill="both", padx=20, pady=20)

        button_frame = tk.Frame(frame)
        button_frame.pack(expand=True)

        self.start_button = tk.Button(button_frame, text="Start", command=self.start_reminders, state=tk.DISABLED)
        self.start_button.grid(row=0, column=0, padx=10)

        self.stop_button = tk.Button(button_frame, text="Pause", command=self.stop_reminders, state=tk.NORMAL)
        self.stop_button.grid(row=0, column=1, padx=10)

        self.add_to_startup_button = tk.Button(button_frame, text="Add to Startup", command=self.add_to_startup)
        self.add_to_startup_button.grid(row=1, column=0, padx=10, pady=10)

        self.remove_from_startup_button = tk.Button(
            button_frame, text="Remove from Startup", command=self.remove_from_startup
        )
        self.remove_from_startup_button.grid(row=1, column=1, padx=10, pady=10)

        # Start automatically
        self.root.after(self.work_interval, self.start_reminders)

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

        # Filter out lines for the current program
        remaining_lines = [line for line in lines if not line.startswith(f'start "" "{file_path}"')]

        try:
            with open(bat_path, "w") as bat_file:
                bat_file.writelines(remaining_lines)
        except PermissionError:
            print("Permission denied. Run the script as an administrator.")

    def play_sound(self):
        threading.Thread(target=lambda: winsound.Beep(self.sound_pitch, self.sound_length)).start()

    def show_reminder(self):
        reminder = tk.Toplevel(self.root)
        reminder.title("20-20-20 Rule")
        reminder.geometry("500x150")
        reminder.resizable(False, False)
        reminder.attributes("-toolwindow", True)
        reminder.lift()  # Bring window to front

        tk.Label(
            reminder,
            text=f"Time to take a break! Look at something 20 feet away for {self.break_interval} seconds.",
            font=("Arial", 12),
        ).pack(pady=10)

        countdown_label = tk.Label(reminder, text="", font=("Arial", 12))
        countdown_label.pack(pady=10)

        def remind_in_five():
            self.remind_early = True
            reminder.destroy()

        tk.Button(
            reminder, text=f"Remind me in {self.remind_early_interval_mins} minutes", command=remind_in_five
        ).pack()

        self.play_sound()

        def update_countdown(seconds):
            if not reminder.winfo_exists():
                return
            if seconds > 0:
                countdown_label.config(text=f"Time remaining: {seconds} seconds")
                reminder.after(1000, update_countdown, seconds - 1)
            else:
                reminder.destroy()

        update_countdown(self.break_interval)

    def reminder_loop(self):
        while self.running:
            self.root.after(0, self.show_reminder)
            if self.remind_early:
                time.sleep(self.remind_early_interval)
                self.remind_early = False
            else:
                time.sleep(self.work_interval)

    def start_reminders(self):
        self.running = True
        self.reminder_thread = threading.Thread(target=self.reminder_loop, daemon=True)
        self.reminder_thread.start()
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)

    def stop_reminders(self):
        self.running = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    username = getuser()

    app = EyeBreakReminder(username=username)
    app.run()
