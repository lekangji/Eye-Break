# EyeBreak

EyeBreak v1 is a Windows tray app for the 20-20-20 eye break rule. It reminds you every 20 minutes to look at something 20 feet away for 20 seconds.

## Run

Install Python 3.11 or newer. From this folder, run:

```powershell
python -m pip install -r requirements.txt
python eye_break.py
```

Use `python eye_break.py --test` to show a break reminder immediately and play the configured sound.

## Settings

Open **Settings** in the app to change the work interval, break length, sound, volume, tray notification, startup visibility, or animations. EyeBreak writes personal settings to `config.txt` beside the script. The repository includes `defaults.ini` and the default WAV sound. Keep both files beside `eye_break.py` when running from a downloaded copy.

The app pauses its countdown while Windows is locked or asleep. Closing the control window hides it in the tray when a system tray is available. Use the tray menu to quit.
