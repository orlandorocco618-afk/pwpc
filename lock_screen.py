"""
pwpc - lock your PC with a password after a period of inactivity.

Usage:
    pythonw lock_screen.py           run in the background (first run opens the setup window)
    python  lock_screen.py --setup   change the password and the inactivity time
    python  lock_screen.py --test    show the lock screen right away, exit after unlocking

On the first run a setup window asks for a password and for how many minutes of
inactivity (no mouse or keyboard input, system-wide) must pass before the PC locks.
The password is never stored in clear text: only a salted PBKDF2-SHA256 hash is saved
in %APPDATA%\\pwpc\\config.json.

When the time is up, a full-screen, always-on-top overlay covers every connected
monitor and stays there until the right password is typed.
"""

import ctypes
import hashlib
import hmac
import json
import os
import secrets
import sys
import tkinter as tk

# Make the process DPI-aware: without this, with Windows scaling enabled
# (125%/150%...) the full-screen window can end up smaller than the real
# screen or in the wrong place.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

APP_NAME = "pwpc"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_IDLE_MINUTES = 30
MIN_PASSWORD_LENGTH = 4
PBKDF2_ITERATIONS = 200_000
CHECK_INTERVAL_MS = 5000
REASSERT_INTERVAL_MS = 500

TEST_MODE = "--test" in sys.argv
SETUP_MODE = "--setup" in sys.argv

BG = "black"
FG = "white"
ERROR_FG = "#ff5555"
FONT = "Segoe UI"


# ---------------------------------------------------------------- config

def hash_password(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def load_config():
    """The saved configuration, or None if the app has never been set up."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        if {"salt", "hash", "iterations", "idle_minutes"} <= cfg.keys():
            return cfg
    except (OSError, ValueError):
        pass
    return None


def save_config(password: str, idle_minutes: int) -> dict:
    salt = secrets.token_bytes(16)
    cfg = {
        "salt": salt.hex(),
        "hash": hash_password(password, salt),
        "iterations": PBKDF2_ITERATIONS,
        "idle_minutes": idle_minutes,
    }
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)
    return cfg


def check_password(cfg: dict, password: str) -> bool:
    attempt = hash_password(password, bytes.fromhex(cfg["salt"]), cfg["iterations"])
    return hmac.compare_digest(attempt, cfg["hash"])


# ---------------------------------------------------------------- system

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


ctypes.windll.kernel32.GetTickCount.restype = ctypes.c_uint

# System metrics for the multi-monitor layout: the "virtual" screen is the
# rectangle around every connected monitor (it can have a negative origin if
# a monitor sits left of/above the primary one), while SM_CXSCREEN/SM_CYSCREEN
# always return the size of the primary monitor only.
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


def get_virtual_screen_rect():
    """Rectangle (x, y, w, h) covering every connected monitor."""
    gsm = ctypes.windll.user32.GetSystemMetrics
    return (
        gsm(SM_XVIRTUALSCREEN),
        gsm(SM_YVIRTUALSCREEN),
        gsm(SM_CXVIRTUALSCREEN),
        gsm(SM_CYVIRTUALSCREEN),
    )


def get_idle_seconds() -> float:
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
    # GetTickCount and dwTime are unsigned 32-bit counters that wrap around
    # every ~49.7 days: the subtraction must be masked to 32 bits, otherwise
    # with an uptime above ~24.8 days the result can turn negative.
    millis = (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF
    return millis / 1000.0


# ---------------------------------------------------------------- setup window

class SetupWindow:
    """Asks for the password (twice) and the inactivity time, then saves them."""

    def __init__(self, root: tk.Tk, current: dict | None, on_done):
        self._on_done = on_done
        self._win = tk.Toplevel(root)
        self._win.title("pwpc - setup")
        self._win.configure(bg=BG, padx=30, pady=24)
        self._win.resizable(False, False)
        self._win.attributes("-topmost", True)
        self._win.protocol("WM_DELETE_WINDOW", self._cancel)

        title = "Welcome to pwpc" if current is None else "Change pwpc settings"
        tk.Label(self._win, text=title, fg=FG, bg=BG, font=(FONT, 18, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(0, 6))
        tk.Label(
            self._win, fg="#bbbbbb", bg=BG, font=(FONT, 10), justify="center",
            text="Choose the password that unlocks your PC\nand after how many minutes of inactivity it locks.",
        ).grid(row=1, column=0, columnspan=2, pady=(0, 16))

        self._pw1 = tk.StringVar()
        self._pw2 = tk.StringVar()
        self._minutes = tk.StringVar(value=str(current["idle_minutes"] if current else DEFAULT_IDLE_MINUTES))

        rows = [("Password", self._pw1, "*"), ("Confirm password", self._pw2, "*")]
        for i, (label, var, show) in enumerate(rows, start=2):
            tk.Label(self._win, text=label, fg=FG, bg=BG, font=(FONT, 11)).grid(
                row=i, column=0, sticky="w", pady=4, padx=(0, 12))
            entry = tk.Entry(self._win, textvariable=var, show=show, font=(FONT, 13), width=18)
            entry.grid(row=i, column=1, pady=4)
            if i == 2:
                entry.focus_force()

        tk.Label(self._win, text="Lock after (minutes)", fg=FG, bg=BG, font=(FONT, 11)).grid(
            row=4, column=0, sticky="w", pady=4, padx=(0, 12))
        tk.Spinbox(self._win, from_=1, to=1440, textvariable=self._minutes, font=(FONT, 13), width=6).grid(
            row=4, column=1, sticky="w", pady=4)

        self._error = tk.Label(self._win, text="", fg=ERROR_FG, bg=BG, font=(FONT, 10))
        self._error.grid(row=5, column=0, columnspan=2, pady=(10, 4))
        tk.Button(self._win, text="Save", font=(FONT, 11, "bold"), width=12, command=self._save).grid(
            row=6, column=0, columnspan=2, pady=(4, 0))
        self._win.bind("<Return>", lambda _e: self._save())

        # center on the primary monitor
        self._win.update_idletasks()
        gsm = ctypes.windll.user32.GetSystemMetrics
        w, h = self._win.winfo_width(), self._win.winfo_height()
        self._win.geometry(f"+{(gsm(SM_CXSCREEN) - w) // 2}+{(gsm(SM_CYSCREEN) - h) // 2}")

    def _save(self):
        pw = self._pw1.get()
        if len(pw) < MIN_PASSWORD_LENGTH:
            return self._error.config(text=f"The password needs at least {MIN_PASSWORD_LENGTH} characters.")
        if pw != self._pw2.get():
            return self._error.config(text="The two passwords don't match.")
        try:
            minutes = int(self._minutes.get())
        except ValueError:
            minutes = 0
        if not 1 <= minutes <= 1440:
            return self._error.config(text="Inactivity time: a whole number of minutes between 1 and 1440.")
        cfg = save_config(pw, minutes)
        self._win.destroy()
        self._on_done(cfg)

    def _cancel(self):
        self._win.destroy()
        self._on_done(None)


# ---------------------------------------------------------------- lock overlay

class LockOverlay:
    def __init__(self, root: tk.Tk, cfg: dict, on_unlock):
        self._root = root
        self._cfg = cfg
        self._on_unlock = on_unlock

        self._win = tk.Toplevel(root)
        self._win.configure(bg=BG)
        self._win.overrideredirect(True)
        # Cover the whole virtual rectangle (every monitor), so the lock
        # applies to each connected screen and not only the primary one.
        vx, vy, vw, vh = get_virtual_screen_rect()
        self._win.geometry(f"{vw}x{vh}+{vx}+{vy}")
        self._win.attributes("-topmost", True)
        self._win.protocol("WM_DELETE_WINDOW", lambda: None)
        self._win.deiconify()
        self._win.state("normal")
        self._win.update_idletasks()
        self._win.lift()
        self._win.focus_force()

        # The password box is centered on the primary monitor, not on the
        # whole virtual rectangle: centered on the union of both screens it
        # would end up straddling the border between the two monitors.
        gsm = ctypes.windll.user32.GetSystemMetrics
        pw, ph = gsm(SM_CXSCREEN), gsm(SM_CYSCREEN)
        frame = tk.Frame(self._win, bg=BG)
        frame.place(x=-vx + pw // 2, y=-vy + ph // 2, anchor="center")

        tk.Label(frame, text="PC locked", fg=FG, bg=BG, font=(FONT, 28, "bold")).pack(pady=(0, 6))
        tk.Label(frame, text="Enter your password to unlock", fg="#bbbbbb", bg=BG,
                 font=(FONT, 11)).pack(pady=(0, 14))

        self._error_label = tk.Label(frame, text="", fg=ERROR_FG, bg=BG, font=(FONT, 11))
        self._error_label.pack(pady=(0, 10))

        self._entry_var = tk.StringVar()
        entry = tk.Entry(frame, show="*", textvariable=self._entry_var,
                         font=(FONT, 16), justify="center", width=12)
        entry.pack()
        entry.bind("<Return>", lambda _e: self._check_password())
        self._entry = entry
        entry.focus_force()

        # Block the most common escape routes (best effort: without low-level
        # hooks Alt+Tab/Win cannot be blocked completely).
        for seq in ("<Alt-F4>", "<Alt-Tab>", "<Escape>", "<Control-w>"):
            self._win.bind(seq, lambda _e: "break")

        self._win.grab_set()
        self._reassert()

    def _reassert(self):
        if not self._win.winfo_exists():
            return
        self._win.lift()
        self._win.attributes("-topmost", True)
        # Focus goes to the text field, not the window: forcing it on the
        # window would move keyboard focus away from the Entry every time this
        # timer fires, leaving only a few milliseconds to type.
        if self._win.focus_get() is not self._entry:
            self._entry.focus_force()
        self._win.after(REASSERT_INTERVAL_MS, self._reassert)

    def _check_password(self):
        if check_password(self._cfg, self._entry_var.get()):
            self._win.grab_release()
            self._win.destroy()
            self._on_unlock()
        else:
            self._error_label.config(text="Wrong password")
            self._entry_var.set("")


# ---------------------------------------------------------------- main loop

class App:
    def __init__(self):
        self._root = tk.Tk()
        self._root.withdraw()
        self._locked = False
        self._cfg = load_config()
        if self._cfg is None or SETUP_MODE:
            SetupWindow(self._root, self._cfg, self._after_setup)
        else:
            self._start()

    def _after_setup(self, cfg):
        if cfg is None:
            # setup closed without saving
            if self._cfg is None:
                self._root.destroy()  # never configured: nothing to protect with
                return
        else:
            self._cfg = cfg
        if SETUP_MODE and not TEST_MODE:
            self._root.destroy()      # only changing settings: the running instance will reload them
            return
        self._start()

    def _start(self):
        if TEST_MODE:
            self._locked = True
            self._overlay = LockOverlay(self._root, self._cfg, self._on_unlock)
        self._check_idle()

    def _check_idle(self):
        # re-read the config so that changes made with --setup apply without a restart
        self._cfg = load_config() or self._cfg
        if not self._locked and get_idle_seconds() >= self._cfg["idle_minutes"] * 60:
            self._locked = True
            self._overlay = LockOverlay(self._root, self._cfg, self._on_unlock)
        self._root.after(CHECK_INTERVAL_MS, self._check_idle)

    def _on_unlock(self):
        if TEST_MODE:
            self._root.destroy()
            return
        self._locked = False

    def run(self):
        self._root.mainloop()


if __name__ == "__main__":
    App().run()
