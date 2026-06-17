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
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WH_KEYBOARD_LL = 13
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C

VK_BY_NAME = {chr(code): code for code in range(ord("A"), ord("Z") + 1)}
VK_BY_NAME.update({str(i): ord(str(i)) for i in range(10)})
VK_BY_NAME.update({f"F{i}": 0x6F + i for i in range(1, 13)})
VK_BY_NAME["SPACE"] = 0x20


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


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.c_uint),
        ("scanCode", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("time", ctypes.c_uint),
        ("dwExtraInfo", ctypes.c_size_t),
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
        self._fallback_callbacks: dict[tuple[int, int], Callable[[], None]] = {}
        self._active_fallbacks: set[tuple[int, int]] = set()
        self._hook_handle = None
        self._hook_proc = None
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
        self._fallback_callbacks.clear()
        self._active_fallbacks.clear()

    def _run(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        failed: list[tuple[str, int, int, Callable[[], None]]] = []
        for hotkey_id, hotkey, modifiers, vk, callback in self._registrations:
            ok = ctypes.windll.user32.RegisterHotKey(None, hotkey_id, modifiers, vk)
            if not ok:
                failed.append((hotkey, modifiers, vk, callback))
        if failed:
            for _hotkey, modifiers, vk, callback in failed:
                self._fallback_callbacks[(modifiers, vk)] = callback
            if not self._start_keyboard_hook():
                for hotkey, *_ in failed:
                    self.errors.append(f"快捷键注册失败：{hotkey}")
        self._ready.set()
        msg = MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                callback = self._callbacks.get(int(msg.wParam))
                if callback:
                    callback()
        if self._hook_handle:
            ctypes.windll.user32.UnhookWindowsHookEx(self._hook_handle)
            self._hook_handle = None
            self._hook_proc = None
        for hotkey_id, *_ in self._registrations:
            ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)

    def _start_keyboard_hook(self) -> bool:
        hook_proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p)

        def proc(n_code, w_param, l_param):
            if n_code >= 0:
                try:
                    event = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    vk = int(event.vkCode)
                    if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        modifiers = self._current_modifiers()
                        combo = (modifiers, vk)
                        callback = self._fallback_callbacks.get(combo)
                        if callback and combo not in self._active_fallbacks:
                            self._active_fallbacks.add(combo)
                            callback()
                    elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                        self._active_fallbacks = {combo for combo in self._active_fallbacks if combo[1] != vk}
                except Exception:
                    pass
            return ctypes.windll.user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

        self._hook_proc = hook_proc_type(proc)
        ctypes.windll.kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        ctypes.windll.user32.SetWindowsHookExW.restype = ctypes.c_void_p
        ctypes.windll.user32.CallNextHookEx.restype = ctypes.c_ssize_t
        module_handle = ctypes.windll.kernel32.GetModuleHandleW(None)
        self._hook_handle = ctypes.windll.user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_proc, module_handle, 0)
        return bool(self._hook_handle)

    @staticmethod
    def _current_modifiers() -> int:
        user32 = ctypes.windll.user32
        modifiers = 0
        if user32.GetAsyncKeyState(VK_CONTROL) & 0x8000:
            modifiers |= MOD_CONTROL
        if user32.GetAsyncKeyState(VK_SHIFT) & 0x8000:
            modifiers |= MOD_SHIFT
        if user32.GetAsyncKeyState(VK_MENU) & 0x8000:
            modifiers |= MOD_ALT
        if (user32.GetAsyncKeyState(VK_LWIN) | user32.GetAsyncKeyState(VK_RWIN)) & 0x8000:
            modifiers |= MOD_WIN
        return modifiers
