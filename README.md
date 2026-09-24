# EyeBreak

EyeBreak v3 is an app to help you stay productive while taking care of your eyes using the 20-20-20 rule.
![Eye Break Thumbnail](https://raw.githubusercontent.com/lekangji/Eye-Break/refs/heads/main/thumbnail.png)

## Run

Install Python 3.11 or newer. From this folder, run:

```powershell
python -m pip install -r requirements.txt
python main.py
```

Use `python main.py --test` to show a break reminder immediately and play the configured sound.

## What is the 20-20-20 Rule?

The 20-20-20 rule helps reduce digital eye strain. It suggests:

- Every **20 minutes**, look at something **20 feet away** for **20 seconds**.

This app will remind you to follow this rule while working on your computer.

## Settings

Open **Settings** in the app to change the work interval, break length, sound, volume, tray notification, startup visibility, or animations. EyeBreak writes personal settings to `config.txt` beside the script. The repository includes `defaults.ini` and the default notification sound. Keep both files beside `main.py` when running from a downloaded copy.

The app pauses its countdown while Windows is locked or asleep. Closing the control window hides it in the tray when a system tray is available. Use the tray menu to quit.

## Features

- Customizable reminder intervals.
- Visual and/or audio alerts.
- Lightweight and easy to use.
- Custom sound effects
- Nice UI with PyQt

<br/>
Stay productive while taking care of your eyes! 👀✨
