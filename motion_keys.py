"""Send the configured movement keys to the Fallout session launched by the runner."""

import ctypes
from ctypes import wintypes
import time

import psutil


class KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("virtual_key", wintypes.WORD), ("scan", wintypes.WORD), ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("extra", ctypes.c_size_t),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG), ("y", wintypes.LONG), ("wheel", wintypes.LONG), ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("extra", ctypes.c_size_t),
    ]


class InputData(ctypes.Union):
    _fields_ = [("keyboard", KeyboardInput), ("mouse", MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [("kind", wintypes.DWORD), ("data", InputData)]


def send_key(key, release=False):
    user = ctypes.windll.user32
    scan = user.MapVirtualKeyW(key, 4)
    if not scan:
        raise RuntimeError(f"No Windows scan code for Fallout key {key}.")
    flags = 0x8 | (0x1 if scan >> 8 == 0xE0 else 0) | (0x2 if release else 0)
    event = Input(1, InputData(keyboard=KeyboardInput(0, scan & 0xFF, flags, 0, 0)))
    if user.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
        raise RuntimeError("Windows rejected a Fallout movement key.")


def frame_lower_body(launcher):
    check_focus(launcher)
    event = Input(0, InputData(mouse=MouseInput(0, 110, -600, 0x0801, 0, 0)))
    if ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
        raise RuntimeError("Windows rejected the third-person camera adjustment.")


def check_focus(launcher):
    user = ctypes.windll.user32
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    window_pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(window_pid))
    for game in psutil.Process(launcher.pid).children(recursive=True):
        if game.pid == window_pid.value and game.name().lower() == "fallout4.exe":
            return
    raise RuntimeError("Focus Fallout 4 before the sprint scenario.")


class SprintKeys:
    def __init__(self):
        self.held = set()
        self.release_at = {}

    def press(self, keys, launcher, seconds):
        check_focus(launcher)
        stop_at = time.monotonic() + seconds
        for key in keys:
            if not 0 < key < 256:
                raise RuntimeError("Sprint and jump require keyboard bindings.")
            send_key(key)
            self.held.add(key)
            self.release_at[key] = stop_at

    def update(self, launcher):
        if self.held:
            check_focus(launcher)
        for key in list(self.held):
            if time.monotonic() >= self.release_at[key]:
                send_key(key, release=True)
                self.held.remove(key)

    def release(self):
        for key in self.held:
            send_key(key, release=True)
        self.held.clear()
