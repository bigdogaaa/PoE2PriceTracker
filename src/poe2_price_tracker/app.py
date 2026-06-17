from __future__ import annotations

import queue
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    TOP,
    X,
    Y,
    Button,
    Canvas,
    Entry,
    Frame,
    Label,
    LabelFrame,
    Menu,
    Radiobutton,
    StringVar,
    Text,
    Tk,
    Toplevel,
    filedialog,
    messagebox,
)
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk
try:
    import pystray
except Exception:
    pystray = None
try:
    import ttkbootstrap as tb
except Exception:
    tb = None

Button = ttk.Button
Entry = ttk.Entry
Radiobutton = ttk.Radiobutton
Combobox = ttk.Combobox

ERROR_ALREADY_EXISTS = 183
_INSTANCE_MUTEX_HANDLE = None

from .bundled_assets import app_icon_path, seed_bundled_currency_icons
from . import __version__
from .config import AppConfig, load_config, save_config
from .currencies import BASE_CURRENCIES
from .clipboard_parser import parse_poe_clipboard_item
from .db import MarketRow, PriceDatabase, PriceStats, convert_amount, normalize_name, trend_percent
from .hotkeys import GlobalHotkeys, parse_hotkey
from .ocr import RapidOcr
from .parser import ParsedItemPrice, ParsedPrice, find_number, meaningful_lines, parse_item_price_rows, parse_ocr_text
from .poe2db_sync import fetch_all_economy_prices
from .screenshot import (
    capture_around_cursor,
    capture_full_screen,
    capture_full_screen_image,
    crop_and_prepare_for_ocr,
    crop_image,
    prepare_image_for_ocr,
)
from .structure import RecognizedItemCandidate, recognize_item_candidates, recognize_structured_prices
from .updater import UpdateInfo, check_update, download_update


class ConfirmPriceDialog:
    def __init__(
        self,
        parent: Tk,
        parsed: ParsedPrice,
        image_path: Path,
        ocr_message: str,
    ):
        self.result: tuple[str, float, str, str, float, str] | None = None
        self.window = Toplevel(parent)
        self.window.title("确认价格记录")
        self.window.geometry("640x520")
        self.window.transient(parent)
        self.window.grab_set()

        self.item_var = StringVar(value=parsed.item_name)
        self.amount_var = StringVar(value="" if parsed.amount is None else str(parsed.amount))
        self.currency_var = StringVar(value=parsed.currency)
        self.source_var = StringVar(value="screenshot")

        form = Frame(self.window, padx=12, pady=12)
        form.pack(fill=BOTH, expand=True)

        Label(form, text="物品名").pack(anchor="w")
        Entry(form, textvariable=self.item_var).pack(fill=X, pady=(0, 8))

        row = Frame(form)
        row.pack(fill=X, pady=(0, 8))
        left = Frame(row)
        left.pack(side=LEFT, fill=X, expand=True)
        right = Frame(row)
        right.pack(side=RIGHT, fill=X, expand=True, padx=(8, 0))
        Label(left, text="价格数量").pack(anchor="w")
        Entry(left, textvariable=self.amount_var).pack(fill=X)
        Label(right, text="价格单位").pack(anchor="w")
        Combobox(right, textvariable=self.currency_var, values=BASE_CURRENCIES).pack(fill=X)

        Label(form, text="来源").pack(anchor="w")
        Entry(form, textvariable=self.source_var).pack(fill=X, pady=(0, 8))

        message = f"识别提示：{ocr_message}" if ocr_message else "识别完成"
        Label(form, text=message, foreground="#555").pack(anchor="w", pady=(0, 4))
        Label(form, text=f"截图：{image_path}").pack(anchor="w", pady=(0, 8))

        Label(form, text="原始识别文本").pack(anchor="w")
        self.raw_text = Text(form, height=12, wrap="word")
        self.raw_text.pack(fill=BOTH, expand=True)
        self.raw_text.insert("1.0", parsed.raw_text)

        buttons = Frame(form)
        buttons.pack(fill=X, pady=(10, 0))
        Button(buttons, text="保存", command=self._save).pack(side=RIGHT)
        Button(buttons, text="取消", command=self.window.destroy).pack(side=RIGHT, padx=(0, 8))

    def _save(self) -> None:
        item = self.item_var.get().strip()
        amount_text = self.amount_var.get().strip()
        currency = self.currency_var.get().strip()
        source = self.source_var.get().strip() or "screenshot"
        if not item:
            messagebox.showwarning("缺少物品名", "请填写物品名。", parent=self.window)
            return
        try:
            amount = float(amount_text.replace(",", "."))
        except ValueError:
            messagebox.showwarning("价格格式错误", "价格数量需要是数字。", parent=self.window)
            return
        if not currency:
            messagebox.showwarning("缺少价格单位", "请填写价格单位。", parent=self.window)
            return
        raw = self.raw_text.get("1.0", END).strip()
        self.result = (item, amount, currency, source, 1.0, raw)
        self.window.destroy()


class HotkeyCaptureButton(Button):
    MODIFIER_KEYS = {
        "Control_L",
        "Control_R",
        "Shift_L",
        "Shift_R",
        "Alt_L",
        "Alt_R",
        "Win_L",
        "Win_R",
    }

    def __init__(self, parent, variable: StringVar):
        self.variable = variable
        self.capturing = False
        super().__init__(parent, textvariable=variable, command=self.start_capture)

    def start_capture(self) -> None:
        self.capturing = True
        self.configure(textvariable="", text="请按快捷键...")
        self.focus_set()
        self.bind("<KeyPress>", self._capture)
        self.bind("<FocusOut>", self._cancel)

    def _cancel(self, _event=None) -> None:
        if self.capturing:
            self.capturing = False
            self.configure(textvariable=self.variable)
            self.unbind("<KeyPress>")
            self.unbind("<FocusOut>")

    def _capture(self, event) -> str:
        if event.keysym == "Escape":
            self._cancel()
            return "break"
        if event.keysym in self.MODIFIER_KEYS:
            return "break"

        parts = []
        if ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000:
            parts.append("Ctrl")
        if ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000:
            parts.append("Shift")
        if ctypes.windll.user32.GetAsyncKeyState(0x12) & 0x8000:
            parts.append("Alt")

        key = event.keysym.upper()
        if len(key) == 1 and key.isalnum():
            parts.append(key)
        elif key.startswith("F") and key[1:].isdigit():
            parts.append(key)
        elif key == "SPACE":
            parts.append("Space")
        else:
            self.configure(textvariable="", text="不支持这个按键")
            self.after(900, self._cancel)
            return "break"

        self.variable.set("+".join(parts))
        self._cancel()
        return "break"


class SettingsDialog:
    def __init__(self, parent: Tk, config: AppConfig):
        self.config = config
        self.window = Toplevel(parent)
        self.window.title("配置")
        self.window.geometry("620x480")
        self.window.transient(parent)
        self.window.grab_set()

        self.manifest_var = StringVar(value=config.update_manifest)
        self.lookup_hotkey_var = StringVar(value=config.hotkeys.lookup_hovered)
        self.focus_hotkey_var = StringVar(value=config.hotkeys.focus_search)
        self.quick_hotkey_var = StringVar(value=config.hotkeys.quick_price)

        body = Frame(self.window, padx=18, pady=16)
        body.pack(fill=BOTH, expand=True)

        Label(
            body,
            text="快捷键",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w")
        for label, variable in [
            ("截图识别", self.lookup_hotkey_var),
            ("聚焦搜索框", self.focus_hotkey_var),
            ("快速查价", self.quick_hotkey_var),
        ]:
            row = Frame(body)
            row.pack(fill=X, pady=(8, 0))
            Label(row, text=label, width=16, anchor="w").pack(side=LEFT)
            HotkeyCaptureButton(row, variable).pack(side=LEFT, fill=X, expand=True)

        Label(
            body,
            text="程序已按国服中文默认调好截图识别。通常不需要额外配置。",
            foreground="#555",
            wraplength=540,
            justify=LEFT,
        ).pack(anchor="w", pady=(16, 0))

        Label(body, text="更新地址", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(18, 0))
        Entry(body, textvariable=self.manifest_var).pack(fill=X, pady=(8, 0))

        buttons = Frame(body)
        buttons.pack(fill=X, pady=(10, 0))
        Button(buttons, text="保存", command=self._save).pack(side=RIGHT)
        Button(buttons, text="取消", command=self.window.destroy).pack(side=RIGHT, padx=(0, 8))

    def _save(self) -> None:
        hotkeys = [
            self.lookup_hotkey_var.get().strip(),
            self.focus_hotkey_var.get().strip(),
            self.quick_hotkey_var.get().strip(),
        ]
        try:
            for hotkey in hotkeys:
                parse_hotkey(hotkey)
        except ValueError as exc:
            messagebox.showwarning("快捷键格式错误", str(exc), parent=self.window)
            return
        if len({hotkey.lower() for hotkey in hotkeys}) != len(hotkeys):
            messagebox.showwarning("快捷键重复", "快捷键不能重复。", parent=self.window)
            return
        self.config.hotkeys.lookup_hovered = hotkeys[0]
        self.config.hotkeys.focus_search = hotkeys[1]
        self.config.hotkeys.quick_price = hotkeys[2]
        self.config.update_manifest = self.manifest_var.get().strip()
        save_config(self.config)
        self.window.destroy()


class ScreenshotSelectionOverlay:
    def __init__(self, parent: Tk, image_source: Path | Image.Image, on_confirm, on_cancel=None):
        self.parent = parent
        self.image_source = image_source
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel
        self.window = Toplevel(parent)
        self.window.title("选择截图区域")
        self.window.attributes("-topmost", True)
        self.window.overrideredirect(True)
        self.window.geometry(
            f"{self.window.winfo_screenwidth()}x{self.window.winfo_screenheight()}+0+0"
        )
        self.window.focus_force()

        if isinstance(image_source, Image.Image):
            self.original = image_source
        else:
            self.original = Image.open(image_source)
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        self.scale = min(screen_w / self.original.width, screen_h / self.original.height)
        display_size = (
            int(self.original.width * self.scale),
            int(self.original.height * self.scale),
        )
        self.display_image = self.original.resize(display_size, Image.Resampling.BILINEAR).convert("RGB")
        dimmed = self.display_image.convert("RGBA")
        shade = Image.new("RGBA", dimmed.size, (0, 0, 0, 115))
        dimmed = Image.alpha_composite(dimmed, shade).convert("RGB")
        self.photo = ImageTk.PhotoImage(dimmed)
        self.selection_photo = None
        self.selection_image_id: int | None = None

        self.canvas = Canvas(
            self.window,
            width=display_size[0],
            height=display_size[1],
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill=BOTH, expand=True)
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.create_text(
            24,
            24,
            anchor="nw",
            text="拖拽选择要识别的区域，松开后点确认",
            fill="#f5f5f5",
            font=("Microsoft YaHei UI", 16, "bold"),
        )

        self.start: tuple[int, int] | None = None
        self.rect_id: int | None = None
        self.box: tuple[int, int, int, int] | None = None
        self.action_window: Toplevel | None = None
        self._last_drag_preview_at = 0.0
        self._last_drag_preview_box: tuple[int, int, int, int] | None = None

        self.canvas.bind("<ButtonPress-1>", self._start)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._finish)
        self.window.bind("<Escape>", lambda _event: self.cancel())

    def _start(self, event) -> None:
        self.start = (event.x, event.y)
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        if self.selection_image_id:
            self.canvas.delete(self.selection_image_id)
            self.selection_image_id = None
        if self.action_window:
            self.action_window.destroy()
            self.action_window = None
        self.rect_id = self.canvas.create_rectangle(
            event.x,
            event.y,
            event.x,
            event.y,
            outline="#58a6ff",
            width=3,
        )

    def _drag(self, event) -> None:
        if self.start and self.rect_id:
            x0, y0 = self.start
            x1, y1 = event.x, event.y
            left, right = sorted((x0, x1))
            top, bottom = sorted((y0, y1))
            preview_box = (left, top, right, bottom)
            now = time.monotonic()
            if self._should_update_drag_preview(preview_box, now):
                if self.selection_image_id:
                    self.canvas.delete(self.selection_image_id)
                if right > left and bottom > top:
                    crop = self.display_image.crop((left, top, right, bottom))
                    self.selection_photo = ImageTk.PhotoImage(crop)
                    self.selection_image_id = self.canvas.create_image(left, top, anchor="nw", image=self.selection_photo)
                self._last_drag_preview_at = now
                self._last_drag_preview_box = preview_box
            self.canvas.coords(self.rect_id, x0, y0, x1, y1)
            self.canvas.tag_raise(self.rect_id)

    def _should_update_drag_preview(self, box: tuple[int, int, int, int], now: float) -> bool:
        if self._last_drag_preview_box is None:
            return True
        if now - self._last_drag_preview_at >= 0.025:
            return True
        return any(abs(current - previous) >= 8 for current, previous in zip(box, self._last_drag_preview_box))

    def _finish(self, event) -> None:
        if not self.start:
            return
        x0, y0 = self.start
        x1, y1 = event.x, event.y
        if abs(x1 - x0) < 12 or abs(y1 - y0) < 12:
            return
        self.box = self._to_original_box((x0, y0, x1, y1))
        self._show_actions(max(x0, x1), max(y0, y1))

    def _to_original_box(self, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = box
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        return (
            int(left / self.scale),
            int(top / self.scale),
            int(right / self.scale),
            int(bottom / self.scale),
        )

    def _show_actions(self, x: int, y: int) -> None:
        if self.action_window:
            self.action_window.destroy()
        self.action_window = Toplevel(self.window)
        self.action_window.overrideredirect(True)
        self.action_window.attributes("-topmost", True)
        self.action_window.geometry(f"+{min(x + 12, self.window.winfo_screenwidth() - 180)}+{min(y + 12, self.window.winfo_screenheight() - 58)}")
        frame = Frame(self.action_window, padx=8, pady=8, bg="#20242a")
        frame.pack()
        Button(frame, text="确认", command=self.confirm).pack(side=LEFT)
        Button(frame, text="取消", command=self.cancel).pack(side=LEFT, padx=(8, 0))

    def confirm(self) -> None:
        if not self.box:
            return
        box = self.box
        self.window.destroy()
        self.on_confirm(self.image_source, box)

    def cancel(self) -> None:
        self.window.destroy()
        if self.on_cancel:
            self.on_cancel()


class OcrReviewDialog:
    def __init__(
        self,
        parent: Tk,
        db: PriceDatabase,
        rows: list[ParsedItemPrice],
        raw_text: str,
        screenshot_path: Path,
        on_saved,
    ):
        self.parent = parent
        self.db = db
        self.rows = rows
        self.raw_text = raw_text
        self.screenshot_path = screenshot_path
        self.on_saved = on_saved
        self.currency_var = StringVar(value="Exalted Orb")

        self.window = Toplevel(parent)
        self.window.title("识别结果")
        self.window.geometry("920x620")
        self.window.minsize(760, 520)

        body = Frame(self.window, padx=16, pady=16)
        body.pack(fill=BOTH, expand=True)
        top = Frame(body)
        top.pack(fill=X)
        Label(top, text="识别结果", font=("Microsoft YaHei UI", 16, "bold")).pack(side=LEFT)
        Label(top, text="价格单位").pack(side=RIGHT, padx=(12, 6))
        self.currency_combo = Combobox(
            top,
            textvariable=self.currency_var,
            values=BASE_CURRENCIES,
            width=26,
        )
        self.currency_combo.pack(side=RIGHT)
        self.currency_combo.bind("<KeyRelease>", self._filter_currency)

        columns = ("item", "amount", "currency", "raw")
        self.tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("item", text="Item")
        self.tree.heading("amount", text="Price")
        self.tree.heading("currency", text="Currency")
        self.tree.heading("raw", text="原始识别内容")
        self.tree.column("item", width=260)
        self.tree.column("amount", width=100)
        self.tree.column("currency", width=140)
        self.tree.column("raw", width=300)
        self.tree.pack(fill=BOTH, expand=True, pady=(12, 0))
        for index, row in enumerate(rows):
            self.tree.insert(
                "",
                END,
                iid=str(index),
                values=(row.item_name, f"{row.amount:g}", row.currency, row.raw_text),
            )

        actions = Frame(body)
        actions.pack(fill=X, pady=(12, 0))
        Button(actions, text="入库选中", command=self.save_selected).pack(side=RIGHT)
        Button(actions, text="全部入库", command=self.save_all).pack(side=RIGHT, padx=(0, 8))
        Button(actions, text="查看识别原文", command=self.show_raw).pack(side=LEFT)

    def _filter_currency(self, _event=None) -> None:
        query = self.currency_var.get().lower()
        values = [name for name in BASE_CURRENCIES if query in name.lower()]
        self.currency_combo.configure(values=values or BASE_CURRENCIES)

    def _save_indices(self, indices: list[int]) -> None:
        currency = self.currency_var.get().strip() or "Exalted Orb"
        saved = 0
        for index in indices:
            row = self.rows[index]
            self.db.add_price_record(
                row.item_name,
                row.amount,
                row.currency or currency,
                "ocr-selection",
                confidence=max(0.85, min(1.0, 0.55 + row.item_match_score * 0.2 + row.currency_match_score * 0.25)),
                raw_text=self.raw_text,
                screenshot_path=str(self.screenshot_path),
            )
            saved += 1
        if saved:
            self.on_saved()
        messagebox.showinfo("入库完成", f"已保存 {saved} 条价格记录。", parent=self.window)

    def save_selected(self) -> None:
        indices = [int(iid) for iid in self.tree.selection()]
        if not indices:
            messagebox.showwarning("未选择", "请先在列表中选择要入库的行。", parent=self.window)
            return
        self._save_indices(indices)

    def save_all(self) -> None:
        self._save_indices(list(range(len(self.rows))))

    def show_raw(self) -> None:
        window = Toplevel(self.window)
        window.title("识别原文")
        window.geometry("720x480")
        text = Text(window, wrap="word")
        text.pack(fill=BOTH, expand=True)
        text.insert("1.0", self.raw_text)


class RegionOcrWorkbench:
    def __init__(
        self,
        parent: Tk,
        config: AppConfig,
        db: PriceDatabase,
        image_path: Path,
        on_saved,
    ):
        self.parent = parent
        self.config = config
        self.db = db
        self.image_path = image_path
        self.on_saved = on_saved
        self.mode_var = StringVar(value="item")
        self.item_var = StringVar()
        self.amount_var = StringVar()
        self.currency_var = StringVar(value="Divine Orb")
        self.status_var = StringVar(value="先框选物品名区域，再框选价格区域。")
        self.rectangles: dict[str, tuple[int, int, int, int]] = {}
        self.canvas_rects: dict[str, int] = {}
        self.drag_start: tuple[int, int] | None = None
        self.active_rect_id: int | None = None

        self.window = Toplevel(parent)
        self.window.title("截图识别实验台")
        self.window.geometry("1180x820")
        self.window.minsize(980, 680)

        self.original = Image.open(image_path)
        max_w, max_h = 760, 600
        scale = min(max_w / self.original.width, max_h / self.original.height, 1.0)
        self.scale = scale
        display_size = (
            max(1, int(self.original.width * scale)),
            max(1, int(self.original.height * scale)),
        )
        self.display = self.original.resize(display_size)
        self.photo = ImageTk.PhotoImage(self.display)

        self._build_ui()

    def _build_ui(self) -> None:
        root = Frame(self.window, padx=18, pady=18)
        root.pack(fill=BOTH, expand=True)

        left = LabelFrame(root, text="截图区域", padx=12, pady=12)
        left.pack(side=LEFT, fill=BOTH, expand=True)
        self.canvas = Canvas(
            left,
            width=self.photo.width(),
            height=self.photo.height(),
            highlightthickness=0,
            bg="#151515",
        )
        self.canvas.pack(fill=BOTH, expand=True)
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._finish_drag)

        right = Frame(root)
        right.pack(side=LEFT, fill=BOTH, padx=(18, 0))

        mode = LabelFrame(right, text="1. 选择要框的字段", padx=12, pady=12)
        mode.pack(fill=X)
        Radiobutton(mode, text="物品名 item", variable=self.mode_var, value="item").pack(anchor="w")
        Radiobutton(mode, text="价格 price", variable=self.mode_var, value="price").pack(anchor="w")

        actions = LabelFrame(right, text="2. 识别", padx=12, pady=12)
        actions.pack(fill=X, pady=(14, 0))
        Button(actions, text="识别框选区域", command=self.recognize_regions).pack(fill=X)
        Button(actions, text="清空框选", command=self.clear_regions).pack(fill=X, pady=(8, 0))
        Label(actions, textvariable=self.status_var, wraplength=320, justify=LEFT).pack(anchor="w", pady=(10, 0))

        result = LabelFrame(right, text="3. 确认并入库", padx=12, pady=12)
        result.pack(fill=X, pady=(14, 0))
        Label(result, text="物品名").pack(anchor="w")
        Entry(result, textvariable=self.item_var, width=42).pack(fill=X, pady=(0, 8))
        Label(result, text="价格数量").pack(anchor="w")
        Entry(result, textvariable=self.amount_var).pack(fill=X, pady=(0, 8))
        Label(result, text="价格单位").pack(anchor="w")
        Combobox(result, textvariable=self.currency_var, values=BASE_CURRENCIES).pack(fill=X, pady=(0, 10))
        Button(result, text="保存到价格库", command=self.save_record).pack(fill=X)

        raw_box = LabelFrame(right, text="识别原文", padx=12, pady=12)
        raw_box.pack(fill=BOTH, expand=True, pady=(14, 0))
        self.raw_text = Text(raw_box, height=10, width=42, wrap="word")
        self.raw_text.pack(fill=BOTH, expand=True)

    def _start_drag(self, event) -> None:
        self.drag_start = (event.x, event.y)
        color = "#2ecc71" if self.mode_var.get() == "item" else "#f39c12"
        self.active_rect_id = self.canvas.create_rectangle(
            event.x,
            event.y,
            event.x,
            event.y,
            outline=color,
            width=3,
        )

    def _drag(self, event) -> None:
        if self.drag_start and self.active_rect_id:
            x0, y0 = self.drag_start
            self.canvas.coords(self.active_rect_id, x0, y0, event.x, event.y)

    def _finish_drag(self, event) -> None:
        if not self.drag_start or not self.active_rect_id:
            return
        mode = self.mode_var.get()
        old_rect = self.canvas_rects.get(mode)
        if old_rect:
            self.canvas.delete(old_rect)
        self.canvas_rects[mode] = self.active_rect_id
        x0, y0 = self.drag_start
        self.rectangles[mode] = self._to_original_box((x0, y0, event.x, event.y))
        self.drag_start = None
        self.active_rect_id = None
        self.status_var.set(f"已选择 {mode} 区域。")

    def _to_original_box(self, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        if self.scale <= 0:
            return box
        x0, y0, x1, y1 = box
        return (
            int(x0 / self.scale),
            int(y0 / self.scale),
            int(x1 / self.scale),
            int(y1 / self.scale),
        )

    def clear_regions(self) -> None:
        for rect_id in self.canvas_rects.values():
            self.canvas.delete(rect_id)
        self.rectangles.clear()
        self.canvas_rects.clear()
        self.raw_text.delete("1.0", END)
        self.status_var.set("框选已清空。")

    def recognize_regions(self) -> None:
        missing = [name for name in ("item", "price") if name not in self.rectangles]
        if missing:
            messagebox.showwarning("缺少区域", "请先框选物品名区域和价格区域。", parent=self.window)
            return

        ocr = RapidOcr(
            cpu_threads=getattr(self.config, "ocr_cpu_threads", 0),
            execution_provider=getattr(self.config, "ocr_execution_provider", "cpu"),
        )
        item_crop = crop_image(
            self.image_path,
            self.rectangles["item"],
            self.config.screenshots_path,
            "item-region",
            max_files=max(1, int(getattr(self.config, "screenshot_retention_count", 20) or 20)),
        )
        price_crop = crop_image(
            self.image_path,
            self.rectangles["price"],
            self.config.screenshots_path,
            "price-region",
            max_files=max(1, int(getattr(self.config, "screenshot_retention_count", 20) or 20)),
        )
        item_result = ocr.recognize(item_crop)
        price_result = ocr.recognize(price_crop)
        raw = (
            "[item]\n"
            f"{item_result.text}\n\n"
            "[price]\n"
            f"{price_result.text}\n\n"
            f"item crop: {item_crop}\n"
            f"price crop: {price_crop}\n"
        )
        if item_result.message or price_result.message:
            raw += f"\nmessage: {item_result.message or price_result.message}"
        self.raw_text.delete("1.0", END)
        self.raw_text.insert("1.0", raw)

        item_lines = meaningful_lines(item_result.text)
        combined = "\n".join([item_lines[0] if item_lines else "", price_result.text])
        parsed = parse_ocr_text(combined)
        if item_lines:
            self.item_var.set(item_lines[0])
        elif parsed.item_name:
            self.item_var.set(parsed.item_name)
        if parsed.amount is not None:
            self.amount_var.set(f"{parsed.amount:g}")
        else:
            amount = find_number(price_result.text)
            if amount is not None:
                self.amount_var.set(f"{amount:g}")
        if parsed.currency:
            self.currency_var.set(parsed.currency)
        if not item_result.ok or not price_result.ok:
            self.status_var.set("截图识别未完整返回文本。请缩小或重新框选区域。")
        else:
            self.status_var.set("识别完成，请确认后保存。")

    def save_record(self) -> None:
        item = self.item_var.get().strip()
        currency = self.currency_var.get().strip()
        try:
            amount = float(self.amount_var.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showwarning("价格格式错误", "价格数量需要是数字。", parent=self.window)
            return
        if not item or not currency:
            messagebox.showwarning("缺少信息", "请确认物品名和价格单位。", parent=self.window)
            return
        raw = self.raw_text.get("1.0", END).strip()
        self.db.add_price_record(
            item,
            amount,
            currency,
            "region-screenshot",
            confidence=0.9,
            raw_text=raw,
            screenshot_path=str(self.image_path),
        )
        self.on_saved(item)
        self.status_var.set(f"已保存：{item} = {amount:g} {currency}")


class PriceTrackerApp:
    def __init__(self, root: Tk):
        self.root = root
        self.config = load_config()
        self.db = PriceDatabase(self.config.database_path)
        self.bundled_currency_icon_count = seed_bundled_currency_icons(self.db)
        self.ocr = self._make_ocr_engine()
        self.ocr_lock = threading.Lock()
        self.hotkeys = GlobalHotkeys()
        self.events: queue.Queue[object] = queue.Queue()
        self._draining_events = False

        self.search_var = StringVar()
        self.focus_search_var = StringVar()
        self.item_var = StringVar()
        self.amount_var = StringVar()
        self.currency_var = StringVar(value="Divine Orb")
        self.source_var = StringVar(value="人工添加")
        self.status_var = StringVar(value=f"数据目录：{self.config.data_path}")
        self.progress_var = StringVar(value="就绪")
        self.tray_icon = None
        self.syncing = False
        self.updating = False
        self.page_var = StringVar(value="1")
        self.page_size_var = StringVar(value=str(self.config.page_size))
        self.display_currency_var = StringVar(value=self.config.display_currency)
        self.sort_column = "latest_at"
        self.sort_descending = True
        self.source_filter_var = StringVar(value="全部来源")
        self.trend_widgets = []
        self.trend_data = {}
        self.market_icon_images = {}
        self.search_debounce_job = None
        self.trend_render_job = None
        self._ignore_unmap_prompt = False
        self.context_item_name = ""
        self._quick_price_foreground_hwnd = 0
        self.quick_price_overlay = None
        self.quick_price_overlay_labels = {}
        self.quick_price_overlay_hide_job = None
        self.quick_price_overlay_watch_token = 0
        self.focus_search_overlay = None
        self.focus_search_entry = None
        self.focus_search_results = None
        self.focus_search_outer_canvas = None
        self.focus_search_container = None
        self.focus_search_container_window = None
        self.focus_search_results_canvas = None
        self.focus_search_result_window = None
        self.focus_search_results_scrollbar = None
        self.focus_search_job = None
        self.screenshot_lookup_overlay = None
        self.screenshot_lookup_outer_canvas = None
        self.screenshot_lookup_container = None
        self.screenshot_lookup_container_window = None
        self.screenshot_lookup_results = None
        self.screenshot_lookup_results_canvas = None
        self.screenshot_lookup_result_window = None
        self.screenshot_lookup_results_scrollbar = None
        self.screenshot_lookup_loading_label = None
        self.screenshot_lookup_animation_job = None
        self.screenshot_lookup_animation_step = 0
        self.screenshot_lookup_watch_token = 0
        self.screenshot_lookup_drag_start: tuple[int, int, int, int] | None = None
        self.screenshot_lookup_drag_moved = False
        self._restore_after_area_capture = False
        self._area_capture_active = False
        self.ocr_review_rows: list[ParsedItemPrice] = []
        self.ocr_review_raw_text = ""
        self.ocr_review_image_path = Path()
        self.ocr_selected_index: int | None = None
        self.ocr_item_var = StringVar()
        self.ocr_amount_var = StringVar()
        self.ocr_currency_var = StringVar(value="崇高石")
        self.ocr_raw_var = StringVar()
        self.ocr_favorite_var = StringVar(value="1")
        self.ocr_running = False
        self.ocr_animation_job = None
        self.ocr_animation_step = 0
        self.ocr_capture_photo = None
        self.preload_ocr_var = StringVar(value="1" if self.config.preload_ocr_on_start else "0")
        self.ocr_cpu_threads_var = StringVar(value=self._ocr_threads_display_value(self.config.ocr_cpu_threads))
        self.ocr_provider_var = StringVar(value=self._ocr_provider_label(self.config.ocr_execution_provider))
        self.ocr_low_priority_var = StringVar(value="1" if self.config.ocr_low_priority else "0")
        self.app_icon_image = None

        self.root.title(f"流放之路2 物价追踪 v{__version__}")
        self._apply_window_icon()
        self.root.geometry("1120x760")
        self.root.minsize(980, 640)
        self._configure_style()
        self._build_menu()
        self._build_ui()
        self._register_hotkeys()
        self._refresh_recent()
        self._poll_events()
        self.root.bind_all("<Escape>", self._handle_overlay_escape, add="+")
        if self.config.preload_ocr_on_start:
            self.root.after(600, self.prepare_ocr_runtime)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_request)
        self.root.bind("<Unmap>", self.on_window_unmap, add="+")
        self.root.after(300, self._ensure_tray_icon)

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        size = int(getattr(self.config, "font_size", 13))
        rowheight = max(72, size * 3 + 26)
        style.configure("Treeview", rowheight=rowheight, font=("Microsoft YaHei UI", size))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", size, "bold"))
        style.configure("Market.Treeview", rowheight=rowheight, font=("Microsoft YaHei UI", size))
        style.configure("Market.Treeview.Heading", font=("Microsoft YaHei UI", size, "bold"))
        style.configure("TNotebook.Tab", padding=(16, 8))

    def _build_menu(self) -> None:
        self.root.config(menu=Menu(self.root))

    def _build_ui(self) -> None:
        self.sort_var = StringVar(value="最近更新")
        self.settings_font_var = StringVar(value=str(self.config.font_size))
        self.settings_width_var = StringVar(value=str(self.config.screenshot_width))
        self.settings_height_var = StringVar(value=str(self.config.screenshot_height))
        self.screenshot_retention_var = StringVar(value=str(self.config.screenshot_retention_count))
        self.show_ocr_details_var = StringVar(value="1" if self.config.show_ocr_review_details else "0")
        self.settings_manifest_var = StringVar(value=self.config.update_manifest)
        self.focus_search_shape_var = StringVar(value="圆角" if self.config.focus_search_rounded else "直角")
        self.focus_search_limit_var = StringVar(value=str(self.config.focus_search_limit))
        self.ocr_status_var = StringVar(value="截图识别已内置")
        self.manual_item_var = StringVar()
        self.manual_amount_var = StringVar()
        self.manual_currency_var = StringVar(value="崇高石")
        self.manual_favorite_var = StringVar(value="1" if self.config.manual_add_favorite else "0")
        self.minimize_action_var = StringVar(value=self._window_action_label(self.config.minimize_action, "minimize"))
        self.close_action_var = StringVar(value=self._window_action_label(self.config.close_action, "close"))

        self.bottom_bar = Frame(self.root, padx=14, pady=8)
        self.bottom_bar.pack(side="bottom", fill=X)
        Label(self.bottom_bar, textvariable=self.progress_var, anchor="w").pack(side=LEFT, fill=X, expand=True)
        self.progress = ttk.Progressbar(self.bottom_bar, mode="determinate", maximum=100, value=0, length=180)
        self.progress.pack(side=RIGHT)

        shell = Frame(self.root, padx=0, pady=0)
        shell.pack(fill=BOTH, expand=True)

        self.sidebar = Frame(shell, padx=16, pady=18, width=210)
        self.sidebar.pack(side=LEFT, fill="y")
        self.sidebar.pack_propagate(False)
        Label(self.sidebar, text="流放之路2 物价", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w", pady=(0, 18))
        self._nav_button("物价列表", self.show_market_page).pack(fill=X, pady=4)
        self._nav_button("收藏列表", self.show_favorites_page).pack(fill=X, pady=4)
        Frame(self.sidebar).pack(fill=BOTH, expand=True)
        self._nav_button("配置", self.show_settings_page).pack(side="bottom", fill=X, pady=4)
        self._nav_button("同步经济数据", self.sync_poe2db_currency).pack(side="bottom", fill=X, pady=4)
        self._nav_button("手动记录", self.show_manual_record_page).pack(side="bottom", fill=X, pady=4)
        self._nav_button("截图识别", self.show_ocr_review_page).pack(side="bottom", fill=X, pady=4)

        self.content = Frame(shell, padx=22, pady=18)
        self.content.pack(side=LEFT, fill=BOTH, expand=True)
        self.show_market_page()

    def _nav_button(self, text: str, command):
        return Button(self.sidebar, text=text, command=command)

    def _enable_combo_full_click(self, combo: ttk.Combobox) -> ttk.Combobox:
        combo.configure(state="readonly")

        def post_dropdown(_event=None):
            combo.focus_set()
            combo.after(1, lambda: self._post_combo_dropdown(combo))

        combo.bind("<Button-1>", post_dropdown, add="+")
        return combo

    @staticmethod
    def _post_combo_dropdown(combo: ttk.Combobox) -> None:
        try:
            combo.tk.call("ttk::combobox::Post", str(combo))
        except Exception:
            combo.event_generate("<Down>")

    def _set_progress_idle(self, text: str = "就绪") -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=100, value=0)
        self.progress_var.set(text)

    def _set_progress_busy(self, text: str) -> None:
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(80)
        self.progress_var.set(text)

    def _apply_window_icon(self) -> None:
        try:
            self.root.iconbitmap(str(app_icon_path()))
        except Exception:
            pass

    def _load_app_icon_image(self, size: int = 64) -> Image.Image:
        try:
            image = Image.open(app_icon_path()).convert("RGBA")
            return image.resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            image = Image.new("RGB", (size, size), "#2f80ed")
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((8, 8, size - 8, size - 8), radius=12, fill="#ffffff")
            draw.text((max(4, size // 3), max(4, size // 3)), "P2", fill="#2f80ed")
            return image

    def _set_progress_percent(self, percent: int, text: str) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=100, value=max(0, min(100, percent)))
        self.progress_var.set(text)

    def _screenshot_retention_count(self) -> int:
        try:
            return max(1, min(500, int(self.config.screenshot_retention_count)))
        except (TypeError, ValueError):
            return 20

    def _make_ocr_engine(self) -> RapidOcr:
        return RapidOcr(
            cpu_threads=getattr(self.config, "ocr_cpu_threads", 0),
            execution_provider=getattr(self.config, "ocr_execution_provider", "auto"),
        )

    @staticmethod
    def _ocr_provider_label(value: str) -> str:
        labels = {
            "cpu": "CPU",
            "auto": "自动",
            "directml": "GPU DirectML",
            "cuda": "GPU CUDA",
        }
        return labels.get((value or "auto").lower(), "自动")

    @staticmethod
    def _ocr_provider_value(label: str) -> str:
        values = {
            "CPU": "cpu",
            "自动": "auto",
            "GPU DirectML": "directml",
            "GPU CUDA": "cuda",
        }
        return values.get(label, "auto")

    @staticmethod
    def _auto_ocr_cpu_threads() -> int:
        return RapidOcr(cpu_threads=0).cpu_threads

    @staticmethod
    def _ocr_threads_display_value(value: int) -> str:
        try:
            threads = int(value)
        except (TypeError, ValueError):
            threads = 0
        if threads <= 0:
            return "自动"
        return str(threads)

    @staticmethod
    def _ocr_threads_config_value(value: str) -> int:
        text = (value or "").strip()
        if not text or text == "自动":
            return 0
        try:
            return max(0, int(text))
        except ValueError:
            return 0

    @staticmethod
    def _available_ocr_provider_text() -> str:
        providers = RapidOcr.available_providers()
        return "，".join(providers) if providers else "未检测到 onnxruntime"

    def _set_ocr_process_priority(self, low: bool) -> int | None:
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetCurrentProcess()
            previous = int(kernel32.GetPriorityClass(handle))
            target = 0x00004000 if low else 0x00000020
            kernel32.SetPriorityClass(handle, target)
            return previous
        except Exception:
            return None

    def _restore_process_priority(self, priority: int | None) -> None:
        if not priority:
            return
        try:
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), int(priority))
        except Exception:
            pass

    def _should_update_ocr_review_page(self) -> bool:
        return bool(getattr(self.config, "show_ocr_review_details", True))

    def _clear_ocr_review_data(self) -> None:
        self.ocr_review_rows = []
        self.ocr_review_raw_text = ""
        self.ocr_review_image_path = Path()
        self.ocr_selected_index = None

    def _clear_content(self) -> None:
        if hasattr(self, "trend_widgets"):
            self._clear_trend_canvases()
        for child in self.content.winfo_children():
            child.destroy()
        self.market_tree = None
        self.source_filter_combo = None

    def _has_market_tree(self) -> bool:
        tree = getattr(self, "market_tree", None)
        if tree is None:
            return False
        try:
            return bool(tree.winfo_exists())
        except Exception:
            return False

    def show_market_page(self) -> None:
        self.current_page_name = "market"
        self.current_favorites_only = False
        self._build_market_page("物价列表", favorites_only=False)

    def show_favorites_page(self) -> None:
        self.current_page_name = "favorites"
        self.current_favorites_only = True
        self._build_market_page("收藏列表", favorites_only=True)

    def show_manual_record_page(self) -> None:
        self.current_page_name = "manual"
        self._clear_content()
        Label(
            self.content,
            text="手动记录",
            font=("Microsoft YaHei UI", self.config.font_size + 8, "bold"),
        ).pack(anchor="w")
        Label(
            self.content,
            text="用于补充截图和同步之外的价格。只需要填物品名、价格和单位，其余字段会自动按手动来源记录。",
            foreground="#607080",
            wraplength=820,
        ).pack(anchor="w", pady=(8, 0))

        form = LabelFrame(self.content, text="新增价格记录", padx=18, pady=16)
        form.pack(fill=X, pady=(22, 0))

        row = Frame(form)
        row.pack(fill=X, pady=(0, 12))
        Label(row, text="物品名", width=10, anchor="w").pack(side=LEFT)
        Entry(row, textvariable=self.manual_item_var).pack(side=LEFT, fill=X, expand=True)

        row = Frame(form)
        row.pack(fill=X, pady=(0, 12))
        Label(row, text="价格", width=10, anchor="w").pack(side=LEFT)
        Entry(row, textvariable=self.manual_amount_var, width=18).pack(side=LEFT)
        Label(row, text="单位").pack(side=LEFT, padx=(18, 8))
        manual_unit = Combobox(row, textvariable=self.manual_currency_var, values=["崇高石", "神圣石"], width=24)
        self._enable_combo_full_click(manual_unit).pack(side=LEFT)

        ttk.Checkbutton(
            form,
            text="手动添加的物品默认加入收藏",
            variable=self.manual_favorite_var,
            onvalue="1",
            offvalue="0",
            command=self.save_manual_favorite_setting,
        ).pack(anchor="w", pady=(2, 14))

        actions = Frame(form)
        actions.pack(fill=X)
        Button(actions, text="保存记录", command=self.add_manual_record).pack(side=RIGHT)
        Button(actions, text="清空", command=self.clear_manual_record_form).pack(side=RIGHT, padx=(0, 8))

    def save_manual_favorite_setting(self) -> None:
        self.config.manual_add_favorite = self.manual_favorite_var.get() == "1"
        save_config(self.config)
        self.status_var.set("手动记录偏好已保存。")

    def clear_manual_record_form(self) -> None:
        self.manual_item_var.set("")
        self.manual_amount_var.set("")
        self.manual_currency_var.set("崇高石")

    def show_ocr_review_page(self) -> None:
        self.current_page_name = "ocr"
        self._clear_content()
        Label(
            self.content,
            text="截图识别",
            font=("Microsoft YaHei UI", self.config.font_size + 8, "bold"),
        ).pack(anchor="w")
        toolbar = Frame(self.content)
        toolbar.pack(fill=X, pady=(12, 10))
        Button(toolbar, text="截图识别", command=lambda: self.start_area_capture(restore_after=True)).pack(side=LEFT)
        Label(toolbar, text="框选后会先显示截图，再自动识别内容。").pack(side=LEFT, padx=(12, 0))
        if not self._should_update_ocr_review_page():
            Label(
                self.content,
                text="截图识别详情已隐藏。识别结果仍会在查价浮窗中显示。",
                foreground="#607080",
            ).pack(anchor="w", pady=(8, 0))
            return
        Button(toolbar, text="保存选中", command=self.save_selected_ocr_row).pack(side=RIGHT)
        Button(toolbar, text="保存全部", command=self.save_all_ocr_rows).pack(side=RIGHT, padx=(0, 8))
        ttk.Checkbutton(
            toolbar,
            text="保存后加入收藏",
            variable=self.ocr_favorite_var,
            onvalue="1",
            offvalue="0",
        ).pack(side=RIGHT, padx=(0, 16))

        result_box = LabelFrame(self.content, text="识别结果", padx=12, pady=10)
        result_box.pack(fill=X)

        result_top = Frame(result_box)
        result_top.pack(fill=X)
        columns = ("item", "amount", "currency", "source", "confidence", "raw")
        self.ocr_tree = ttk.Treeview(result_top, columns=columns, show="headings", selectmode="browse", height=5)
        self.ocr_tree.heading("item", text="物品")
        self.ocr_tree.heading("amount", text="价格")
        self.ocr_tree.heading("currency", text="单位")
        self.ocr_tree.heading("source", text="来源")
        self.ocr_tree.heading("confidence", text="可信度")
        self.ocr_tree.heading("raw", text="原始识别内容")
        self.ocr_tree.column("item", width=260, stretch=True)
        self.ocr_tree.column("amount", width=100, anchor="center")
        self.ocr_tree.column("currency", width=120, anchor="center")
        self.ocr_tree.column("source", width=100, anchor="center")
        self.ocr_tree.column("confidence", width=90, anchor="center")
        self.ocr_tree.column("raw", width=320, stretch=True)
        y_scroll = ttk.Scrollbar(result_top, orient="vertical", command=self.ocr_tree.yview)
        self.ocr_tree.configure(yscrollcommand=y_scroll.set)
        self.ocr_tree.pack(side=LEFT, fill=BOTH, expand=True)
        y_scroll.pack(side=RIGHT, fill=Y)
        self.ocr_tree.bind("<<TreeviewSelect>>", self.on_ocr_row_select)

        edit_row = Frame(result_box)
        edit_row.pack(fill=X, pady=(10, 0))
        Label(edit_row, text="物品").pack(side=LEFT)
        Entry(edit_row, textvariable=self.ocr_item_var, width=30).pack(side=LEFT, fill=X, expand=True, padx=(8, 14))
        Label(edit_row, text="价格").pack(side=LEFT)
        Entry(edit_row, textvariable=self.ocr_amount_var, width=12).pack(side=LEFT, padx=(8, 14))
        Label(edit_row, text="单位").pack(side=LEFT)
        ocr_unit = Combobox(
            edit_row,
            textvariable=self.ocr_currency_var,
            values=["崇高石", "神圣石"],
            width=18,
        )
        self._enable_combo_full_click(ocr_unit).pack(side=LEFT, padx=(8, 14))
        Button(edit_row, text="应用修改", command=self.apply_ocr_edit).pack(side=RIGHT)
        Button(edit_row, text="删除此行", command=self.delete_selected_ocr_row).pack(side=RIGHT, padx=(0, 8))

        process_box = LabelFrame(self.content, text="识别过程", padx=12, pady=10)
        process_box.pack(fill=BOTH, expand=True, pady=(14, 0))
        process_box.columnconfigure(0, weight=3)
        process_box.columnconfigure(1, weight=2)
        process_box.rowconfigure(0, weight=1)

        preview = Frame(process_box)
        preview.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.ocr_image_canvas = Canvas(preview, highlightthickness=1, highlightbackground="#d9e2ec", bg="#f8fafc")
        x_scroll = ttk.Scrollbar(preview, orient="horizontal", command=self.ocr_image_canvas.xview)
        y_scroll_image = ttk.Scrollbar(preview, orient="vertical", command=self.ocr_image_canvas.yview)
        self.ocr_image_canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll_image.set)
        self.ocr_image_canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll_image.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)

        text_panel = Frame(process_box)
        text_panel.grid(row=0, column=1, sticky="nsew")
        Label(text_panel, text="识别到的文字").pack(anchor="w")
        self.ocr_raw_text = Text(text_panel, height=12, wrap="word")
        self.ocr_raw_text.pack(fill=BOTH, expand=True, pady=(6, 0))

        self.refresh_ocr_review_table()
        self._render_ocr_capture_image()
        self._update_ocr_process_text()
        self._set_ocr_running_ui(self.ocr_running)

    def _render_ocr_capture_image(self) -> None:
        canvas = getattr(self, "ocr_image_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        if not self.ocr_review_image_path or not self.ocr_review_image_path.is_file():
            canvas.create_text(24, 24, text="还没有截图。点击“开始框选截图”或按截图快捷键。", anchor="nw", fill="#607080")
            canvas.configure(scrollregion=(0, 0, 680, 220))
            return
        try:
            image = Image.open(self.ocr_review_image_path)
            self.ocr_capture_photo = ImageTk.PhotoImage(image)
            canvas.create_image(0, 0, image=self.ocr_capture_photo, anchor="nw")
            canvas.configure(scrollregion=(0, 0, image.width, image.height))
        except Exception as exc:
            canvas.create_text(24, 24, text=f"截图预览失败：{exc}", anchor="nw", fill="#b42318")
            canvas.configure(scrollregion=(0, 0, 680, 220))

    def _update_ocr_process_text(self, placeholder: str = "") -> None:
        text = getattr(self, "ocr_raw_text", None)
        if text is None:
            return
        try:
            text.delete("1.0", END)
            if self.ocr_review_raw_text:
                text.insert("1.0", self.ocr_review_raw_text)
            elif placeholder:
                text.insert("1.0", placeholder)
            elif self.ocr_running:
                text.insert("1.0", "正在识别截图内容")
            else:
                text.insert("1.0", "等待截图。")
        except Exception:
            return

    def _set_ocr_running_ui(self, running: bool) -> None:
        self.ocr_running = running
        if running:
            self._animate_ocr_text()
        elif self.ocr_animation_job is not None:
            try:
                self.root.after_cancel(self.ocr_animation_job)
            except Exception:
                pass
            self.ocr_animation_job = None

    def _animate_ocr_text(self) -> None:
        if not self.ocr_running:
            self.ocr_animation_job = None
            return
        dots = "." * (self.ocr_animation_step % 4)
        self.ocr_animation_step += 1
        self._update_ocr_process_text(f"正在识别截图内容{dots}\n\n识别完成后，结果会自动出现在上方列表。")
        self.ocr_animation_job = self.root.after(360, self._animate_ocr_text)

    def _ocr_row_confidence(self, row: ParsedItemPrice) -> float:
        match = re.search(r"structure_confidence=([0-9.]+)", row.raw_text)
        if match:
            try:
                return max(0.0, min(1.0, float(match.group(1))))
            except ValueError:
                pass
        if row.item_match_score or row.currency_match_score:
            return max(
                0.0,
                min(1.0, 0.45 + row.item_match_score * 0.3 + row.currency_match_score * 0.25),
            )
        return 0.55

    def refresh_ocr_review_table(self) -> None:
        tree = getattr(self, "ocr_tree", None)
        if tree is None:
            return
        for item in tree.get_children():
            tree.delete(item)
        for index, row in enumerate(self.ocr_review_rows):
            confidence = self._ocr_row_confidence(row)
            tree.insert(
                "",
                END,
                iid=str(index),
                values=(
                    row.item_name,
                    f"{row.amount:g}",
                    row.currency,
                    "截图识别",
                    f"{confidence:.0%}",
                    row.raw_text,
                ),
            )
        if self.ocr_review_rows:
            tree.selection_set("0")
            self.load_ocr_row(0)

    def on_ocr_row_select(self, _event=None) -> None:
        selection = getattr(self, "ocr_tree", None).selection() if hasattr(self, "ocr_tree") else ()
        if not selection:
            return
        self.load_ocr_row(int(selection[0]))

    def load_ocr_row(self, index: int) -> None:
        if index < 0 or index >= len(self.ocr_review_rows):
            return
        row = self.ocr_review_rows[index]
        self.ocr_selected_index = index
        self.ocr_item_var.set(row.item_name)
        self.ocr_amount_var.set(f"{row.amount:g}")
        self.ocr_currency_var.set(row.currency or "崇高石")

    def apply_ocr_edit(self) -> bool:
        index = self.ocr_selected_index
        if index is None or index < 0 or index >= len(self.ocr_review_rows):
            return False
        item = self.ocr_item_var.get().strip()
        currency = self.ocr_currency_var.get().strip() or "崇高石"
        try:
            amount = float(self.ocr_amount_var.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showwarning("价格格式错误", "价格需要填写数字。")
            return False
        if not item:
            messagebox.showwarning("缺少物品", "物品名称不能为空。")
            return False
        raw = self.ocr_review_rows[index].raw_text
        old = self.ocr_review_rows[index]
        self.ocr_review_rows[index] = ParsedItemPrice(
            item_name=item,
            amount=amount,
            currency=currency,
            raw_text=raw,
            trend_percent=old.trend_percent,
            item_page_url=old.item_page_url,
            item_icon_url=old.item_icon_url,
            currency_page_url=old.currency_page_url,
            currency_icon_url=old.currency_icon_url,
            item_icon_path=old.item_icon_path,
            currency_icon_path=old.currency_icon_path,
            item_icon_phash=old.item_icon_phash,
            currency_icon_phash=old.currency_icon_phash,
            item_match_score=old.item_match_score,
            currency_match_score=old.currency_match_score,
        )
        self.refresh_ocr_review_table()
        try:
            self.ocr_tree.selection_set(str(index))
        except Exception:
            pass
        return True

    def delete_selected_ocr_row(self) -> None:
        index = self.ocr_selected_index
        if index is None or index < 0 or index >= len(self.ocr_review_rows):
            return
        del self.ocr_review_rows[index]
        self.ocr_selected_index = None
        self.refresh_ocr_review_table()

    def _save_ocr_indices(self, indices: list[int]) -> None:
        if self.ocr_selected_index in indices:
            self.apply_ocr_edit()
        saved = 0
        favorite = self.ocr_favorite_var.get() == "1"
        for index in indices:
            if index < 0 or index >= len(self.ocr_review_rows):
                continue
            row = self.ocr_review_rows[index]
            self.db.upsert_latest_price_record(
                row.item_name,
                row.amount,
                row.currency,
                "截图识别",
                confidence=self._ocr_row_confidence(row),
                raw_text=row.raw_text or self.ocr_review_raw_text,
                screenshot_path=str(self.ocr_review_image_path),
            )
            if favorite:
                self.db.set_favorite(row.item_name, True)
            saved += 1
        if saved:
            self.search_var.set(self.ocr_review_rows[indices[0]].item_name)
            self.refresh_market_table()
            self.status_var.set(f"已保存 {saved} 条截图识别结果。")
            messagebox.showinfo("保存完成", f"已保存 {saved} 条价格记录。")

    def save_selected_ocr_row(self) -> None:
        selection = getattr(self, "ocr_tree", None).selection() if hasattr(self, "ocr_tree") else ()
        if not selection:
            messagebox.showwarning("未选择", "请先选择要保存的识别结果。")
            return
        self._save_ocr_indices([int(selection[0])])

    def save_all_ocr_rows(self) -> None:
        if not self.ocr_review_rows:
            messagebox.showwarning("没有结果", "当前没有可保存的截图识别结果。")
            return
        self._save_ocr_indices(list(range(len(self.ocr_review_rows))))

    def _build_market_page(self, title: str, favorites_only: bool) -> None:
        self.current_page_name = "favorites" if favorites_only else "market"
        self._clear_content()
        self.current_favorites_only = favorites_only
        header = Frame(self.content)
        header.pack(fill=X)
        Label(header, text=title, font=("Microsoft YaHei UI", self.config.font_size + 8, "bold")).pack(side=LEFT)
        Label(header, textvariable=self.status_var).pack(side=RIGHT)

        filters = Frame(self.content)
        filters.pack(fill=X, pady=(18, 12))
        Label(filters, text="搜索").pack(side=LEFT)
        self.search_entry = Entry(filters, textvariable=self.search_var)
        self.search_entry.pack(side=LEFT, fill=X, expand=True, padx=(8, 14))
        self.search_entry.bind("<KeyRelease>", self.schedule_search_refresh)
        Label(filters, text="排序").pack(side=LEFT)
        sort = Combobox(
            filters,
            textvariable=self.sort_var,
            values=["最近更新", "价格从高到低", "价格从低到高", "名称", "记录数"],
            width=16,
            state="readonly",
        )
        sort.pack(side=LEFT, padx=(8, 0))
        sort.bind("<<ComboboxSelected>>", lambda _event: self.apply_sort_preset())
        Label(filters, text="单位").pack(side=LEFT, padx=(14, 0))
        currency = Combobox(
            filters,
            textvariable=self.display_currency_var,
            values=["神圣石", "崇高石"],
            width=8,
            state="readonly",
        )
        currency.pack(side=LEFT, padx=(8, 0))
        currency.bind("<<ComboboxSelected>>", lambda _event: self.save_display_currency())
        Label(filters, text="来源").pack(side=LEFT, padx=(14, 0))
        self.source_filter_combo = Combobox(
            filters,
            textvariable=self.source_filter_var,
            values=["全部来源"],
            width=18,
            state="readonly",
        )
        self.source_filter_combo.pack(side=LEFT, padx=(8, 0))
        self.source_filter_combo.bind("<<ComboboxSelected>>", lambda _event: self._reset_page_and_refresh())
        Label(filters, text="字体").pack(side=LEFT, padx=(14, 0))
        font_size = Combobox(
            filters,
            textvariable=self.settings_font_var,
            values=[str(value) for value in range(13, 23)],
            width=6,
            state="readonly",
        )
        font_size.pack(side=LEFT, padx=(8, 0))
        font_size.bind("<<ComboboxSelected>>", lambda _event: self.save_market_font_size())

        columns = ("index", "item", "price", "currency", "trend", "count", "source", "updated", "favorite")
        table_box = Frame(self.content)
        table_box.pack(fill=BOTH, expand=True)
        self.market_tree = ttk.Treeview(
            table_box,
            columns=columns,
            show="tree headings",
            selectmode="browse",
            style="Market.Treeview",
        )
        y_scroll = ttk.Scrollbar(table_box, orient="vertical", command=self._market_tree_yview)
        x_scroll = ttk.Scrollbar(table_box, orient="horizontal", command=self._market_tree_xview)
        self.market_tree.configure(
            yscrollcommand=lambda first, last: y_scroll.set(first, last),
            xscrollcommand=lambda first, last: x_scroll.set(first, last),
        )
        headings = {
            "index": "序号",
            "item": "物品",
            "price": "价格",
            "currency": "单位",
            "trend": "走势",
            "count": "记录",
            "source": "来源",
            "updated": "更新时间",
            "favorite": "收藏",
        }
        widths = {
            "index": 70,
            "item": 300,
            "price": 130,
            "currency": 90,
            "trend": 170,
            "count": 80,
            "source": 150,
            "updated": 180,
            "favorite": 80,
        }
        self.market_headings = headings
        self.market_tree.heading("#0", text=self._market_heading_text("图标", "icon"), command=lambda: self.sort_by_column("icon"))
        self.market_tree.column("#0", width=58, minwidth=42, anchor="center", stretch=False)
        for key in columns:
            self.market_tree.heading(key, text=self._market_heading_text(headings[key], key), command=lambda k=key: self.sort_by_column(k))
            anchor = "center" if key in {"index", "favorite", "count"} else "w"
            self.market_tree.column(key, width=widths[key], anchor=anchor)
        self.market_tree.tag_configure("pinned", background="#fff7d6")
        self.market_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_box.rowconfigure(0, weight=1)
        table_box.columnconfigure(0, weight=1)
        self.market_tree.bind("<ButtonRelease-1>", self.on_market_click)
        self.market_tree.bind("<Button-3>", self.show_market_context_menu)
        self.market_tree.bind("<MouseWheel>", self.on_market_tree_motion, add="+")
        self.market_tree.bind("<Shift-MouseWheel>", self.on_market_tree_motion, add="+")
        self.market_tree.bind("<Button-4>", self.on_market_tree_motion, add="+")
        self.market_tree.bind("<Button-5>", self.on_market_tree_motion, add="+")
        self.market_tree.bind("<Configure>", lambda _event: self._schedule_trend_render())

        footer = Frame(self.content)
        footer.pack(fill=X, pady=(12, 0))
        Button(footer, text="上一页", command=self.prev_page).pack(side=LEFT)
        Label(footer, textvariable=self.page_var, width=6, anchor="center").pack(side=LEFT, padx=8)
        Button(footer, text="下一页", command=self.next_page).pack(side=LEFT)
        Label(footer, text="每页").pack(side=LEFT, padx=(18, 6))
        page_size = Combobox(footer, textvariable=self.page_size_var, values=["25", "50", "100", "200"], width=8, state="readonly")
        page_size.pack(side=LEFT)
        page_size.bind("<<ComboboxSelected>>", lambda _event: self.save_page_size())
        Button(footer, text="显示列", command=self.open_column_settings).pack(side=LEFT, padx=(18, 0))
        Button(footer, text="刷新", command=self.refresh_market_table).pack(side=LEFT, padx=(8, 0))
        self.refresh_market_table()
        self.root.after(280, self._settle_market_layout)

    def show_settings_page(self) -> None:
        self.current_page_name = "settings"
        self._clear_content()
        holder = Frame(self.content)
        holder.pack(fill=BOTH, expand=True)
        canvas = Canvas(holder, highlightthickness=0)
        scrollbar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        body = Frame(canvas)
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")

        def update_scrollregion(_event=None) -> None:
            canvas.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, 0, 0))

        def resize_body(event) -> None:
            canvas.itemconfigure(window_id, width=event.width)
            canvas.after_idle(update_scrollregion)

        body.bind("<Configure>", update_scrollregion)
        canvas.bind("<Configure>", resize_body)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        Label(body, text="配置", font=("Microsoft YaHei UI", self.config.font_size + 8, "bold")).pack(anchor="w")
        grid = Frame(body)
        grid.pack(fill=X, pady=(18, 0))

        left = LabelFrame(grid, text="快捷键", padx=14, pady=12)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        for label, variable in [
            ("截图识别", StringVar(value=self.config.hotkeys.lookup_hovered)),
            ("聚焦搜索", StringVar(value=self.config.hotkeys.focus_search)),
            ("快速查价", StringVar(value=self.config.hotkeys.quick_price)),
        ]:
            row = Frame(left)
            row.pack(fill=X, pady=6)
            Label(row, text=label, width=12, anchor="w").pack(side=LEFT)
            button = HotkeyCaptureButton(row, variable)
            button.pack(side=LEFT, fill=X, expand=True)
            if variable.get() == self.config.hotkeys.focus_search:
                Button(row, text="重置", command=lambda v=variable: v.set("Ctrl+Space")).pack(side=LEFT, padx=(8, 0))
            variable.trace_add("write", lambda *_args, v=variable, n=label: self._save_hotkey_setting(n, v.get()))

        right = LabelFrame(grid, text="显示与截图", padx=14, pady=12)
        right.pack(side=LEFT, fill=BOTH, expand=True, padx=(10, 0))
        for label, variable in [
            ("默认每页数量", self.page_size_var),
            ("保留截图数量", self.screenshot_retention_var),
        ]:
            row = Frame(right)
            row.pack(fill=X, pady=6)
            Label(row, text=label, width=14, anchor="w").pack(side=LEFT)
            entry = Entry(row, textvariable=variable)
            entry.pack(side=LEFT, fill=X, expand=True)
            entry.bind("<FocusOut>", lambda _event: self.save_inline_settings())
            entry.bind("<Return>", lambda _event: self.save_inline_settings())
        row = Frame(right)
        row.pack(fill=X, pady=6)
        Label(row, text="默认显示单位", width=14, anchor="w").pack(side=LEFT)
        unit = Combobox(row, textvariable=self.display_currency_var, values=["神圣石", "崇高石"], state="readonly")
        unit.pack(side=LEFT, fill=X, expand=True)
        unit.bind("<<ComboboxSelected>>", lambda _event: self.save_display_currency())
        row = Frame(right)
        row.pack(fill=X, pady=6)
        Label(row, text="焦点搜索外观", width=14, anchor="w").pack(side=LEFT)
        shape = Combobox(row, textvariable=self.focus_search_shape_var, values=["圆角", "直角"], state="readonly")
        shape.pack(side=LEFT, fill=X, expand=True)
        shape.bind("<<ComboboxSelected>>", lambda _event: self.save_focus_search_settings())
        row = Frame(right)
        row.pack(fill=X, pady=6)
        Label(row, text="焦点搜索条数", width=14, anchor="w").pack(side=LEFT)
        limit = Combobox(row, textvariable=self.focus_search_limit_var, values=["3", "5", "8", "10"], state="readonly")
        limit.pack(side=LEFT, fill=X, expand=True)
        limit.bind("<<ComboboxSelected>>", lambda _event: self.save_focus_search_settings())

        window_box = LabelFrame(body, text="窗口行为", padx=14, pady=12)
        window_box.pack(fill=X, pady=(16, 0))
        row = Frame(window_box)
        row.pack(fill=X, pady=6)
        Label(row, text="最小化时", width=14, anchor="w").pack(side=LEFT)
        minimize = Combobox(
            row,
            textvariable=self.minimize_action_var,
            values=["首次询问", "保留在任务栏", "右下角小图标"],
            state="readonly",
        )
        minimize.pack(side=LEFT, fill=X, expand=True)
        minimize.bind("<<ComboboxSelected>>", lambda _event: self.save_window_behavior_settings())
        row = Frame(window_box)
        row.pack(fill=X, pady=6)
        Label(row, text="关闭窗口时", width=14, anchor="w").pack(side=LEFT)
        close = Combobox(
            row,
            textvariable=self.close_action_var,
            values=["首次询问", "退出软件", "右下角小图标"],
            state="readonly",
        )
        close.pack(side=LEFT, fill=X, expand=True)
        close.bind("<<ComboboxSelected>>", lambda _event: self.save_window_behavior_settings())
        Label(
            window_box,
            text="保留在任务栏：普通最小化。右下角小图标：隐藏窗口并继续后台运行。退出软件：关闭程序并停止快捷键。",
            foreground="#607080",
            wraplength=860,
            justify=LEFT,
        ).pack(anchor="w", pady=(8, 0))

        ocr_box = LabelFrame(body, text="截图识别功能", padx=14, pady=12)
        ocr_box.pack(fill=X, pady=(16, 0))
        Label(
            ocr_box,
            text="截图识别能力已随程序提供。首次使用时需要准备一下，之后会更快。",
            foreground="#607080",
            wraplength=760,
        ).pack(anchor="w")
        ocr_row = Frame(ocr_box)
        ocr_row.pack(fill=X, pady=(10, 0))
        Label(ocr_row, text="准备状态", width=10, anchor="w").pack(side=LEFT)
        Entry(ocr_row, textvariable=self.ocr_status_var, state="readonly").pack(side=LEFT, fill=X, expand=True)
        Button(ocr_row, text="提前准备", command=self.prepare_ocr_runtime).pack(side=LEFT, padx=(8, 0))
        row = Frame(ocr_box)
        row.pack(fill=X, pady=(10, 0))
        Label(row, text="OCR推理后端", width=14, anchor="w").pack(side=LEFT)
        provider = Combobox(
            row,
            textvariable=self.ocr_provider_var,
            values=["CPU", "自动", "GPU DirectML", "GPU CUDA"],
            state="readonly",
        )
        provider.pack(side=LEFT, fill=X, expand=True)
        provider.bind("<<ComboboxSelected>>", lambda _event: self.save_ocr_performance_settings())
        row = Frame(ocr_box)
        row.pack(fill=X, pady=6)
        Label(row, text="OCR CPU线程", width=14, anchor="w").pack(side=LEFT)
        threads = Combobox(
            row,
            textvariable=self.ocr_cpu_threads_var,
            values=["自动", "1", "2", "3", "4", "6", "8"],
            state="readonly",
        )
        threads.pack(side=LEFT, fill=X, expand=True)
        threads.bind("<<ComboboxSelected>>", lambda _event: self.save_ocr_performance_settings())
        threads.bind("<FocusOut>", lambda _event: self.save_ocr_performance_settings())
        threads.bind("<Return>", lambda _event: self.save_ocr_performance_settings())
        Label(
            ocr_box,
            text=f"检测到 {os.cpu_count() or 1} 个逻辑核心",
            foreground="#607080",
            wraplength=760,
        ).pack(anchor="w", pady=(2, 0))
        ttk.Checkbutton(
            ocr_box,
            text="识别时降低本程序优先级，减少游戏卡顿",
            variable=self.ocr_low_priority_var,
            onvalue="1",
            offvalue="0",
            command=self.save_ocr_performance_settings,
        ).pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(
            ocr_box,
            text="启动后自动提前准备截图识别",
            variable=self.preload_ocr_var,
            onvalue="1",
            offvalue="0",
            command=self.save_preload_ocr_setting,
        ).pack(anchor="w", pady=(10, 0))
        ttk.Checkbutton(
            ocr_box,
            text="在截图识别页显示截图、识别文字和可保存列表",
            variable=self.show_ocr_details_var,
            onvalue="1",
            offvalue="0",
            command=self.save_ocr_details_setting,
        ).pack(anchor="w", pady=(8, 0))

        danger_box = LabelFrame(body, text="数据", padx=14, pady=12)
        danger_box.pack(fill=X, pady=(16, 0))
        Label(
            danger_box,
            text="清空已记录数据会删除本地所有价格记录、收藏和置顶，不影响配置。",
            foreground="#9a3412",
            wraplength=760,
        ).pack(side=LEFT, fill=X, expand=True)
        Button(danger_box, text="清空已记录数据", command=self.clear_recorded_data).pack(side=RIGHT, padx=(12, 0))

        Button(body, text="退出软件", command=self.exit_app).pack(anchor="w", pady=(16, 0))
        Label(
            body,
            text="© 2026 大狗狗丶丶。版权所有，保留所有权利。",
            foreground="#8a97a6",
            wraplength=760,
        ).pack(anchor="w", pady=(16, 18))

        def wheel_handler(event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self._bind_mousewheel_recursive(holder, wheel_handler)

    def _bind_mousewheel_recursive(self, widget, handler) -> None:
        try:
            widget.bind("<MouseWheel>", handler, add="+")
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_mousewheel_recursive(child, handler)

    def _save_hotkey_setting(self, label: str, value: str) -> None:
        try:
            parse_hotkey(value)
        except ValueError:
            return
        if label == "截图识别":
            self.config.hotkeys.lookup_hovered = value
        elif label == "聚焦搜索":
            self.config.hotkeys.focus_search = value
        elif label == "快速查价":
            self.config.hotkeys.quick_price = value
        save_config(self.config)
        self.reload_hotkeys()

    def save_inline_settings(self) -> None:
        try:
            self.config.screenshot_width = max(120, int(self.settings_width_var.get()))
            self.config.screenshot_height = max(120, int(self.settings_height_var.get()))
            self.config.page_size = max(10, min(500, int(self.page_size_var.get())))
            self.config.focus_search_limit = max(1, min(10, int(self.focus_search_limit_var.get())))
            self.config.screenshot_retention_count = max(1, min(500, int(self.screenshot_retention_var.get())))
        except ValueError:
            return
        self.config.update_manifest = self.settings_manifest_var.get().strip()
        save_config(self.config)
        self._configure_style()
        self.status_var.set("配置已自动保存。")

    def save_focus_search_settings(self) -> None:
        try:
            self.config.focus_search_limit = max(1, min(10, int(self.focus_search_limit_var.get())))
        except ValueError:
            self.config.focus_search_limit = 5
            self.focus_search_limit_var.set("5")
        self.config.focus_search_rounded = self.focus_search_shape_var.get() != "直角"
        save_config(self.config)
        self.status_var.set("焦点搜索偏好已保存。")

    def save_ocr_settings(self) -> None:
        self.config.ocr_engine = "rapidocr"
        save_config(self.config)

    def save_ocr_performance_settings(self) -> None:
        old_threads = getattr(self.config, "ocr_cpu_threads", 0)
        old_provider = getattr(self.config, "ocr_execution_provider", "auto")
        old_low_priority = getattr(self.config, "ocr_low_priority", True)
        self.config.ocr_cpu_threads = self._ocr_threads_config_value(self.ocr_cpu_threads_var.get())
        self.config.ocr_execution_provider = self._ocr_provider_value(self.ocr_provider_var.get())
        self.config.ocr_low_priority = self.ocr_low_priority_var.get() == "1"
        self.config.ocr_performance_configured = True
        save_config(self.config)
        if (
            old_threads != self.config.ocr_cpu_threads
            or old_provider != self.config.ocr_execution_provider
            or old_low_priority != self.config.ocr_low_priority
        ):
            with self.ocr_lock:
                self.ocr = self._make_ocr_engine()
        threads_text = self._auto_ocr_cpu_threads() if self.config.ocr_cpu_threads <= 0 else self.config.ocr_cpu_threads
        self.status_var.set(f"OCR性能设置已保存：{self._ocr_provider_label(self.config.ocr_execution_provider)}，{threads_text} 线程")

    def save_preload_ocr_setting(self) -> None:
        self.config.preload_ocr_on_start = self.preload_ocr_var.get() == "1"
        save_config(self.config)
        self.status_var.set("截图识别准备偏好已保存。")

    def save_ocr_details_setting(self) -> None:
        self.config.show_ocr_review_details = self.show_ocr_details_var.get() == "1"
        if not self.config.show_ocr_review_details:
            self._clear_ocr_review_data()
        save_config(self.config)
        if getattr(self, "current_page_name", "") == "ocr":
            self.show_ocr_review_page()
        self.status_var.set("截图识别详情偏好已保存。")

    def save_window_behavior_settings(self) -> None:
        self.config.minimize_action = self._window_action_value(self.minimize_action_var.get(), "minimize")
        self.config.close_action = self._window_action_value(self.close_action_var.get(), "close")
        save_config(self.config)
        self.status_var.set("窗口行为已保存。")

    def prepare_ocr_runtime(self) -> None:
        if getattr(self, "ocr_preparing", False):
            return
        self.ocr_preparing = True
        self._set_progress_percent(0, "正在准备截图识别功能...")
        thread = threading.Thread(target=self._prepare_ocr_runtime_worker, daemon=True)
        thread.start()

    def _prepare_ocr_runtime_worker(self) -> None:
        try:
            with self.ocr_lock:
                ok = self.ocr.available()
            message = "截图识别已准备好。" if ok else "截图识别功能暂时不可用，请重新安装新版程序。"
            self._post_event(("ocr_done", ok, "截图识别已准备好", message))
        except Exception as exc:
            self._post_event(("ocr_done", False, "", str(exc)))

    @staticmethod
    def _window_action_label(value: str, kind: str) -> str:
        if value == "tray":
            return "右下角小图标"
        if value == "taskbar":
            return "保留在任务栏"
        if value == "exit":
            return "退出软件"
        return "首次询问"

    @staticmethod
    def _window_action_value(label: str, kind: str) -> str:
        if label == "右下角小图标":
            return "tray"
        if label == "保留在任务栏":
            return "taskbar"
        if label == "退出软件":
            return "exit"
        return "ask"

    def clear_recorded_data(self) -> None:
        ok = messagebox.askyesno(
            "清空已记录数据",
            "确定要清空本地所有价格记录、收藏和置顶吗？\n\n这个操作不会删除配置，但无法撤销。",
        )
        if not ok:
            return
        self.db.clear_all_data()
        self.search_var.set("")
        self.page_var.set("1")
        if self._has_market_tree():
            self.refresh_market_table()
        self.status_var.set("已清空本地价格记录。")

    def save_market_font_size(self) -> None:
        try:
            self.config.font_size = max(13, min(22, int(self.settings_font_var.get())))
        except ValueError:
            return
        save_config(self.config)
        self._configure_style()
        self.status_var.set(f"列表字体已调整为 {self.config.font_size}。")
        self.show_favorites_page() if getattr(self, "current_favorites_only", False) else self.show_market_page()

    def _market_heading_text(self, label: str, key: str) -> str:
        db_column = {
            "icon": "icon",
            "index": "index",
            "item": "name",
            "price": "price",
            "currency": "currency",
            "trend": "trend",
            "updated": "latest_at",
            "count": "count",
            "source": "source",
            "favorite": "favorite",
        }.get(key, key)
        if self.sort_column != db_column:
            return label
        return f"{label} {'↓' if self.sort_descending else '↑'}"

    def _update_market_headings(self) -> None:
        if not self._has_market_tree():
            return
        headings = getattr(self, "market_headings", {})
        self.market_tree.heading("#0", text=self._market_heading_text("图标", "icon"), command=lambda: self.sort_by_column("icon"))
        for key, label in headings.items():
            self.market_tree.heading(key, text=self._market_heading_text(label, key), command=lambda k=key: self.sort_by_column(k))

    def sort_by_column(self, column: str) -> None:
        mapping = {
            "icon": "图标",
            "index": "序号",
            "item": "名称",
            "price": "价格从高到低",
            "currency": "单位",
            "trend": "走势",
            "updated": "最近更新",
            "count": "记录数",
            "source": "来源",
            "favorite": "收藏",
        }
        db_column = {
            "icon": "icon",
            "index": "index",
            "item": "name",
            "price": "price",
            "currency": "currency",
            "trend": "trend",
            "updated": "latest_at",
            "count": "count",
            "source": "source",
            "favorite": "favorite",
        }.get(column)
        if not db_column:
            return
        if self.sort_column == db_column:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = db_column
            self.sort_descending = db_column not in {"name"}
        if column in mapping:
            if column == "price":
                self.sort_var.set("价格从高到低" if self.sort_descending else "价格从低到高")
            elif column in {"item", "updated", "count"}:
                self.sort_var.set(mapping[column])
            else:
                self.sort_var.set(f"{mapping[column]}排序")
        self._reset_page_and_refresh()

    def apply_sort_preset(self) -> None:
        value = self.sort_var.get()
        if value == "价格从高到低":
            self.sort_column, self.sort_descending = "price", True
        elif value == "价格从低到高":
            self.sort_column, self.sort_descending = "price", False
        elif value == "名称":
            self.sort_column, self.sort_descending = "name", False
        elif value == "记录数":
            self.sort_column, self.sort_descending = "count", True
        else:
            self.sort_column, self.sort_descending = "latest_at", True
        self._reset_page_and_refresh()

    def _current_page(self) -> int:
        try:
            return max(1, int(self.page_var.get()))
        except ValueError:
            return 1

    def _current_page_size(self) -> int:
        try:
            return max(1, int(self.page_size_var.get()))
        except ValueError:
            return self.config.page_size

    def _reset_page_and_refresh(self) -> None:
        self.page_var.set("1")
        self.refresh_market_table()

    def schedule_search_refresh(self, _event=None) -> None:
        if self.search_debounce_job is not None:
            self.root.after_cancel(self.search_debounce_job)
        self.search_debounce_job = self.root.after(350, self._run_debounced_search)

    def _run_debounced_search(self) -> None:
        self.search_debounce_job = None
        self._reset_page_and_refresh()

    def refresh_market_table(self) -> None:
        if not self._has_market_tree():
            return
        for widget in self.trend_widgets:
            widget.destroy()
        self.trend_widgets.clear()
        self.trend_data.clear()
        self.market_icon_images.clear()
        for item in self.market_tree.get_children():
            self.market_tree.delete(item)
        self._refresh_source_filter_values()
        page = self._current_page()
        page_size = self._current_page_size()
        total = self.db.count_market_rows(
            query=self.search_var.get(),
            source_filter=self.source_filter_var.get(),
            favorites_only=getattr(self, "current_favorites_only", False),
        )
        max_page = max(1, (total + page_size - 1) // page_size)
        if page > max_page:
            page = max_page
            self.page_var.set(str(page))
        target_currency = self.display_currency_var.get() or self.config.display_currency
        rate = self.db.get_exalted_per_divine()
        all_rows = self.db.get_market_rows(
            query=self.search_var.get(),
            source_filter=self.source_filter_var.get(),
            favorites_only=getattr(self, "current_favorites_only", False),
            sort_by="latest_at",
            descending=True,
            offset=0,
            limit=10000,
        )
        all_rows.sort(
            key=lambda row: self._market_sort_key(row, target_currency, rate),
            reverse=self.sort_descending,
        )
        all_rows.sort(key=lambda row: not row.pinned)
        rows = all_rows[(page - 1) * page_size : page * page_size]
        for index, row in enumerate(rows, start=(page - 1) * page_size + 1):
            display_amount = convert_amount(row.latest_amount, row.latest_currency, target_currency, rate)
            icon_image = self._market_icon_image(row.item_icon_path, row.item_name)
            self.market_tree.insert(
                "",
                END,
                iid=row.item_name,
                text="",
                image=icon_image,
                values=(
                    index,
                    row.item_name,
                    f"{display_amount:g}",
                    target_currency,
                    row.trend_percent,
                    row.count,
                    row.source,
                    self._format_time(row.latest_at),
                    ("置 " if row.pinned else "") + ("★" if row.favorite else "☆"),
                ),
                tags=("pinned",) if row.pinned else (),
            )
            history = [
                convert_amount(record.amount, record.currency, row.latest_currency, rate)
                for record in self.db.get_price_history(row.item_name, limit=12)
            ]
            trend_values = history if len(history) >= 3 else []
            self.trend_data[row.item_name] = (trend_values, row.trend_percent)
        self._apply_visible_columns()
        self._update_market_headings()
        self.root.update_idletasks()
        self._auto_fit_market_columns()
        self._schedule_trend_render(260)
        self.status_var.set(f"共 {total} 条记录，第 {page}/{max_page} 页")

    def _market_icon_image(self, path: str, key: str):
        if not path:
            return ""
        try:
            source = Path(path)
            if not source.exists():
                return ""
            image = Image.open(source).convert("RGBA")
            image.thumbnail((34, 34), Image.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self.market_icon_images[key] = photo
            return photo
        except Exception:
            return ""

    def _settle_market_layout(self) -> None:
        if not self._has_market_tree():
            return
        self._configure_style()
        self.root.update_idletasks()
        self._auto_fit_market_columns()
        self._schedule_trend_render(180)

    def _market_sort_key(self, row, target_currency: str, rate: float):
        column = self.sort_column
        if column == "index":
            return row.item_id
        if column == "icon":
            return int(self._market_row_has_icon(row))
        if column == "name":
            return row.item_name.casefold()
        if column == "price":
            return convert_amount(row.latest_amount, row.latest_currency, target_currency, rate)
        if column == "currency":
            return str(target_currency).casefold()
        if column == "trend":
            return self._trend_number(row.trend_percent)
        if column == "count":
            return row.count
        if column == "source":
            return row.source.casefold()
        if column == "latest_at":
            return row.latest_at
        if column == "favorite":
            return int(bool(row.favorite))
        return str(getattr(row, column, "")).casefold()

    @staticmethod
    def _market_row_has_icon(row) -> bool:
        if not row.item_icon_path:
            return False
        try:
            return Path(row.item_icon_path).is_file()
        except OSError:
            return False

    @staticmethod
    def _trend_number(value: str) -> float:
        try:
            return float(value.strip().replace("%", "").replace("+", ""))
        except ValueError:
            return 0.0

    def _refresh_source_filter_values(self) -> None:
        if not getattr(self, "source_filter_combo", None):
            return
        try:
            if not self.source_filter_combo.winfo_exists():
                return
        except Exception:
            return
        current = self.source_filter_var.get()
        values = ["全部来源"] + self.db.get_sources()
        self.source_filter_combo.configure(values=values)
        if current not in values:
            self.source_filter_var.set("全部来源")

    def _clear_trend_canvases(self) -> None:
        for widget in self.trend_widgets:
            try:
                widget.destroy()
            except Exception:
                pass
        self.trend_widgets.clear()

    def _schedule_trend_render(self, delay: int = 80) -> None:
        if self.trend_render_job is not None:
            try:
                self.root.after_cancel(self.trend_render_job)
            except Exception:
                pass
        self._clear_trend_canvases()
        self.trend_render_job = self.root.after(delay, self._render_trend_canvases)

    def _market_tree_yview(self, *args) -> None:
        self._clear_trend_canvases()
        self.market_tree.yview(*args)
        self._schedule_trend_render()

    def _market_tree_xview(self, *args) -> None:
        self._clear_trend_canvases()
        self.market_tree.xview(*args)
        self._schedule_trend_render()

    def on_market_tree_motion(self, _event=None) -> None:
        self._schedule_trend_render(120)

    def _render_trend_canvases(self) -> None:
        if not self._has_market_tree():
            return
        self.trend_render_job = None
        self._clear_trend_canvases()
        tree_height = self.market_tree.winfo_height()
        display_columns = self.market_tree["displaycolumns"]
        visible = set() if display_columns == "#all" or display_columns == ("#all",) else set(display_columns)
        if visible and "trend" not in visible:
            return
        for iid in self.market_tree.get_children():
            bbox = self.market_tree.bbox(iid, "trend")
            if not bbox:
                continue
            x, y, width, height = bbox
            if width <= 8 or height <= 8 or y < 0 or y + height > tree_height - 3:
                continue
            values, percent = self.trend_data.get(iid, ([], ""))
            tags = self.market_tree.item(iid, "tags")
            bg = "#fff7d6" if "pinned" in tags else "#ffffff"
            canvas_w = max(1, width - 4)
            canvas_h = max(1, height - 4)
            canvas = Canvas(self.market_tree, width=canvas_w, height=canvas_h, highlightthickness=0, bg=bg)
            canvas.place(x=x + 2, y=y + 2)
            self._draw_trend(canvas, values, percent, canvas_w, canvas_h)
            self.trend_widgets.append(canvas)

    def _draw_trend(self, canvas: Canvas, values: list[float], percent: str, width: int, height: int) -> None:
        color = "#7b8794"
        if percent.startswith("+"):
            color = "#18a058"
        elif percent.startswith("-"):
            color = "#d03050"
        canvas.create_rectangle(0, 0, width, height, fill=str(canvas["bg"]), outline="")
        percent_width = 0
        if percent:
            percent_width = min(56, max(40, 9 * len(percent) + 8))
        chart_left = 6
        chart_right = width - percent_width - 8
        chart_width = chart_right - chart_left
        if len(values) >= 3 and chart_width >= 34 and height >= 16:
            low, high = min(values), max(values)
            span = high - low or 1
            points = []
            usable_h = max(8, height - 12)
            for index, value in enumerate(values):
                px = chart_left + index * chart_width / max(1, len(values) - 1)
                py = height - 6 - (value - low) / span * usable_h
                points.extend((round(px, 1), round(max(3, min(height - 3, py)), 1)))
            canvas.create_line(*points, fill=color, width=2, smooth=True, capstyle="round", joinstyle="round")
        if percent:
            canvas.create_text(width - 6, height / 2, text=percent, anchor="e", fill=color, font=("Microsoft YaHei UI", 9, "bold"))

    def _auto_fit_market_columns(self) -> None:
        if not self._has_market_tree():
            return
        display_columns = self.market_tree["displaycolumns"]
        visible = list(self.market_tree["columns"]) if display_columns == "#all" or display_columns == ("#all",) else list(display_columns)
        if not visible:
            return
        icon_width = 58 if "图标" in self.config.visible_columns else 0
        tree_width = max(760, self.market_tree.winfo_width() - 26 - icon_width)
        weights = {
            "index": 0.55,
            "item": 2.9,
            "price": 1.15,
            "currency": 0.95,
            "trend": 1.7,
            "count": 0.8,
            "source": 1.35,
            "updated": 1.8,
            "favorite": 0.9,
        }
        mins = {
            "index": 68,
            "item": 220,
            "price": 110,
            "currency": 90,
            "trend": 150,
            "count": 78,
            "source": 120,
            "updated": 165,
            "favorite": 90,
        }
        total_weight = sum(weights.get(column, 1.0) for column in visible)
        widths = {
            column: max(mins.get(column, 90), int(tree_width * weights.get(column, 1.0) / total_weight))
            for column in visible
        }
        overflow = sum(widths.values()) - tree_width
        if overflow > 0 and "item" in widths:
            widths["item"] = max(mins["item"], widths["item"] - overflow)
        for column in self.market_tree["columns"]:
            self.market_tree.column(column, width=widths.get(column, mins.get(column, 90)), minwidth=mins.get(column, 90))
        self._schedule_trend_render()

    def toggle_selected_favorite(self, item_name: str | None = None) -> None:
        if not self._has_market_tree():
            return
        if item_name is None:
            selection = self.market_tree.selection()
            if not selection:
                return
            item_name = str(selection[0])
        values = self.market_tree.item(item_name, "values")
        current = bool(values and "★" in str(values[-1]))
        self.db.set_favorite(item_name, not current)
        self.refresh_market_table()

    def toggle_context_pinned(self) -> None:
        item_name = self.context_item_name
        if not item_name:
            return
        self.db.set_pinned(item_name, not self.db.is_pinned(item_name))
        self.refresh_market_table()

    def delete_context_item(self) -> None:
        item_name = self.context_item_name
        if not item_name:
            return
        ok = messagebox.askyesno("删除记录", f"确定删除“{item_name}”的所有本地价格记录吗？")
        if not ok:
            return
        self.db.delete_item(item_name)
        self.refresh_market_table()
        self.status_var.set(f"已删除：{item_name}")

    def show_market_context_menu(self, event) -> str:
        row_id = self.market_tree.identify_row(event.y)
        if not row_id:
            return "break"
        self.context_item_name = str(row_id)
        self.market_tree.selection_set(row_id)
        menu = Menu(self.root, tearoff=0)
        pinned = self.db.is_pinned(self.context_item_name)
        menu.add_command(label="取消置顶" if pinned else "置顶", command=self.toggle_context_pinned)
        menu.add_command(label="删除", command=self.delete_context_item)
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def on_market_click(self, event) -> None:
        region = self.market_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        column = self.market_tree.identify_column(event.x)
        row_id = self.market_tree.identify_row(event.y)
        if not row_id:
            return
        if column == "#0":
            return
        display_columns = self.market_tree["displaycolumns"]
        if display_columns == "#all" or display_columns == ("#all",):
            columns = list(self.market_tree["columns"])
        else:
            columns = list(display_columns)
        try:
            column_index = int(column.replace("#", "")) - 1
            column_name = columns[column_index]
        except Exception:
            return
        if column_name == "favorite":
            self.toggle_selected_favorite(str(row_id))
            return
        if column_name in {"item", "price"}:
            value = self.market_tree.set(row_id, column_name)
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self.status_var.set(f"已复制：{value}")

    def prev_page(self) -> None:
        self.page_var.set(str(max(1, self._current_page() - 1)))
        self.refresh_market_table()

    def next_page(self) -> None:
        self.page_var.set(str(self._current_page() + 1))
        self.refresh_market_table()

    def save_page_size(self) -> None:
        self.config.page_size = self._current_page_size()
        save_config(self.config)
        self._reset_page_and_refresh()

    def save_display_currency(self) -> None:
        self.config.display_currency = self.display_currency_var.get() or "神圣石"
        save_config(self.config)
        self.refresh_market_table()

    def _format_time(self, value: str) -> str:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return value[:19].replace("T", " ")

    def _apply_visible_columns(self) -> None:
        if not self._has_market_tree():
            return
        key_to_label = {
            "icon": "图标",
            "index": "序号",
            "item": "物品",
            "price": "价格",
            "currency": "单位",
            "trend": "走势",
            "count": "记录",
            "source": "来源",
            "updated": "更新时间",
            "favorite": "收藏",
        }
        visible = []
        for key, label in key_to_label.items():
            if key == "icon":
                continue
            if label in self.config.visible_columns:
                visible.append(key)
        data_columns = [key for key in key_to_label if key != "icon"]
        self.market_tree.configure(displaycolumns=visible or data_columns)
        if "图标" in self.config.visible_columns:
            self.market_tree.column("#0", width=58, minwidth=42, stretch=False)
        else:
            self.market_tree.column("#0", width=0, minwidth=0, stretch=False)
        self.root.update_idletasks()
        self._auto_fit_market_columns()

    def open_column_settings(self) -> None:
        window = Toplevel(self.root)
        window.title("显示列")
        window.geometry("360x420")
        variables: dict[str, StringVar] = {}
        labels = ["序号", "图标", "物品", "价格", "单位", "走势", "记录", "来源", "更新时间", "收藏"]
        body = Frame(window, padx=16, pady=16)
        body.pack(fill=BOTH, expand=True)
        for label in labels:
            var = StringVar(value="1" if label in self.config.visible_columns else "0")
            variables[label] = var
            ttk.Checkbutton(body, text=label, variable=var, onvalue="1", offvalue="0").pack(anchor="w", pady=4)

        def save_columns():
            selected = [label for label, var in variables.items() if var.get() == "1"]
            if "物品" not in selected:
                selected.insert(0, "物品")
            self.config.visible_columns = selected
            save_config(self.config)
            self._apply_visible_columns()
            self._schedule_trend_render()
            window.destroy()

        Button(body, text="保存", command=save_columns).pack(anchor="e", pady=(12, 0))

    def _register_hotkeys(self) -> None:
        self.hotkeys.register(
            self.config.hotkeys.lookup_hovered,
            lambda: self._post_event("open_workbench"),
        )
        self.hotkeys.register(
            self.config.hotkeys.focus_search,
            lambda: self._post_event("focus_search"),
        )
        self.hotkeys.register(
            self.config.hotkeys.quick_price,
            lambda: self._post_event("quick_price"),
        )
        self.hotkeys.start()
        if self.hotkeys.errors:
            self.status_var.set("；".join(self.hotkeys.errors))

    def reload_hotkeys(self) -> None:
        self.hotkeys.stop()
        self.hotkeys = GlobalHotkeys()
        self._register_hotkeys()
        if self.hotkeys.errors:
            self.status_var.set("；".join(self.hotkeys.errors))
        else:
            self.status_var.set(
                "快捷键已加载："
                f"截图识别 {self.config.hotkeys.lookup_hovered}，"
                f"搜索 {self.config.hotkeys.focus_search}，"
                f"快速查价 {self.config.hotkeys.quick_price}"
            )

    def _post_event(self, event: object) -> None:
        self.events.put(event)
        try:
            self.root.after(0, self._drain_events)
        except Exception:
            pass

    def _drain_events(self) -> None:
        if self._draining_events:
            return
        self._draining_events = True
        try:
            while True:
                event = self.events.get_nowait()
                if isinstance(event, tuple) and event[0] == "sync_done":
                    self._finish_sync(event[1], event[2])
                elif isinstance(event, tuple) and event[0] == "sync_progress":
                    _kind, index, total, category, url = event
                    percent = int(index / total * 100)
                    self._set_progress_percent(percent, f"同步中 {percent}%：{category}  {url}")
                elif isinstance(event, tuple) and event[0] == "sync_error":
                    self.syncing = False
                    self._set_progress_idle("同步失败")
                    messagebox.showerror("同步失败", event[1])
                elif isinstance(event, tuple) and event[0] == "ocr_progress":
                    _kind, percent, url = event
                    self._set_progress_percent(percent, f"截图识别准备中 {percent}%：{url}")
                elif isinstance(event, tuple) and event[0] == "ocr_done":
                    _kind, ok, engine_name, message = event
                    self.ocr_preparing = False
                    if ok:
                        self.config.ocr_engine = "rapidocr"
                        self.ocr_status_var.set(engine_name or "截图识别已准备好")
                        save_config(self.config)
                        self._set_progress_idle("截图识别已准备好")
                        self.status_var.set("截图识别已准备好。")
                        messagebox.showinfo("截图识别", "截图识别已准备好。")
                    else:
                        self._set_progress_idle("截图识别准备失败")
                        messagebox.showerror("截图识别准备失败", message)
                elif isinstance(event, tuple) and event[0] == "ocr_recognized":
                    _kind, ok, rows, raw_text, crop_path, message = event
                    self._set_ocr_running_ui(False)
                    show_review_details = self._should_update_ocr_review_page()
                    if show_review_details:
                        self.ocr_review_raw_text = raw_text
                        self.ocr_review_image_path = Path(crop_path)
                    else:
                        self._clear_ocr_review_data()
                    if ok:
                        if show_review_details:
                            self.ocr_review_rows = rows
                            self.show_ocr_review_page()
                        self._set_progress_idle(f"截图识别完成：{len(rows)} 条。")
                        self.status_var.set(f"截图识别完成：{len(rows)} 条，请确认后保存。")
                    else:
                        self.ocr_review_rows = []
                        if show_review_details and getattr(self, "current_page_name", "") == "ocr":
                            self.show_ocr_review_page()
                        self._set_progress_idle("截图识别未得到结果")
                        self.status_var.set(message or "截图识别未得到结果。")
                elif isinstance(event, tuple) and event[0] == "screenshot_lookup_done":
                    _kind, ok, rows, lookup_rows, raw_text, crop_path, message = event
                    self._set_ocr_running_ui(False)
                    self._area_capture_active = False
                    show_review_details = self._should_update_ocr_review_page()
                    if show_review_details:
                        self.ocr_review_rows = rows
                        self.ocr_review_raw_text = raw_text
                        self.ocr_review_image_path = Path(crop_path)
                        self.ocr_selected_index = None
                    else:
                        self._clear_ocr_review_data()
                    if (
                        show_review_details
                        and getattr(self, "current_page_name", "") == "ocr"
                        and self._restore_after_area_capture
                    ):
                        self.show_ocr_review_page()
                    elif (
                        show_review_details
                        and getattr(self, "current_page_name", "") == "ocr"
                        and self.root.state() != "withdrawn"
                    ):
                        self.show_ocr_review_page()
                    self.show_screenshot_lookup_results(lookup_rows, message)
                    if lookup_rows:
                        self._set_progress_idle(f"截图查价完成：{len(lookup_rows)} 条。")
                        self.status_var.set(f"截图查价完成：{len(lookup_rows)} 条。")
                    elif ok:
                        self._set_progress_idle("截图识别完成，但本地没有匹配价格")
                        self.status_var.set("截图识别完成，但本地没有匹配价格。")
                    else:
                        self._set_progress_idle("截图识别未得到可靠结果")
                        self.status_var.set(message or "截图识别未得到可靠结果。")
                elif isinstance(event, tuple) and event[0] == "update_progress":
                    _kind, percent, url = event
                    self._set_progress_percent(percent, f"更新下载中 {percent}%：{url}")
                elif isinstance(event, tuple) and event[0] == "update_done":
                    _kind, ok, executable_path, message = event
                    self.updating = False
                    if ok and executable_path:
                        self._set_progress_idle("更新已下载")
                        if messagebox.askyesno("更新完成", f"{message}\n\n现在启动新版并退出当前版本？"):
                            subprocess.Popen([executable_path], close_fds=True)
                            self.exit_app()
                    elif ok:
                        self._set_progress_idle("更新已下载")
                        messagebox.showinfo("更新完成", message)
                    else:
                        self._set_progress_idle("更新失败")
                        messagebox.showerror("更新失败", message)
                elif event == "open_workbench":
                    self.start_area_capture()
                elif event == "quick_price":
                    self.quick_price_from_clipboard()
                elif event == "focus_search":
                    self.toggle_focus_search_overlay()
        except queue.Empty:
            pass
        finally:
            self._draining_events = False

    def _poll_events(self) -> None:
        self._drain_events()
        self.root.after(60, self._poll_events)

    def search(self) -> None:
        self.refresh_market_table()

    def toggle_focus_search_overlay(self) -> None:
        if self._focus_search_overlay_exists():
            self.destroy_focus_search_overlay()
        else:
            self.show_focus_search_overlay()

    def show_focus_search_overlay(self) -> None:
        if self._focus_search_overlay_exists():
            self.focus_search_overlay.lift()
            if self.focus_search_entry is not None:
                self.focus_search_entry.focus_force()
                self.focus_search_entry.selection_range(0, END)
            return

        overlay = Toplevel(self.root)
        self.focus_search_overlay = overlay
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        try:
            overlay.attributes("-alpha", 0.96)
        except Exception:
            pass
        transparent = "#ff00ff"
        if self.config.focus_search_rounded:
            overlay.configure(bg=transparent)
            try:
                overlay.attributes("-transparentcolor", transparent)
            except Exception:
                pass
        else:
            overlay.configure(bg="#ffffff")
        overlay.bind("<Escape>", lambda _event: self.destroy_focus_search_overlay())
        overlay.bind("<Control-space>", lambda _event: self.destroy_focus_search_overlay())
        overlay.bind("<Control-Key-space>", lambda _event: self.destroy_focus_search_overlay())

        outer = Canvas(overlay, bg=transparent if self.config.focus_search_rounded else "#ffffff", highlightthickness=0)
        outer.pack(fill=BOTH, expand=True)
        self.focus_search_outer_canvas = outer
        container = Frame(outer, bg="#ffffff", padx=16, pady=12, highlightthickness=0 if self.config.focus_search_rounded else 1, highlightbackground="#d8e1ea")
        self.focus_search_container = container
        self.focus_search_container_window = outer.create_window((0, 0), window=container, anchor="nw")

        search_row = Frame(container, bg="#ffffff")
        search_row.pack(fill=X)
        Label(search_row, text="搜索", fg="#8a97a6", bg="#ffffff", font=("Microsoft YaHei UI", 12, "bold")).pack(side=LEFT)
        entry = Entry(search_row, textvariable=self.focus_search_var, font=("Microsoft YaHei UI", 17))
        entry.pack(side=LEFT, fill=X, expand=True, padx=(12, 0), ipady=3)
        entry.bind("<KeyRelease>", self.schedule_focus_search_refresh)
        entry.bind("<Escape>", lambda _event: self.destroy_focus_search_overlay())
        entry.bind("<Control-space>", lambda _event: self.destroy_focus_search_overlay())
        entry.bind("<Control-Key-space>", lambda _event: self.destroy_focus_search_overlay())
        self.focus_search_entry = entry

        result_box = Frame(container, bg="#ffffff")
        result_box.pack(fill=BOTH, expand=True, pady=(7, 0))
        result_canvas = Canvas(result_box, bg="#ffffff", highlightthickness=0)
        result_scrollbar = ttk.Scrollbar(result_box, orient="vertical", command=result_canvas.yview)
        result_inner = Frame(result_canvas, bg="#ffffff")
        result_window = result_canvas.create_window((0, 0), window=result_inner, anchor="nw")
        result_inner.bind(
            "<Configure>",
            lambda _event: result_canvas.configure(scrollregion=result_canvas.bbox("all") or (0, 0, 0, 0)),
        )
        result_canvas.bind("<Configure>", lambda event: result_canvas.itemconfigure(result_window, width=event.width))
        result_canvas.configure(yscrollcommand=result_scrollbar.set)
        result_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.focus_search_results = result_inner
        self.focus_search_results_canvas = result_canvas
        self.focus_search_result_window = result_window
        self.focus_search_results_scrollbar = result_scrollbar
        self.focus_search_var.set(self.search_var.get().strip())
        self._position_focus_search_overlay(96)
        overlay.after(30, lambda: self._focus_search_entry_force_focus(entry))
        overlay.after(40, lambda: entry.selection_range(0, END))
        self.schedule_focus_search_refresh()

    def _focus_search_entry_force_focus(self, entry) -> None:
        try:
            if self.focus_search_overlay is not None:
                self.focus_search_overlay.lift()
                self.focus_search_overlay.focus_force()
            entry.focus_force()
        except Exception:
            pass

    def _position_focus_search_overlay(self, height: int) -> None:
        overlay = self.focus_search_overlay
        if overlay is None:
            return
        width = 640
        screen_width = overlay.winfo_screenwidth()
        screen_height = overlay.winfo_screenheight()
        x = max(24, int((screen_width - width) / 2))
        center_y = int(screen_height * (1 - 0.618))
        y = max(24, center_y - int(height / 2))
        overlay.geometry(f"{width}x{height}+{x}+{y}")
        self._draw_focus_search_shell(width, height)

    def _draw_focus_search_shell(self, width: int, height: int) -> None:
        canvas = self.focus_search_outer_canvas
        if canvas is None:
            return
        rounded = bool(self.config.focus_search_rounded)
        margin = 10 if rounded else 0
        canvas.configure(width=width, height=height)
        canvas.delete("shell")
        if rounded:
            points = self._rounded_rect_points(margin, margin, width - margin, height - margin, 18)
            shell = canvas.create_polygon(points, smooth=True, fill="#ffffff", outline="#d8e1ea", tags="shell")
        else:
            shell = canvas.create_rectangle(0, 0, width, height, fill="#ffffff", outline="#d8e1ea", tags="shell")
        canvas.tag_lower(shell)
        if self.focus_search_container_window is not None:
            canvas.coords(self.focus_search_container_window, margin, margin)
            canvas.itemconfigure(self.focus_search_container_window, width=width - margin * 2, height=height - margin * 2)
            canvas.tag_raise(self.focus_search_container_window)

    @staticmethod
    def _rounded_rect_points(x1: int, y1: int, x2: int, y2: int, radius: int) -> list[int]:
        return [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]

    def _focus_search_overlay_exists(self) -> bool:
        overlay = self.focus_search_overlay
        if overlay is None:
            return False
        try:
            return bool(overlay.winfo_exists())
        except Exception:
            return False

    def destroy_focus_search_overlay(self) -> None:
        if self.focus_search_job is not None:
            try:
                self.root.after_cancel(self.focus_search_job)
            except Exception:
                pass
            self.focus_search_job = None
        overlay = self.focus_search_overlay
        self.focus_search_overlay = None
        self.focus_search_entry = None
        self.focus_search_results = None
        self.focus_search_outer_canvas = None
        self.focus_search_container = None
        self.focus_search_container_window = None
        self.focus_search_results_canvas = None
        self.focus_search_result_window = None
        self.focus_search_results_scrollbar = None
        if overlay is not None:
            try:
                if overlay.winfo_exists():
                    overlay.destroy()
            except Exception:
                pass

    def show_screenshot_lookup_loading(self) -> None:
        overlay = self._ensure_screenshot_lookup_overlay()
        if overlay is None:
            return
        self._clear_screenshot_lookup_results()
        header = Frame(self.screenshot_lookup_results, bg="#ffffff", pady=4)
        header.pack(fill=X)
        Label(
            header,
            text="正在识别截图",
            fg="#172033",
            bg="#ffffff",
            font=("Microsoft YaHei UI", 15, "bold"),
        ).pack(anchor="w")
        loading = Label(
            header,
            text="正在分析物品区域和本地物价...",
            fg="#7b8794",
            bg="#ffffff",
            font=("Microsoft YaHei UI", 11),
        )
        loading.pack(anchor="w", pady=(6, 0))
        self._bind_screenshot_lookup_drag_recursive(header)
        self.screenshot_lookup_loading_label = loading
        self._configure_screenshot_lookup_scroll(46, False)
        self._position_screenshot_lookup_overlay(126)
        self._animate_screenshot_lookup_loading()
        self._show_screenshot_lookup_overlay(overlay)

    def _ensure_screenshot_lookup_overlay(self) -> Toplevel | None:
        if self.screenshot_lookup_overlay is not None and self._toplevel_exists(self.screenshot_lookup_overlay):
            return self.screenshot_lookup_overlay
        overlay = Toplevel(self.root)
        self.screenshot_lookup_overlay = overlay
        overlay.withdraw()
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        try:
            overlay.attributes("-alpha", 0.96)
        except Exception:
            pass
        transparent = "#ff00ff"
        if self.config.focus_search_rounded:
            overlay.configure(bg=transparent)
            try:
                overlay.attributes("-transparentcolor", transparent)
            except Exception:
                pass
        else:
            overlay.configure(bg="#ffffff")
        overlay.bind("<Escape>", lambda _event: self.destroy_screenshot_lookup_overlay())

        outer = Canvas(overlay, bg=transparent if self.config.focus_search_rounded else "#ffffff", highlightthickness=0)
        outer.pack(fill=BOTH, expand=True)
        self.screenshot_lookup_outer_canvas = outer
        container = Frame(
            outer,
            bg="#ffffff",
            padx=16,
            pady=12,
            highlightthickness=0 if self.config.focus_search_rounded else 1,
            highlightbackground="#d8e1ea",
        )
        self.screenshot_lookup_container = container
        self.screenshot_lookup_container_window = outer.create_window((0, 0), window=container, anchor="nw")
        self._bind_screenshot_lookup_drag_recursive(container)

        title_row = Frame(container, bg="#ffffff")
        title_row.pack(fill=X)
        Label(
            title_row,
            text="截图查价",
            fg="#8a97a6",
            bg="#ffffff",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(side=LEFT)
        Label(
            title_row,
            text="Esc 关闭",
            fg="#b0bac5",
            bg="#ffffff",
            font=("Microsoft YaHei UI", 10),
        ).pack(side=RIGHT)

        result_box = Frame(container, bg="#ffffff")
        result_box.pack(fill=BOTH, expand=True, pady=(8, 0))
        result_canvas = Canvas(result_box, bg="#ffffff", highlightthickness=0, takefocus=1)
        result_canvas.bind("<Escape>", lambda _event: self.destroy_screenshot_lookup_overlay())
        result_scrollbar = ttk.Scrollbar(result_box, orient="vertical", command=result_canvas.yview)
        result_inner = Frame(result_canvas, bg="#ffffff")
        result_window = result_canvas.create_window((0, 0), window=result_inner, anchor="nw")
        result_inner.bind(
            "<Configure>",
            lambda _event: result_canvas.configure(scrollregion=result_canvas.bbox("all") or (0, 0, 0, 0)),
        )
        result_canvas.bind("<Configure>", lambda event: result_canvas.itemconfigure(result_window, width=event.width))
        result_canvas.configure(yscrollcommand=result_scrollbar.set)
        result_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.screenshot_lookup_results = result_inner
        self.screenshot_lookup_results_canvas = result_canvas
        self.screenshot_lookup_result_window = result_window
        self.screenshot_lookup_results_scrollbar = result_scrollbar
        self._position_screenshot_lookup_overlay(126)
        return overlay

    def _show_screenshot_lookup_overlay(self, overlay: Toplevel) -> None:
        try:
            if not overlay.winfo_exists():
                return
            overlay.update_idletasks()
            overlay.deiconify()
            overlay.lift()
            self._focus_screenshot_lookup_overlay(overlay)
            self.root.after(40, lambda: self._focus_screenshot_lookup_overlay(overlay))
        except Exception:
            pass

    def _handle_overlay_escape(self, _event=None) -> str | None:
        if self.screenshot_lookup_overlay is not None and self._toplevel_exists(self.screenshot_lookup_overlay):
            self.destroy_screenshot_lookup_overlay()
            return "break"
        if self.quick_price_overlay is not None and self._toplevel_exists(self.quick_price_overlay):
            self._destroy_quick_price_overlay()
            return "break"
        if self._focus_search_overlay_exists():
            self.destroy_focus_search_overlay()
            return "break"
        return None

    def _focus_screenshot_lookup_overlay(self, overlay: Toplevel) -> None:
        try:
            if overlay.winfo_exists():
                overlay.lift()
                overlay.focus_force()
                target = self.screenshot_lookup_results_canvas or overlay
                target.focus_set()
        except Exception:
            pass

    def _bind_screenshot_lookup_drag_recursive(self, widget) -> None:
        try:
            widget.bind("<ButtonPress-1>", self._start_screenshot_lookup_drag, add="+")
            widget.bind("<B1-Motion>", self._drag_screenshot_lookup_overlay, add="+")
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_screenshot_lookup_drag_recursive(child)

    def _start_screenshot_lookup_drag(self, event) -> None:
        overlay = self.screenshot_lookup_overlay
        if overlay is None:
            return
        self.screenshot_lookup_drag_moved = False
        self.screenshot_lookup_drag_start = (event.x_root, event.y_root, overlay.winfo_x(), overlay.winfo_y())

    def _drag_screenshot_lookup_overlay(self, event) -> None:
        overlay = self.screenshot_lookup_overlay
        start = self.screenshot_lookup_drag_start
        if overlay is None or start is None:
            return
        start_x, start_y, window_x, window_y = start
        dx = event.x_root - start_x
        dy = event.y_root - start_y
        if abs(dx) + abs(dy) >= 4:
            self.screenshot_lookup_drag_moved = True
        overlay.geometry(f"+{window_x + dx}+{window_y + dy}")

    def _clear_screenshot_lookup_results(self) -> None:
        if self.screenshot_lookup_animation_job is not None:
            try:
                self.root.after_cancel(self.screenshot_lookup_animation_job)
            except Exception:
                pass
            self.screenshot_lookup_animation_job = None
        self.screenshot_lookup_loading_label = None
        if self.screenshot_lookup_results is None:
            return
        for child in self.screenshot_lookup_results.winfo_children():
            child.destroy()

    def _animate_screenshot_lookup_loading(self) -> None:
        label = self.screenshot_lookup_loading_label
        if label is None:
            self.screenshot_lookup_animation_job = None
            return
        try:
            if not label.winfo_exists():
                self.screenshot_lookup_animation_job = None
                return
            dots = "." * (self.screenshot_lookup_animation_step % 4)
            self.screenshot_lookup_animation_step += 1
            label.configure(text=f"正在分析物品区域和本地物价{dots}")
        except Exception:
            self.screenshot_lookup_animation_job = None
            return
        self.screenshot_lookup_animation_job = self.root.after(360, self._animate_screenshot_lookup_loading)

    def show_screenshot_lookup_results(self, rows: list[tuple[MarketRow, float, str]], message: str = "") -> None:
        overlay = self._ensure_screenshot_lookup_overlay()
        if overlay is None:
            return
        self._clear_screenshot_lookup_results()
        if not rows:
            box = Frame(self.screenshot_lookup_results, bg="#ffffff", pady=8)
            box.pack(fill=X)
            Label(
                box,
                text="没有查到可靠物品",
                fg="#172033",
                bg="#ffffff",
                font=("Microsoft YaHei UI", 14, "bold"),
            ).pack(anchor="w")
            Label(
                box,
                text=message or "已把截图和识别文字放到截图识别页，可以稍后手动确认。",
                fg="#7b8794",
                bg="#ffffff",
                font=("Microsoft YaHei UI", 10),
                wraplength=600,
                justify=LEFT,
            ).pack(anchor="w", pady=(6, 0))
            self._bind_screenshot_lookup_drag_recursive(box)
            self._configure_screenshot_lookup_scroll(68, False)
            self._position_screenshot_lookup_overlay(150)
            self._show_screenshot_lookup_overlay(overlay)
            return

        for index, (row_data, confidence, raw_text) in enumerate(rows):
            self._render_screenshot_lookup_row(index, row_data, confidence, raw_text)
        visible_rows = min(len(rows), 5)
        result_height = self._measure_screenshot_lookup_result_height(visible_rows)
        self._configure_screenshot_lookup_scroll(result_height, len(rows) > 5)
        self._position_screenshot_lookup_overlay(104 + result_height)
        self._show_screenshot_lookup_overlay(overlay)
        self._focus_screenshot_lookup_overlay(overlay)

    def _render_screenshot_lookup_row(self, index: int, row_data: MarketRow, confidence: float, raw_text: str) -> None:
        if self.screenshot_lookup_results is None:
            return
        item = Frame(self.screenshot_lookup_results, bg="#ffffff", pady=5)
        item.pack(fill=X)
        if index:
            Canvas(item, height=1, bg="#e8eef5", highlightthickness=0).pack(fill=X, pady=(0, 7))
        body = Frame(item, bg="#ffffff")
        body.pack(fill=X)
        order = Label(
            body,
            text=str(index + 1),
            fg="#98a2b3",
            bg="#ffffff",
            font=("Microsoft YaHei UI", 12, "bold"),
            width=3,
            anchor="w",
        )
        order.pack(side=LEFT)
        name_box = Frame(body, bg="#ffffff")
        name_box.pack(side=LEFT, fill=X, expand=True)
        Label(
            name_box,
            text=row_data.item_name,
            fg="#172033",
            bg="#ffffff",
            font=("Microsoft YaHei UI", 13, "bold"),
            anchor="w",
        ).pack(anchor="w")
        subtitle = row_data.source
        Label(name_box, text=subtitle, fg="#8a97a6", bg="#ffffff", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(1, 0))

        target_currency = self.display_currency_var.get() or self.config.display_currency
        rate = self.db.get_exalted_per_divine()
        amount = convert_amount(row_data.latest_amount, row_data.latest_currency, target_currency, rate)
        price_box = Frame(body, bg="#ffffff")
        price_box.pack(side=RIGHT, padx=(16, 0))
        Label(
            price_box,
            text=f"{amount:g} {target_currency}",
            fg="#c77d00",
            bg="#ffffff",
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(anchor="e")
        trend_color = "#1f9d55" if row_data.trend_percent.startswith("+") else "#d64545" if row_data.trend_percent.startswith("-") else "#8a97a6"
        Label(price_box, text=f"趋势 {row_data.trend_percent or '暂无'}", fg=trend_color, bg="#ffffff", font=("Microsoft YaHei UI", 9)).pack(anchor="e")
        self._bind_screenshot_lookup_drag_recursive(item)
        self._bind_screenshot_lookup_click_recursive(item, row_data.item_name)

    def _bind_screenshot_lookup_click_recursive(self, widget, item_name: str) -> None:
        try:
            widget.bind("<ButtonRelease-1>", lambda _event, name=item_name: self._choose_screenshot_lookup_item(name), add="+")
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_screenshot_lookup_click_recursive(child, item_name)

    def _choose_screenshot_lookup_item(self, item_name: str) -> None:
        if self.screenshot_lookup_drag_moved:
            self.screenshot_lookup_drag_moved = False
            return
        self.search_var.set(item_name)
        if self.root.state() != "withdrawn":
            self._reset_page_and_refresh()
        self.destroy_screenshot_lookup_overlay()

    def _measure_screenshot_lookup_result_height(self, visible_rows: int) -> int:
        if self.screenshot_lookup_results is None:
            return max(1, visible_rows) * 68
        try:
            self.screenshot_lookup_results.update_idletasks()
            children = self.screenshot_lookup_results.winfo_children()[:visible_rows]
            measured = sum(max(child.winfo_reqheight(), child.winfo_height()) for child in children)
        except Exception:
            measured = 0
        return max(max(1, visible_rows) * 68, measured + 6)

    def _configure_screenshot_lookup_scroll(self, height: int, scrollable: bool) -> None:
        canvas = self.screenshot_lookup_results_canvas
        scrollbar = self.screenshot_lookup_results_scrollbar
        if canvas is None or scrollbar is None:
            return
        canvas.configure(height=height)
        if scrollable:
            scrollbar.pack(side=RIGHT, fill=Y)
            self._bind_focus_result_wheel_recursive(canvas, canvas)
            if self.screenshot_lookup_results is not None:
                self._bind_focus_result_wheel_recursive(self.screenshot_lookup_results, canvas)
        else:
            scrollbar.pack_forget()
            canvas.yview_moveto(0)
        canvas.after_idle(lambda: canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, 0, 0)))

    def _position_screenshot_lookup_overlay(self, height: int) -> None:
        overlay = self.screenshot_lookup_overlay
        if overlay is None:
            return
        width = 680
        screen_width = overlay.winfo_screenwidth()
        screen_height = overlay.winfo_screenheight()
        x = max(24, int((screen_width - width) / 2))
        center_y = int(screen_height * (1 - 0.618))
        y = max(24, center_y - int(height / 2))
        overlay.geometry(f"{width}x{height}+{x}+{y}")
        self._draw_screenshot_lookup_shell(width, height)

    def _draw_screenshot_lookup_shell(self, width: int, height: int) -> None:
        canvas = self.screenshot_lookup_outer_canvas
        if canvas is None:
            return
        rounded = bool(self.config.focus_search_rounded)
        margin = 10 if rounded else 0
        canvas.configure(width=width, height=height)
        canvas.delete("shell")
        if rounded:
            points = self._rounded_rect_points(margin, margin, width - margin, height - margin, 18)
            shell = canvas.create_polygon(points, smooth=True, fill="#ffffff", outline="#d8e1ea", tags="shell")
        else:
            shell = canvas.create_rectangle(0, 0, width, height, fill="#ffffff", outline="#d8e1ea", tags="shell")
        canvas.tag_lower(shell)
        if self.screenshot_lookup_container_window is not None:
            canvas.coords(self.screenshot_lookup_container_window, margin, margin)
            canvas.itemconfigure(self.screenshot_lookup_container_window, width=width - margin * 2, height=height - margin * 2)
            canvas.tag_raise(self.screenshot_lookup_container_window)

    def destroy_screenshot_lookup_overlay(self) -> None:
        self._clear_screenshot_lookup_results()
        overlay = self.screenshot_lookup_overlay
        self.screenshot_lookup_overlay = None
        self.screenshot_lookup_outer_canvas = None
        self.screenshot_lookup_container = None
        self.screenshot_lookup_container_window = None
        self.screenshot_lookup_results = None
        self.screenshot_lookup_results_canvas = None
        self.screenshot_lookup_result_window = None
        self.screenshot_lookup_results_scrollbar = None
        self.screenshot_lookup_watch_token += 1
        if overlay is not None and self._toplevel_exists(overlay):
            try:
                overlay.destroy()
            except Exception:
                pass

    def schedule_focus_search_refresh(self, _event=None) -> None:
        if self.focus_search_job is not None:
            try:
                self.root.after_cancel(self.focus_search_job)
            except Exception:
                pass
        self.focus_search_job = self.root.after(350, self.refresh_focus_search_results)

    def refresh_focus_search_results(self) -> None:
        self.focus_search_job = None
        if not self._focus_search_overlay_exists() or self.focus_search_results is None:
            return
        for child in self.focus_search_results.winfo_children():
            child.destroy()
        query = self.focus_search_var.get().strip()
        if not query:
            self._configure_focus_result_scroll(0, False)
            self._position_focus_search_overlay(96)
            return

        limit = max(1, min(10, int(getattr(self.config, "focus_search_limit", 5) or 5)))
        rows = self.db.get_market_rows(query=query, sort_by="latest_at", descending=True, limit=limit)
        target_currency = self.display_currency_var.get() or self.config.display_currency
        rate = self.db.get_exalted_per_divine()
        if not rows:
            self._configure_focus_result_scroll(36, False)
            row = Frame(self.focus_search_results, bg="#ffffff", pady=8)
            row.pack(fill=X)
            Label(row, text="没有查询到匹配物品", fg="#7b8794", bg="#ffffff", font=("Microsoft YaHei UI", 12)).pack(anchor="w")
            self._position_focus_search_overlay(144)
            return

        for index, row_data in enumerate(rows):
            item = Frame(self.focus_search_results, bg="#ffffff", pady=4)
            item.pack(fill=X)
            if index:
                Canvas(item, height=1, bg="#e8eef5", highlightthickness=0).pack(fill=X, pady=(0, 6))
            body = Frame(item, bg="#ffffff")
            body.pack(fill=X)
            name_box = Frame(body, bg="#ffffff")
            name_box.pack(side=LEFT, fill=X, expand=True)
            Label(
                name_box,
                text=row_data.item_name,
                fg="#172033",
                bg="#ffffff",
                font=("Microsoft YaHei UI", 13, "bold"),
                anchor="w",
            ).pack(anchor="w")
            subtitle = f"{row_data.source}  {self._format_time(row_data.latest_at)}"
            Label(name_box, text=subtitle, fg="#8a97a6", bg="#ffffff", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(1, 0))
            amount = convert_amount(row_data.latest_amount, row_data.latest_currency, target_currency, rate)
            price_text = f"{amount:g} {target_currency}"
            price_box = Frame(body, bg="#ffffff")
            price_box.pack(side=RIGHT, padx=(16, 0))
            Label(price_box, text=price_text, fg="#c77d00", bg="#ffffff", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="e")
            trend_color = "#1f9d55" if row_data.trend_percent.startswith("+") else "#d64545" if row_data.trend_percent.startswith("-") else "#8a97a6"
            Label(price_box, text=f"趋势 {row_data.trend_percent or '暂无'}", fg=trend_color, bg="#ffffff", font=("Microsoft YaHei UI", 9)).pack(anchor="e")
            self._bind_focus_result_click_recursive(item, row_data.item_name)
        visible_rows = min(len(rows), 5)
        result_height = self._measure_focus_result_height(visible_rows)
        self._configure_focus_result_scroll(result_height, len(rows) > 5)
        self._position_focus_search_overlay(96 + result_height)

    def _measure_focus_result_height(self, visible_rows: int) -> int:
        if self.focus_search_results is None:
            return max(1, visible_rows) * 64
        try:
            self.focus_search_results.update_idletasks()
            children = self.focus_search_results.winfo_children()[:visible_rows]
            measured = sum(max(child.winfo_reqheight(), child.winfo_height()) for child in children)
        except Exception:
            measured = 0
        return max(max(1, visible_rows) * 64, measured + 6)

    def _configure_focus_result_scroll(self, height: int, scrollable: bool) -> None:
        canvas = self.focus_search_results_canvas
        scrollbar = self.focus_search_results_scrollbar
        if canvas is None or scrollbar is None:
            return
        canvas.configure(height=height)
        if scrollable:
            scrollbar.pack(side=RIGHT, fill=Y)
            self._bind_focus_result_wheel_recursive(canvas, canvas)
            if self.focus_search_results is not None:
                self._bind_focus_result_wheel_recursive(self.focus_search_results, canvas)
        else:
            scrollbar.pack_forget()
            canvas.yview_moveto(0)
        canvas.after_idle(lambda: canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, 0, 0)))

    def _bind_focus_result_wheel_recursive(self, widget, canvas) -> None:
        try:
            widget.bind("<MouseWheel>", lambda event: canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_focus_result_wheel_recursive(child, canvas)

    def _bind_focus_result_click_recursive(self, widget, item_name: str) -> None:
        try:
            widget.bind("<Button-1>", lambda _event, name=item_name: self._choose_focus_search_item(name), add="+")
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_focus_result_click_recursive(child, item_name)

    def _choose_focus_search_item(self, item_name: str) -> None:
        self.search_var.set(item_name)
        self._reset_page_and_refresh()
        self.destroy_focus_search_overlay()

    def _show_stats(self, stats: PriceStats) -> None:
        text = (
            f"{stats.item_name}\n"
            f"最新：{stats.latest_amount:g} {stats.latest_currency}\n"
            f"记录数：{stats.count}\n"
            f"均价：{stats.avg_amount:g} {stats.latest_currency}\n"
            f"最低/最高：{stats.min_amount:g} / {stats.max_amount:g} {stats.latest_currency}\n"
            f"最近记录：{stats.latest_at}"
        )
        self._write_result(text)

    def _write_result(self, text: str) -> None:
        self.status_var.set(text.replace("\n", "  "))

    def add_manual_record(self) -> None:
        item = self.manual_item_var.get().strip()
        currency = self.manual_currency_var.get().strip() or "崇高石"
        if not item or not currency:
            messagebox.showwarning("缺少信息", "物品名和价格单位都需要填写。")
            return
        try:
            amount = float(self.manual_amount_var.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showwarning("价格格式错误", "价格数量需要是数字。")
            return
        self.save_manual_favorite_setting()
        self.db.add_price_record(
            item,
            amount,
            currency,
            "人工添加",
            confidence=1.0,
            raw_text="手动记录",
        )
        if self.config.manual_add_favorite:
            self.db.set_favorite(item, True)
        self.search_var.set(item)
        self.clear_manual_record_form()
        self.show_market_page()
        self.status_var.set(f"已保存：{item} = {amount:g} {currency}")

    def lookup_from_screenshot(self) -> None:
        parsed, image_path, message = self._capture_and_parse("lookup")
        if not parsed:
            return
        if parsed.item_name:
            self.search_var.set(parsed.item_name)
            self.search()
            stats = self.db.get_stats(parsed.item_name)
            if stats:
                self._show_overlay(stats)
            else:
                self._show_overlay_text(f"{parsed.item_name}\n没有本地价格记录")
        else:
            self.status_var.set(f"截图完成但未识别到物品名：{image_path} {message}")

    def capture_price_from_screenshot(self) -> None:
        parsed, image_path, message = self._capture_and_parse("price")
        if not parsed:
            return
        dialog = ConfirmPriceDialog(self.root, parsed, image_path, message)
        self.root.wait_window(dialog.window)
        if not dialog.result:
            return
        item, amount, currency, source, confidence, raw = dialog.result
        self.db.add_price_record(
            item,
            amount,
            currency,
            source,
            confidence=confidence,
            raw_text=raw,
            screenshot_path=str(image_path),
        )
        self.search_var.set(item)
        self.search()
        self.refresh_market_table()
        self.status_var.set(f"已保存截图价格：{item} = {amount:g} {currency}")

    def quick_price_from_clipboard(self, raw_text: str | None = None) -> None:
        if raw_text is None:
            try:
                self._quick_price_foreground_hwnd = int(ctypes.windll.user32.GetForegroundWindow())
            except Exception:
                self._quick_price_foreground_hwnd = 0
            self._send_ctrl_c()
            self.progress_var.set("正在读取游戏复制内容...")
            self.root.after(260, self._quick_price_from_current_clipboard)
            return
        self._show_quick_price_for_text(raw_text or "")

    def _quick_price_from_current_clipboard(self) -> None:
        try:
            raw_text = self.root.clipboard_get()
        except Exception:
            self._set_progress_idle("快速查价：未读取到物品")
            self._show_quick_price_overlay("未读取到物品", "请把鼠标放在物品上，再按快速查价键。", "", "")
            return
        self._show_quick_price_for_text(raw_text or "")

    @staticmethod
    def _send_ctrl_c() -> None:
        user32 = ctypes.windll.user32
        ctrl = 0x11
        c_key = 0x43
        keyup = 0x0002
        user32.keybd_event(ctrl, 0, 0, 0)
        user32.keybd_event(c_key, 0, 0, 0)
        user32.keybd_event(c_key, 0, keyup, 0)
        user32.keybd_event(ctrl, 0, keyup, 0)

    def _show_quick_price_for_text(self, raw_text: str) -> None:
        item = parse_poe_clipboard_item(raw_text)
        if not item.item_name:
            self._set_progress_idle("快速查价：未识别到物品")
            self._show_quick_price_overlay("未识别到物品名", "剪贴板内容不是可识别的游戏物品。", "", "")
            return
        stats = self.db.get_stats(item.item_name)
        if not stats:
            self._set_progress_idle(f"快速查价：未查询到 {item.item_name}")
            self._show_quick_price_overlay(item.item_name, "没有本地价格记录", item.rarity, "")
            return
        history = self.db.get_price_history(stats.item_name, limit=12)
        trend = trend_percent([record.amount for record in history])
        price = f"{stats.latest_amount:g} {stats.latest_currency}"
        subtitle = item.rarity or "本地物价"
        self._set_progress_idle(f"快速查价：{stats.item_name} {price}")
        self._show_quick_price_overlay(stats.item_name, price, subtitle, trend)

    def _show_quick_price_overlay(self, title: str, price: str, subtitle: str, trend: str) -> None:
        width, height = 430, 230
        trend_color = "#2fb344" if trend.startswith("+") else "#e03131" if trend.startswith("-") else "#9fb5cf"
        overlay = self.quick_price_overlay
        if overlay is None or not self._toplevel_exists(overlay):
            overlay = Toplevel(self.root)
            self.quick_price_overlay = overlay
            overlay.overrideredirect(True)
            overlay.attributes("-topmost", True)
            try:
                overlay.attributes("-alpha", 0.92)
            except Exception:
                pass
            overlay.configure(bg="#10151d")
            overlay.bind("<Escape>", lambda _event: self._destroy_quick_price_overlay())

            frame = Frame(overlay, bg="#10151d", padx=22, pady=20)
            frame.pack(fill=BOTH, expand=True)
            subtitle_label = Label(frame, fg="#9fb5cf", bg="#10151d", font=("Microsoft YaHei UI", 11))
            subtitle_label.pack(anchor="w")
            title_label = Label(
                frame,
                fg="#f8fafc",
                bg="#10151d",
                font=("Microsoft YaHei UI", 18, "bold"),
                wraplength=380,
                justify=LEFT,
            )
            title_label.pack(anchor="w", pady=(8, 12))
            price_label = Label(frame, fg="#ffd166", bg="#10151d", font=("Microsoft YaHei UI", 22, "bold"))
            price_label.pack(anchor="w")
            trend_label = Label(
                frame,
                bg="#10151d",
                font=("Microsoft YaHei UI", 13, "bold"),
            )
            trend_label.pack(anchor="w", pady=(14, 0))
            hint_label = Label(
                frame,
                text="点击或 Esc 关闭，5 秒后自动隐藏",
                fg="#718096",
                bg="#10151d",
                font=("Microsoft YaHei UI", 10),
            )
            hint_label.pack(anchor="e", side="bottom")
            self.quick_price_overlay_labels = {
                "subtitle": subtitle_label,
                "title": title_label,
                "price": price_label,
                "trend": trend_label,
            }
            self._bind_destroy_on_click_recursive(overlay, overlay)

        labels = self.quick_price_overlay_labels
        labels["subtitle"].configure(text=subtitle or "快速查价")
        labels["title"].configure(text=title)
        labels["price"].configure(text=price)
        labels["trend"].configure(text=f"趋势 {trend or '暂无'}", fg=trend_color)
        x = max(24, min(self.root.winfo_pointerx() + 24, overlay.winfo_screenwidth() - width - 24))
        y = max(24, min(self.root.winfo_pointery() + 24, overlay.winfo_screenheight() - height - 24))
        overlay.geometry(f"{width}x{height}+{x}+{y}")
        overlay.lift()
        self.root.after(40, self._restore_quick_price_foreground)
        if self.quick_price_overlay_hide_job is not None:
            try:
                self.root.after_cancel(self.quick_price_overlay_hide_job)
            except Exception:
                pass
        self.quick_price_overlay_hide_job = self.root.after(5000, self._destroy_quick_price_overlay)
        self.quick_price_overlay_watch_token += 1
        token = self.quick_price_overlay_watch_token
        left_down = self._left_mouse_down()
        self.root.after(60, lambda: self._watch_quick_price_overlay(overlay, time.monotonic(), not left_down, left_down, token))

    @staticmethod
    def _toplevel_exists(window: Toplevel) -> bool:
        try:
            return bool(window.winfo_exists())
        except Exception:
            return False

    def _destroy_quick_price_overlay(self) -> None:
        overlay = self.quick_price_overlay
        if self.quick_price_overlay_hide_job is not None:
            try:
                self.root.after_cancel(self.quick_price_overlay_hide_job)
            except Exception:
                pass
            self.quick_price_overlay_hide_job = None
        self.quick_price_overlay_watch_token += 1
        self.quick_price_overlay = None
        self.quick_price_overlay_labels = {}
        if overlay is not None and self._toplevel_exists(overlay):
            overlay.destroy()

    @staticmethod
    def _left_mouse_down() -> bool:
        try:
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        except Exception:
            return False

    def _bind_destroy_on_click_recursive(self, widget, target: Toplevel) -> None:
        try:
            widget.bind("<Button-1>", lambda _event: self._destroy_quick_price_overlay(), add="+")
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_destroy_on_click_recursive(child, target)

    def _watch_quick_price_overlay(
        self,
        overlay: Toplevel,
        created_at: float,
        click_armed: bool,
        was_left_down: bool,
        token: int,
    ) -> None:
        try:
            if token != self.quick_price_overlay_watch_token or not overlay.winfo_exists():
                return
            user32 = ctypes.windll.user32
            if user32.GetAsyncKeyState(0x1B) & 0x0001:
                self._destroy_quick_price_overlay()
                return
            left_down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
            if not click_armed:
                click_armed = not left_down
            elif left_down and not was_left_down:
                point = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(point))
                left = overlay.winfo_rootx()
                top = overlay.winfo_rooty()
                right = left + overlay.winfo_width()
                bottom = top + overlay.winfo_height()
                if not (left <= point.x <= right and top <= point.y <= bottom):
                    self._destroy_quick_price_overlay()
                    return
        except Exception:
            return
        self.root.after(80, lambda: self._watch_quick_price_overlay(overlay, created_at, click_armed, left_down, token))

    def _restore_quick_price_foreground(self) -> None:
        hwnd = int(getattr(self, "_quick_price_foreground_hwnd", 0) or 0)
        if not hwnd:
            return
        try:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def open_capture_workbench(self) -> None:
        try:
            image_path = capture_full_screen(
                self.config.screenshots_path,
                "workbench",
                max_files=self._screenshot_retention_count(),
            )
        except Exception as exc:
            messagebox.showerror("截图失败", str(exc))
            return
        RegionOcrWorkbench(
            self.root,
            self.config,
            self.db,
            image_path,
            self._on_region_record_saved,
        )

    def start_area_capture(self, restore_after: bool = False) -> None:
        if self._area_capture_active:
            self.status_var.set("截图识别正在进行中。")
            return
        self._area_capture_active = True
        self._restore_after_area_capture = restore_after
        self.root.withdraw()
        self.root.update_idletasks()
        self.root.after(25, self._capture_for_selection)

    def _capture_for_selection(self) -> None:
        try:
            screenshot = capture_full_screen_image()
        except Exception as exc:
            self._area_capture_active = False
            if self._restore_after_area_capture:
                self.root.deiconify()
            messagebox.showerror("截图失败", str(exc))
            return
        ScreenshotSelectionOverlay(
            self.root,
            screenshot,
            self._recognize_selected_area,
            on_cancel=self._cancel_area_capture,
        )

    def _cancel_area_capture(self) -> None:
        self._area_capture_active = False
        if self._restore_after_area_capture:
            self.root.deiconify()

    def _recognize_selected_area(self, image_source: Path | Image.Image, box: tuple[int, int, int, int]) -> None:
        if self._restore_after_area_capture:
            self.root.deiconify()
        self._begin_selected_area_lookup(image_source, box)

    def _begin_selected_area_lookup(self, image_source: Path | Image.Image, box: tuple[int, int, int, int]) -> None:
        self.ocr_review_rows = []
        self.ocr_review_raw_text = ""
        self.ocr_review_image_path = Path()
        self.ocr_selected_index = None
        if self._should_update_ocr_review_page() and self._restore_after_area_capture:
            self.show_ocr_review_page()
        elif self._should_update_ocr_review_page() and getattr(self, "current_page_name", "") == "ocr":
            self.show_ocr_review_page()
        if self._should_update_ocr_review_page():
            self._set_ocr_running_ui(True)
        self.show_screenshot_lookup_loading()
        self._set_progress_busy("正在识别截图内容...")
        self.status_var.set("正在识别截图内容，请稍候。")
        threading.Thread(
            target=self._recognize_selected_area_worker_fast,
            args=(image_source, box),
            daemon=True,
        ).start()

    def _recognize_selected_area_worker_fast(self, image_source: Path | Image.Image, box: tuple[int, int, int, int]) -> None:
        worker_db = None
        crop_path = Path()
        previous_priority = None
        try:
            if getattr(self.config, "ocr_low_priority", True):
                previous_priority = self._set_ocr_process_priority(True)
            crop_path, ocr_path = crop_and_prepare_for_ocr(
                image_source,
                box,
                self.config.screenshots_path,
                "selected-area",
                "selected-area-ocr",
                max_files=self._screenshot_retention_count(),
            )
            with self.ocr_lock:
                result = self.ocr.recognize(ocr_path)
            self._restore_process_priority(previous_priority)
            previous_priority = None
            worker_db = PriceDatabase(self.config.database_path)
            rows = recognize_structured_prices(ocr_path, result, db=worker_db, default_currency="崇高石")
            if not rows:
                rows = parse_item_price_rows(result.text, default_currency="崇高石")
            candidates = self._screenshot_lookup_candidates(ocr_path, result, rows, worker_db)
            lookup_rows = self._market_rows_for_candidates(candidates, worker_db)
            if not rows:
                message = result.message or "没有识别到价格列表。请尝试框得更紧一些，或在配置中检查截图识别功能。"
            else:
                message = ""
            self._post_event(
                (
                    "screenshot_lookup_done",
                    bool(rows),
                    rows,
                    lookup_rows,
                    result.text,
                    str(crop_path),
                    message,
                )
            )
        except Exception as exc:
            self._post_event(("screenshot_lookup_done", False, [], [], "", str(crop_path), str(exc)))
        finally:
            self._restore_process_priority(previous_priority)
            if worker_db is not None:
                worker_db.close()

    def _screenshot_lookup_candidates(
        self,
        crop_path: Path,
        result,
        rows: list[ParsedItemPrice],
        db: PriceDatabase,
    ) -> list[RecognizedItemCandidate]:
        candidates: list[RecognizedItemCandidate] = []
        for row in rows:
            confidence = self._ocr_row_confidence(row)
            candidates.append(
                RecognizedItemCandidate(
                    item_name=row.item_name,
                    raw_text=row.raw_text,
                    confidence=confidence,
                    item_match_score=row.item_match_score,
                )
            )
        candidates.extend(recognize_item_candidates(crop_path, result, db=db, min_score=0.62))
        return candidates

    def _market_rows_for_candidates(
        self,
        candidates: list[RecognizedItemCandidate],
        db: PriceDatabase,
    ) -> list[tuple[MarketRow, float, str]]:
        results: list[tuple[MarketRow, float, str]] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.confidence < 0.58:
                continue
            if hasattr(db, "match_item_name_strict"):
                matched_name, match_score = db.match_item_name_strict(candidate.item_name)
            else:
                matched_name, match_score = db.match_item_name(candidate.item_name, min_score=0.92)
            confidence = max(candidate.confidence, min(1.0, 0.35 + match_score * 0.65))
            if match_score < 0.92 or confidence < 0.92:
                continue
            rows = db.get_market_rows(query=matched_name, sort_by="latest_at", descending=True, limit=5)
            if not rows:
                continue
            exact_key = normalize_name(matched_name)
            chosen = next((row for row in rows if normalize_name(row.item_name) == exact_key), rows[0])
            key = normalize_name(chosen.item_name)
            if key in seen:
                continue
            seen.add(key)
            results.append((chosen, confidence, candidate.raw_text))
        return results

    def open_image_workbench(self) -> None:
        path = filedialog.askopenfilename(
            title="选择要识别的截图",
            filetypes=[
                ("图片文件", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        RegionOcrWorkbench(
            self.root,
            self.config,
            self.db,
            Path(path),
            self._on_region_record_saved,
        )

    def _on_region_record_saved(self, item_name: str) -> None:
        self.search_var.set(item_name)
        self.search()
        self.refresh_market_table()

    def _capture_and_parse(self, prefix: str) -> tuple[ParsedPrice | None, Path, str]:
        try:
            image_path = capture_around_cursor(
                self.config.screenshots_path,
                self.config.screenshot_width,
                self.config.screenshot_height,
                prefix,
                max_files=self._screenshot_retention_count(),
            )
        except Exception as exc:
            messagebox.showerror("截图失败", str(exc))
            return None, Path(), str(exc)

        self.ocr = self._make_ocr_engine()
        ocr_result = self.ocr.recognize(image_path)
        parsed = parse_ocr_text(ocr_result.text)
        message = ocr_result.message
        if not ocr_result.ok and not message:
            message = "识别未返回文本"
        return parsed, image_path, message

    def diagnose_image_ocr(self) -> None:
        path = filedialog.askopenfilename(
            title="选择截图图片",
            filetypes=[
                ("图片文件", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        try:
            prepared_path = prepare_image_for_ocr(
                Path(path),
                self.config.screenshots_path,
                "diagnose",
                max_files=self._screenshot_retention_count(),
            )
        except Exception as exc:
            messagebox.showerror("图片预处理失败", str(exc))
            return

        self.ocr = self._make_ocr_engine()
        ocr_result = self.ocr.recognize(prepared_path)
        parsed = parse_ocr_text(ocr_result.text)
        self._show_ocr_diagnostic(Path(path), prepared_path, parsed, ocr_result.message)

    def _show_ocr_diagnostic(
        self,
        source_path: Path,
        prepared_path: Path,
        parsed: ParsedPrice,
        message: str,
    ) -> None:
        window = Toplevel(self.root)
        window.title("识别诊断")
        window.geometry("760x620")
        window.transient(self.root)

        body = Frame(window, padx=12, pady=12)
        body.pack(fill=BOTH, expand=True)

        summary = (
            f"原图：{source_path}\n"
            f"预处理图：{prepared_path}\n"
            f"识别物品：{parsed.item_name or '(无)'}\n"
            f"识别价格："
            f"{'' if parsed.amount is None else f'{parsed.amount:g}'} {parsed.currency}\n"
            f"置信度：{parsed.confidence:.2f}\n"
            f"{'识别提示：' + message if message else ''}"
        )
        Label(body, text=summary, justify=LEFT, anchor="w").pack(fill=X)
        Label(body, text="原始识别文本").pack(anchor="w", pady=(10, 0))
        raw = Text(body, height=20, wrap="word")
        raw.pack(fill=BOTH, expand=True)
        raw.insert("1.0", parsed.raw_text)
        Button(body, text="关闭", command=window.destroy).pack(anchor="e", pady=(10, 0))

    def _refresh_recent(self) -> None:
        self.refresh_market_table()

    def _show_overlay(self, stats: PriceStats) -> None:
        self._show_overlay_text(
            f"{stats.item_name}\n"
            f"最新 {stats.latest_amount:g} {stats.latest_currency}\n"
            f"均价 {stats.avg_amount:g}  记录 {stats.count}"
        )

    def _show_overlay_text(self, text: str) -> None:
        overlay = Toplevel(self.root)
        overlay.title("价格")
        overlay.attributes("-topmost", True)
        overlay.geometry("+80+80")
        frame = Frame(overlay, padx=14, pady=12, bg="#111")
        frame.pack(fill=BOTH, expand=True)
        Label(frame, text=text, justify=LEFT, fg="#f4f4f4", bg="#111").pack()
        overlay.after(5000, overlay.destroy)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.root, self.config)
        self.root.wait_window(dialog.window)
        self.ocr = self._make_ocr_engine()
        self.reload_hotkeys()
        self.status_var.set(f"设置已加载。数据目录：{self.config.data_path}")

    def check_for_updates(self) -> None:
        if self.updating:
            self.progress_var.set("更新正在进行中，请稍候...")
            return
        info = check_update(self.config.update_manifest)
        if info.available and info.download_url:
            if messagebox.askyesno(
                "发现更新",
                f"{info.message}\n当前：{info.current_version}\n最新：{info.latest_version}\n\n下载并安装？",
            ):
                self.updating = True
                self._set_progress_percent(0, "正在下载更新...")
                threading.Thread(target=self._download_update_worker, args=(info,), daemon=True).start()
            return
        messagebox.showinfo(
            "检查更新",
            f"{info.message}\n当前版本：{info.current_version}\n最新版本：{info.latest_version}",
        )

    def _download_update_worker(self, info: UpdateInfo) -> None:
        def progress(percent: int, url: str) -> None:
            self.events.put(("update_progress", percent, url))

        try:
            result = download_update(
                self.config.update_manifest,
                info,
                self.config.data_path / "updates",
                progress=progress,
            )
            self.events.put(
                (
                    "update_done",
                    True,
                    "" if result.executable_path is None else str(result.executable_path),
                    result.message,
                )
            )
        except Exception as exc:
            self.events.put(("update_done", False, "", str(exc)))

    def _sync_state_path(self) -> Path:
        return self.config.data_path / "sync_state.json"

    def _read_sync_state(self) -> dict:
        try:
            path = self._sync_state_path()
            if not path.exists():
                return {}
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_sync_state(self, state: dict) -> None:
        try:
            self.config.data_path.mkdir(parents=True, exist_ok=True)
            self._sync_state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            return

    def _economy_sync_remaining_seconds(self) -> int:
        value = str(self._read_sync_state().get("last_economy_sync_attempt_at", ""))
        if not value:
            return 0
        try:
            last = datetime.fromisoformat(value)
        except ValueError:
            return 0
        elapsed = (datetime.now() - last).total_seconds()
        return max(0, int(30 * 60 - elapsed))

    def _record_economy_sync_attempt(self) -> None:
        state = self._read_sync_state()
        state["last_economy_sync_attempt_at"] = datetime.now().isoformat(timespec="seconds")
        self._write_sync_state(state)

    def sync_poe2db_currency(self) -> None:
        if self.syncing:
            self.progress_var.set("同步正在进行中，请稍候...")
            return
        remaining = self._economy_sync_remaining_seconds()
        if remaining > 0:
            minutes = remaining // 60
            seconds = remaining % 60
            text = f"经济数据同步每 30 分钟最多一次，请 {minutes:02d}:{seconds:02d} 后再试。"
            self.progress_var.set(text)
            self.status_var.set(text)
            messagebox.showinfo("同步冷却中", text)
            return
        self._record_economy_sync_attempt()
        self.syncing = True
        self._set_progress_percent(0, "正在同步 poe2db 经济数据，请稍候...")
        self.status_var.set("同步中...")
        threading.Thread(target=self._sync_worker, daemon=True).start()

    def _sync_worker(self) -> None:
        try:
            batch = fetch_all_economy_prices(
                progress=lambda index, total, category, url: self.events.put(
                    ("sync_progress", index, total, category, url)
                ),
            )
        except Exception as exc:
            self.events.put(("sync_error", f"无法同步 poe2db：{exc}"))
            return
        self.events.put(("sync_done", batch, datetime.now().isoformat()))

    def _finish_sync(self, batch, _finished_at: str) -> None:
        self.syncing = False
        results = batch.results
        if not results:
            detail = "\n".join(batch.errors[:8]) if batch.errors else "没有返回任何分类数据。"
            messagebox.showerror("同步失败", f"没有同步到数据。\n\n{detail}")
            self.status_var.set("poe2db 同步失败。")
            self._set_progress_idle("同步失败，未获得数据。")
            return
        saved = 0
        for result in results:
            for row in result.rows:
                self.db.add_price_record(
                    row.item_name,
                    row.amount,
                    row.currency,
                    f"poe2db-{result.category}",
                    confidence=1.0,
                    raw_text=row.raw_text,
                    screenshot_path=result.source_url,
                )
                saved += 1
        self.refresh_market_table()
        warning = f"\n\n部分分类失败：\n" + "\n".join(batch.errors[:6]) if batch.errors else ""
        self.status_var.set(f"poe2db 同步完成：{saved} 条。")
        self._set_progress_idle(f"同步完成：{len(results)} 个分类，{saved} 条数据。")
        messagebox.showinfo("同步完成", f"已同步 {saved} 条 poe2db 经济数据。{warning}")

    def close(self) -> None:
        self.hotkeys.stop()
        self.db.close()
        self.root.destroy()

    def on_window_unmap(self, event=None) -> None:
        if event is not None and event.widget is not self.root:
            return
        if self._ignore_unmap_prompt:
            return
        self.root.after(80, self._handle_minimize_if_needed)

    def _handle_minimize_if_needed(self) -> None:
        if self._ignore_unmap_prompt or self.root.state() != "iconic":
            return
        action = self.config.minimize_action
        if action == "ask":
            self._ignore_unmap_prompt = True
            self.root.deiconify()
            self._ignore_unmap_prompt = False
            to_tray = messagebox.askyesno(
                "最小化方式",
                "最小化后是否隐藏到右下角小图标？\n\n选择“是”：隐藏窗口，继续后台运行。\n选择“否”：保留在任务栏。",
            )
            self.config.minimize_action = "tray" if to_tray else "taskbar"
            self.minimize_action_var.set(self._window_action_label(self.config.minimize_action, "minimize"))
            save_config(self.config)
            action = self.config.minimize_action
        if action == "tray":
            self.hide_to_background()
        elif action == "taskbar":
            self._ignore_unmap_prompt = True
            self.root.iconify()
            self.root.after(120, self._reset_unmap_guard)

    def on_close_request(self) -> None:
        action = self.config.close_action
        if action == "ask":
            to_tray = messagebox.askyesno(
                "关闭窗口",
                "点击关闭时是否继续后台运行？\n\n选择“是”：隐藏到右下角小图标。\n选择“否”：退出软件。",
            )
            self.config.close_action = "tray" if to_tray else "exit"
            self.close_action_var.set(self._window_action_label(self.config.close_action, "close"))
            save_config(self.config)
            action = self.config.close_action
        if action == "exit":
            self.exit_app()
        else:
            self.hide_to_background()

    def hide_to_background(self) -> None:
        if pystray is None:
            self._ignore_unmap_prompt = True
            self.root.iconify()
            self.root.after(120, self._reset_unmap_guard)
            return
        self._ignore_unmap_prompt = True
        self.root.withdraw()
        self.root.after(120, self._reset_unmap_guard)
        self._ensure_tray_icon()

    def _reset_unmap_guard(self) -> None:
        self._ignore_unmap_prompt = False

    def exit_app(self) -> None:
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None
        self.close()

    def _ensure_tray_icon(self) -> None:
        if pystray is None or self.tray_icon is not None:
            return
        image = self._load_app_icon_image(64)

        def restore(_icon=None, _item=None):
            self.root.after(0, self.restore_from_tray)

        def quit_app(_icon=None, _item=None):
            self.root.after(0, self.exit_app)

        self.tray_icon = pystray.Icon(
            "PoE2PriceTracker",
            image,
            "流放之路2 物价追踪",
            menu=pystray.Menu(
                pystray.MenuItem("显示主窗口", restore, default=True),
                pystray.MenuItem("退出", quit_app),
            ),
        )
        self.tray_icon.run_detached()

    def restore_from_tray(self) -> None:
        self.root.deiconify()
        self.root.lift()


def _acquire_single_instance() -> bool:
    global _INSTANCE_MUTEX_HANDLE
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\PoE2PriceTrackerSingleInstance")
        if not handle:
            return True
        _INSTANCE_MUTEX_HANDLE = handle
        if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            ctypes.windll.user32.MessageBoxW(None, "程序已在运行。", "流放之路2 物价追踪", 0x00000040)
            return False
    except Exception:
        return True
    return True


def main() -> None:
    if not _acquire_single_instance():
        sys.exit(0)
    if tb is not None:
        root = tb.Window(themename="flatly")
    else:
        root = Tk()
    app = PriceTrackerApp(root)
    root.mainloop()


__all__ = ["main", "PriceTrackerApp"]
