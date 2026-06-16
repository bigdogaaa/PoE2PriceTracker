from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

VK_BY_NAME = {chr(code): code for code in range(ord("A"), ord("Z") + 1)}
VK_BY_NAME.update({str(i): ord(str(i)) for i in range(10)})
VK_BY_NAME.update({f"F{i}": 0x6F + i for i in range(1, 13)})


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_size_t),
        ("time", ctypes.c_uint),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


def parse_hotkey(hotkey: str) -> tuple[int, int]:
    modifiers = 0
    key = ""
    for part in hotkey.replace(" ", "").split("+"):
        upper = part.upper()
        if upper == "CTRL" or upper == "CONTROL":
            modifiers |= MOD_CONTROL
        elif upper == "ALT":
            modifiers |= MOD_ALT
        elif upper == "SHIFT":
            modifiers |= MOD_SHIFT
        elif upper in {"WIN", "WINDOWS"}:
            modifiers |= MOD_WIN
        else:
            key = upper
    if key not in VK_BY_NAME:
        raise ValueError(f"Unsupported hotkey key: {hotkey}")
    return modifiers, VK_BY_NAME[key]


class GlobalHotkeys:
    def __init__(self):
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._registrations: list[tuple[int, str, int, int, Callable[[], None]]] = []
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._next_id = 100
        self.errors: list[str] = []

    def register(self, hotkey: str, callback: Callable[[], None]) -> None:
        if self._thread is not None:
            self.errors.append(f"热键线程已启动，无法追加注册：{hotkey}")
            return
        hotkey_id = self._next_id
        self._next_id += 1
        modifiers, vk = parse_hotkey(hotkey)
        self._registrations.append((hotkey_id, hotkey, modifiers, vk, callback))
        self._callbacks[hotkey_id] = callback

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            self._ready.wait(timeout=2)

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
        self._callbacks.clear()

    def _run(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        for hotkey_id, hotkey, modifiers, vk, _callback in self._registrations:
            ok = ctypes.windll.user32.RegisterHotKey(None, hotkey_id, modifiers, vk)
            if not ok:
                self.errors.append(f"快捷键注册失败：{hotkey}")
        self._ready.set()
        msg = MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                callback = self._callbacks.get(int(msg.wParam))
                if callback:
                    callback()
        for hotkey_id, *_ in self._registrations:
            ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
