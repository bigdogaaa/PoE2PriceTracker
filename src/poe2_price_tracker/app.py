from __future__ import annotations

import queue
import ctypes
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    TOP,
    X,
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

from .config import AppConfig, load_config, save_config
from .currencies import BASE_CURRENCIES
from .db import PriceDatabase, PriceStats, convert_amount
from .hotkeys import GlobalHotkeys, parse_hotkey
from .ocr import TesseractOcr
from .ocr_setup import prepare_tesseract_ocr
from .parser import ParsedItemPrice, ParsedPrice, find_number, meaningful_lines, parse_item_price_rows, parse_ocr_text
from .poe2db_sync import fetch_all_economy_prices
from .screenshot import capture_around_cursor, capture_full_screen, crop_image, prepare_image_for_ocr
from .updater import check_update


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

        message = f"OCR：{ocr_message}" if ocr_message else "OCR：完成"
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

        self.width_var = StringVar(value=str(config.screenshot_width))
        self.height_var = StringVar(value=str(config.screenshot_height))
        self.manifest_var = StringVar(value=config.update_manifest)
        self.lookup_hotkey_var = StringVar(value=config.hotkeys.lookup_hovered)
        self.capture_hotkey_var = StringVar(value=config.hotkeys.capture_price)
        self.focus_hotkey_var = StringVar(value=config.hotkeys.focus_search)

        body = Frame(self.window, padx=18, pady=16)
        body.pack(fill=BOTH, expand=True)

        Label(
            body,
            text="快捷键",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w")
        for label, variable in [
            ("截图识别实验台", self.lookup_hotkey_var),
            ("截图价格入库", self.capture_hotkey_var),
            ("聚焦搜索框", self.focus_hotkey_var),
        ]:
            row = Frame(body)
            row.pack(fill=X, pady=(8, 0))
            Label(row, text=label, width=16, anchor="w").pack(side=LEFT)
            HotkeyCaptureButton(row, variable).pack(side=LEFT, fill=X, expand=True)

        Label(
            body,
            text="截图范围",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w", pady=(18, 0))
        size_row = Frame(body)
        size_row.pack(fill=X, pady=(8, 0))
        Label(size_row, text="悬停截图宽度").pack(side=LEFT)
        Entry(size_row, textvariable=self.width_var, width=8).pack(side=LEFT, padx=(8, 18))
        Label(size_row, text="高度").pack(side=LEFT)
        Entry(size_row, textvariable=self.height_var, width=8).pack(side=LEFT, padx=(8, 0))

        Label(
            body,
            text="程序已按国服中文默认调好 OCR：中文简体 + 英文。通常不需要额外配置。",
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
        try:
            self.config.screenshot_width = max(120, int(self.width_var.get()))
            self.config.screenshot_height = max(120, int(self.height_var.get()))
        except ValueError:
            messagebox.showwarning("设置错误", "截图宽高需要是整数。", parent=self.window)
            return
        hotkeys = [
            self.lookup_hotkey_var.get().strip(),
            self.capture_hotkey_var.get().strip(),
            self.focus_hotkey_var.get().strip(),
        ]
        try:
            for hotkey in hotkeys:
                parse_hotkey(hotkey)
        except ValueError as exc:
            messagebox.showwarning("快捷键格式错误", str(exc), parent=self.window)
            return
        if len({hotkey.lower() for hotkey in hotkeys}) != len(hotkeys):
            messagebox.showwarning("快捷键重复", "三个快捷键不能重复。", parent=self.window)
            return
        self.config.tesseract_cmd = "tesseract"
        self.config.ocr_languages = "chi_sim+eng"
        self.config.ocr_psm = 6
        self.config.hotkeys.lookup_hovered = hotkeys[0]
        self.config.hotkeys.capture_price = hotkeys[1]
        self.config.hotkeys.focus_search = hotkeys[2]
        self.config.update_manifest = self.manifest_var.get().strip()
        save_config(self.config)
        self.window.destroy()


class ScreenshotSelectionOverlay:
    def __init__(self, parent: Tk, image_path: Path, on_confirm, on_cancel=None):
        self.parent = parent
        self.image_path = image_path
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

        self.original = Image.open(image_path)
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        self.scale = min(screen_w / self.original.width, screen_h / self.original.height)
        display_size = (
            int(self.original.width * self.scale),
            int(self.original.height * self.scale),
        )
        self.display_image = self.original.resize(display_size).convert("RGB")
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
            if self.selection_image_id:
                self.canvas.delete(self.selection_image_id)
            if right > left and bottom > top:
                crop = self.display_image.crop((left, top, right, bottom))
                self.selection_photo = ImageTk.PhotoImage(crop)
                self.selection_image_id = self.canvas.create_image(left, top, anchor="nw", image=self.selection_photo)
            self.canvas.coords(self.rect_id, x0, y0, x1, y1)
            self.canvas.tag_raise(self.rect_id)

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
        self.on_confirm(self.image_path, box)

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
        self.tree.heading("raw", text="OCR Raw")
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
        Button(actions, text="查看 OCR 原文", command=self.show_raw).pack(side=LEFT)

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
                currency,
                "ocr-selection",
                confidence=0.85,
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
        window.title("OCR 原文")
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

        raw_box = LabelFrame(right, text="OCR 原文", padx=12, pady=12)
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

        ocr = TesseractOcr(
            self.config.tesseract_cmd,
            self.config.ocr_languages,
            self.config.ocr_psm,
        )
        item_crop = crop_image(
            self.image_path,
            self.rectangles["item"],
            self.config.screenshots_path,
            "item-region",
        )
        price_crop = crop_image(
            self.image_path,
            self.rectangles["price"],
            self.config.screenshots_path,
            "price-region",
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
            self.status_var.set("OCR 未完整返回文本。请检查 Tesseract 是否安装，或缩小/重框区域。")
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
        self.ocr = TesseractOcr(
            self.config.tesseract_cmd,
            self.config.ocr_languages,
            self.config.ocr_psm,
        )
        self.hotkeys = GlobalHotkeys()
        self.events: queue.Queue[str] = queue.Queue()

        self.search_var = StringVar()
        self.item_var = StringVar()
        self.amount_var = StringVar()
        self.currency_var = StringVar(value="Divine Orb")
        self.source_var = StringVar(value="人工添加")
        self.status_var = StringVar(value=f"数据目录：{self.config.data_path}")
        self.progress_var = StringVar(value="就绪")
        self.tray_icon = None
        self.syncing = False
        self.page_var = StringVar(value="1")
        self.page_size_var = StringVar(value=str(self.config.page_size))
        self.display_currency_var = StringVar(value=self.config.display_currency)
        self.sort_column = "latest_at"
        self.sort_descending = True
        self.source_filter_var = StringVar(value="全部来源")
        self.trend_widgets = []
        self.trend_data = {}
        self.search_debounce_job = None
        self.trend_render_job = None
        self._ignore_unmap_prompt = False
        self.context_item_name = ""

        self.root.title("流放之路2 物价追踪")
        self.root.geometry("1120x760")
        self.root.minsize(980, 640)
        self._configure_style()
        self._build_menu()
        self._build_ui()
        self._register_hotkeys()
        self._refresh_recent()
        self._poll_events()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_request)
        self.root.bind("<Unmap>", self.on_window_unmap, add="+")

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        size = int(getattr(self.config, "font_size", 13))
        rowheight = max(64, size * 3 + 20)
        style.configure("Treeview", rowheight=rowheight, font=("Microsoft YaHei UI", size))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", size, "bold"))
        style.configure("TNotebook.Tab", padding=(16, 8))

    def _build_menu(self) -> None:
        self.root.config(menu=Menu(self.root))

    def _build_ui(self) -> None:
        self.sort_var = StringVar(value="最近更新")
        self.settings_font_var = StringVar(value=str(self.config.font_size))
        self.settings_width_var = StringVar(value=str(self.config.screenshot_width))
        self.settings_height_var = StringVar(value=str(self.config.screenshot_height))
        self.settings_manifest_var = StringVar(value=self.config.update_manifest)
        self.manual_item_var = StringVar()
        self.manual_amount_var = StringVar()
        self.manual_currency_var = StringVar(value="崇高石")
        self.manual_favorite_var = StringVar(value="1" if self.config.manual_add_favorite else "0")
        self.minimize_action_var = StringVar(value=self._window_action_label(self.config.minimize_action, "minimize"))
        self.close_action_var = StringVar(value=self._window_action_label(self.config.close_action, "close"))

        shell = Frame(self.root, padx=0, pady=0)
        shell.pack(fill=BOTH, expand=True)

        self.sidebar = Frame(shell, padx=16, pady=18, width=210)
        self.sidebar.pack(side=LEFT, fill="y")
        self.sidebar.pack_propagate(False)
        Label(self.sidebar, text="流放之路2 物价", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w", pady=(0, 18))
        self._nav_button("物价列表", self.show_market_page).pack(fill=X, pady=4)
        self._nav_button("收藏列表", self.show_favorites_page).pack(fill=X, pady=4)
        Frame(self.sidebar).pack(fill=BOTH, expand=True)
        self._nav_button("手动记录", self.show_manual_record_page).pack(fill=X, pady=4)
        self._nav_button("同步经济数据", self.sync_poe2db_currency).pack(fill=X, pady=4)
        self._nav_button("配置", self.show_settings_page).pack(fill=X, pady=4)

        self.content = Frame(shell, padx=22, pady=18)
        self.content.pack(side=LEFT, fill=BOTH, expand=True)
        self.bottom_bar = Frame(self.root, padx=14, pady=8)
        self.bottom_bar.pack(side="bottom", fill=X)
        Label(self.bottom_bar, textvariable=self.progress_var, anchor="w").pack(side=LEFT, fill=X, expand=True)
        self.progress = ttk.Progressbar(self.bottom_bar, mode="indeterminate", length=180)
        self.progress.pack(side=RIGHT)
        self.show_market_page()

    def _nav_button(self, text: str, command):
        return Button(self.sidebar, text=text, command=command)

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
        self.current_favorites_only = False
        self._build_market_page("物价列表", favorites_only=False)

    def show_favorites_page(self) -> None:
        self.current_favorites_only = True
        self._build_market_page("收藏列表", favorites_only=True)

    def show_manual_record_page(self) -> None:
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
        unit_values = ["崇高石", "神圣石"] + [name for name in BASE_CURRENCIES if name not in {"Exalted Orb", "Divine Orb"}]
        Combobox(row, textvariable=self.manual_currency_var, values=unit_values, width=24).pack(side=LEFT)

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

    def _build_market_page(self, title: str, favorites_only: bool) -> None:
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
        self.market_tree = ttk.Treeview(table_box, columns=columns, show="headings", selectmode="browse")
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
        for key in columns:
            self.market_tree.heading(key, text=headings[key], command=lambda k=key: self.sort_by_column(k))
            anchor = "center" if key in {"index", "favorite", "count"} else "w"
            self.market_tree.column(key, width=widths[key], anchor=anchor)
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

    def show_settings_page(self) -> None:
        self._clear_content()
        Label(self.content, text="配置", font=("Microsoft YaHei UI", self.config.font_size + 8, "bold")).pack(anchor="w")
        grid = Frame(self.content)
        grid.pack(fill=X, pady=(18, 0))

        left = LabelFrame(grid, text="快捷键", padx=14, pady=12)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        for label, variable in [
            ("截图识别", StringVar(value=self.config.hotkeys.lookup_hovered)),
            ("截图入库", StringVar(value=self.config.hotkeys.capture_price)),
            ("聚焦搜索", StringVar(value=self.config.hotkeys.focus_search)),
        ]:
            row = Frame(left)
            row.pack(fill=X, pady=6)
            Label(row, text=label, width=12, anchor="w").pack(side=LEFT)
            button = HotkeyCaptureButton(row, variable)
            button.pack(side=LEFT, fill=X, expand=True)
            variable.trace_add("write", lambda *_args, v=variable, n=label: self._save_hotkey_setting(n, v.get()))

        right = LabelFrame(grid, text="显示与截图", padx=14, pady=12)
        right.pack(side=LEFT, fill=BOTH, expand=True, padx=(10, 0))
        for label, variable in [
            ("鼠标附近截图宽度", self.settings_width_var),
            ("鼠标附近截图高度", self.settings_height_var),
            ("默认每页数量", self.page_size_var),
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

        window_box = LabelFrame(self.content, text="窗口行为", padx=14, pady=12)
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

        update_box = LabelFrame(self.content, text="更新", padx=14, pady=12)
        update_box.pack(fill=X, pady=(16, 0))
        Entry(update_box, textvariable=self.settings_manifest_var).pack(fill=X)
        self.settings_manifest_var.trace_add("write", lambda *_args: self.save_inline_settings())

        ocr_box = LabelFrame(self.content, text="OCR", padx=14, pady=12)
        ocr_box.pack(fill=X, pady=(16, 0))
        Label(
            ocr_box,
            text="截图识别需要本地 OCR。可自动下载到软件数据目录并配置，不需要安装 Python。",
            foreground="#607080",
            wraplength=760,
        ).pack(side=LEFT, fill=X, expand=True)
        Button(ocr_box, text="自动准备 OCR", command=self.prepare_ocr_runtime).pack(side=RIGHT, padx=(12, 0))

        danger_box = LabelFrame(self.content, text="数据", padx=14, pady=12)
        danger_box.pack(fill=X, pady=(16, 0))
        Label(
            danger_box,
            text="清空已记录数据会删除本地所有价格记录、收藏和置顶，不影响配置。",
            foreground="#9a3412",
            wraplength=760,
        ).pack(side=LEFT, fill=X, expand=True)
        Button(danger_box, text="清空已记录数据", command=self.clear_recorded_data).pack(side=RIGHT, padx=(12, 0))

        Label(
            self.content,
            text="鼠标附近截图尺寸用于旧的悬停截图入库：按快捷键时截取鼠标周围固定范围。现在主流程的框选截图不受这个尺寸影响。",
            foreground="#777",
            wraplength=760,
        ).pack(anchor="w", pady=(16, 0))

    def _save_hotkey_setting(self, label: str, value: str) -> None:
        try:
            parse_hotkey(value)
        except ValueError:
            return
        if label == "截图识别":
            self.config.hotkeys.lookup_hovered = value
        elif label == "截图入库":
            self.config.hotkeys.capture_price = value
        elif label == "聚焦搜索":
            self.config.hotkeys.focus_search = value
        save_config(self.config)
        self.reload_hotkeys()

    def save_inline_settings(self) -> None:
        try:
            self.config.screenshot_width = max(120, int(self.settings_width_var.get()))
            self.config.screenshot_height = max(120, int(self.settings_height_var.get()))
            self.config.page_size = max(10, min(500, int(self.page_size_var.get())))
        except ValueError:
            return
        self.config.update_manifest = self.settings_manifest_var.get().strip()
        save_config(self.config)
        self._configure_style()
        self.status_var.set("配置已自动保存。")

    def save_window_behavior_settings(self) -> None:
        self.config.minimize_action = self._window_action_value(self.minimize_action_var.get(), "minimize")
        self.config.close_action = self._window_action_value(self.close_action_var.get(), "close")
        save_config(self.config)
        self.status_var.set("窗口行为已保存。")

    def prepare_ocr_runtime(self) -> None:
        if getattr(self, "ocr_preparing", False):
            return
        self.ocr_preparing = True
        self.progress.configure(mode="determinate", maximum=100, value=0)
        self.progress_var.set("正在准备 OCR...")
        thread = threading.Thread(target=self._prepare_ocr_runtime_worker, daemon=True)
        thread.start()

    def _prepare_ocr_runtime_worker(self) -> None:
        def progress(percent: int, url: str) -> None:
            self.events.put(("ocr_progress", percent, url))

        try:
            result = prepare_tesseract_ocr(
                self.config.data_path,
                self.config.ocr_download_url,
                progress=progress,
            )
            self.events.put(("ocr_done", result.ok, str(result.tesseract_path), result.message))
        except Exception as exc:
            self.events.put(("ocr_done", False, "", str(exc)))

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

    def sort_by_column(self, column: str) -> None:
        mapping = {
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
            self.market_tree.insert(
                "",
                END,
                iid=row.item_name,
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
            )
            history = [record.amount for record in self.db.get_price_history(row.item_name, limit=8)]
            self.trend_data[row.item_name] = (history, row.trend_percent)
        self._apply_visible_columns()
        self.root.update_idletasks()
        self._auto_fit_market_columns()
        self._schedule_trend_render(120)
        self.status_var.set(f"共 {total} 条记录，第 {page}/{max_page} 页")

    def _market_sort_key(self, row, target_currency: str, rate: float):
        column = self.sort_column
        if column == "index":
            return row.item_name.casefold()
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
        display_columns = self.market_tree["displaycolumns"]
        visible = set() if display_columns == "#all" or display_columns == ("#all",) else set(display_columns)
        if visible and "trend" not in visible:
            return
        for iid in self.market_tree.get_children():
            bbox = self.market_tree.bbox(iid, "trend")
            if not bbox:
                continue
            x, y, width, height = bbox
            values, percent = self.trend_data.get(iid, ([], ""))
            canvas = Canvas(self.market_tree, width=width - 6, height=height - 6, highlightthickness=0, bg="#ffffff")
            canvas.place(x=x + 3, y=y + 3)
            self._draw_trend(canvas, values, percent, width - 6, height - 6)
            self.trend_widgets.append(canvas)

    def _draw_trend(self, canvas: Canvas, values: list[float], percent: str, width: int, height: int) -> None:
        color = "#18a058"
        if percent.startswith("-"):
            color = "#d03050"
        if len(values) >= 2:
            low, high = min(values), max(values)
            span = high - low or 1
            points = []
            usable_w = max(32, width - 52)
            for index, value in enumerate(values):
                px = 4 + index * usable_w / max(1, len(values) - 1)
                py = height - 8 - (value - low) / span * max(10, height - 16)
                points.extend((px, py))
            canvas.create_line(*points, fill=color, width=2, smooth=True)
        if percent:
            canvas.create_text(width - 4, height / 2, text=percent, anchor="e", fill=color, font=("Microsoft YaHei UI", 10, "bold"))

    def _auto_fit_market_columns(self) -> None:
        if not self._has_market_tree():
            return
        display_columns = self.market_tree["displaycolumns"]
        visible = list(self.market_tree["columns"]) if display_columns == "#all" or display_columns == ("#all",) else list(display_columns)
        if not visible:
            return
        tree_width = max(760, self.market_tree.winfo_width() - 26)
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
            if label in self.config.visible_columns:
                visible.append(key)
        self.market_tree.configure(displaycolumns=visible or list(key_to_label))
        self.root.update_idletasks()
        self._auto_fit_market_columns()

    def open_column_settings(self) -> None:
        window = Toplevel(self.root)
        window.title("显示列")
        window.geometry("360x420")
        variables: dict[str, StringVar] = {}
        labels = ["序号", "物品", "价格", "单位", "走势", "记录", "来源", "更新时间", "收藏"]
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
            lambda: self.events.put("open_workbench"),
        )
        self.hotkeys.register(
            self.config.hotkeys.capture_price,
            lambda: self.events.put("capture_price"),
        )
        self.hotkeys.register(
            self.config.hotkeys.focus_search,
            lambda: self.events.put("focus_search"),
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
                f"查询 {self.config.hotkeys.lookup_hovered}，"
                f"入库 {self.config.hotkeys.capture_price}，"
                f"搜索 {self.config.hotkeys.focus_search}"
            )

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if isinstance(event, tuple) and event[0] == "sync_done":
                    self._finish_sync(event[1], event[2])
                elif isinstance(event, tuple) and event[0] == "sync_progress":
                    _kind, index, total, category, url = event
                    percent = int(index / total * 100)
                    self.progress.configure(mode="determinate", maximum=100, value=percent)
                    self.progress_var.set(f"同步中 {percent}%：{category}  {url}")
                elif isinstance(event, tuple) and event[0] == "sync_error":
                    self.syncing = False
                    self.progress.stop()
                    self.progress.configure(mode="indeterminate")
                    self.progress_var.set("同步失败")
                    messagebox.showerror("同步失败", event[1])
                elif isinstance(event, tuple) and event[0] == "ocr_progress":
                    _kind, percent, url = event
                    self.progress.configure(mode="determinate", maximum=100, value=percent)
                    self.progress_var.set(f"OCR 准备中 {percent}%：{url}")
                elif isinstance(event, tuple) and event[0] == "ocr_done":
                    _kind, ok, tesseract_path, message = event
                    self.ocr_preparing = False
                    self.progress.configure(mode="indeterminate", value=0)
                    if ok:
                        self.config.tesseract_cmd = tesseract_path
                        self.config.ocr_languages = "chi_sim+eng"
                        save_config(self.config)
                        self.ocr = TesseractOcr(
                            self.config.tesseract_cmd,
                            self.config.ocr_languages,
                            self.config.ocr_psm,
                        )
                        self.progress_var.set("OCR 已准备好")
                        self.status_var.set("OCR 已自动下载并配置完成。")
                        messagebox.showinfo("OCR", "OCR 已准备好。")
                    else:
                        self.progress_var.set("OCR 准备失败")
                        messagebox.showerror("OCR 准备失败", message)
                elif event == "open_workbench":
                    self.start_area_capture()
                elif event == "capture_price":
                    self.capture_price_from_screenshot()
                elif event == "focus_search":
                    self.root.deiconify()
                    self.root.lift()
                    self.search_entry.focus_set()
        except queue.Empty:
            pass
        self.root.after(120, self._poll_events)

    def search(self) -> None:
        self.refresh_market_table()

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

    def open_capture_workbench(self) -> None:
        try:
            image_path = capture_full_screen(self.config.screenshots_path, "workbench")
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

    def start_area_capture(self) -> None:
        self.root.withdraw()
        self.root.after(160, self._capture_for_selection)

    def _capture_for_selection(self) -> None:
        try:
            image_path = capture_full_screen(self.config.screenshots_path, "selection")
        except Exception as exc:
            self.root.deiconify()
            messagebox.showerror("截图失败", str(exc))
            return
        ScreenshotSelectionOverlay(
            self.root,
            image_path,
            self._recognize_selected_area,
            on_cancel=lambda: self.root.deiconify(),
        )

    def _recognize_selected_area(self, image_path: Path, box: tuple[int, int, int, int]) -> None:
        self.root.deiconify()
        try:
            crop_path = crop_image(image_path, box, self.config.screenshots_path, "selected-area")
        except Exception as exc:
            messagebox.showerror("裁剪失败", str(exc))
            return
        ocr = TesseractOcr(
            self.config.tesseract_cmd,
            self.config.ocr_languages,
            self.config.ocr_psm,
        )
        result = ocr.recognize(crop_path)
        rows = parse_item_price_rows(result.text, default_currency="Exalted Orb")
        if not rows:
            message = result.message or "没有识别到 item-price 行。请尝试框得更紧一些，或确认本地 OCR 已安装中文语言包。"
            messagebox.showwarning("未识别到价格列表", message)
            self._show_ocr_diagnostic(image_path, crop_path, parse_ocr_text(result.text), message)
            return
        OcrReviewDialog(
            self.root,
            self.db,
            rows,
            result.text,
            crop_path,
            self._refresh_recent,
        )

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
            )
        except Exception as exc:
            messagebox.showerror("截图失败", str(exc))
            return None, Path(), str(exc)

        self.ocr = TesseractOcr(
            self.config.tesseract_cmd,
            self.config.ocr_languages,
            self.config.ocr_psm,
        )
        ocr_result = self.ocr.recognize(image_path)
        parsed = parse_ocr_text(ocr_result.text)
        message = ocr_result.message
        if not ocr_result.ok and not message:
            message = "OCR 未返回文本"
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
            )
        except Exception as exc:
            messagebox.showerror("图片预处理失败", str(exc))
            return

        self.ocr = TesseractOcr(
            self.config.tesseract_cmd,
            self.config.ocr_languages,
            self.config.ocr_psm,
        )
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
        window.title("OCR 诊断")
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
            f"{'OCR 提示：' + message if message else ''}"
        )
        Label(body, text=summary, justify=LEFT, anchor="w").pack(fill=X)
        Label(body, text="原始 OCR 文本").pack(anchor="w", pady=(10, 0))
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
        self.ocr = TesseractOcr(
            self.config.tesseract_cmd,
            self.config.ocr_languages,
            self.config.ocr_psm,
        )
        self.reload_hotkeys()
        self.status_var.set(f"设置已加载。数据目录：{self.config.data_path}")

    def check_for_updates(self) -> None:
        info = check_update(self.config.update_manifest)
        if info.available and info.download_url:
            if messagebox.askyesno(
                "发现更新",
                f"{info.message}\n当前版本：{info.current_version}\n最新版本：{info.latest_version}\n\n打开下载地址？",
            ):
                webbrowser.open(info.download_url)
            return
        messagebox.showinfo(
            "检查更新",
            f"{info.message}\n当前版本：{info.current_version}\n最新版本：{info.latest_version}",
        )

    def sync_poe2db_currency(self) -> None:
        if self.syncing:
            self.progress_var.set("同步正在进行中，请稍候...")
            return
        self.syncing = True
        self.progress_var.set("正在同步 poe2db 经济数据，请稍候...")
        self.status_var.set("同步中...")
        self.progress.configure(mode="determinate", maximum=100, value=0)
        threading.Thread(target=self._sync_worker, daemon=True).start()

    def _sync_worker(self) -> None:
        try:
            batch = fetch_all_economy_prices(
                progress=lambda index, total, category, url: self.events.put(
                    ("sync_progress", index, total, category, url)
                )
            )
        except Exception as exc:
            self.events.put(("sync_error", f"无法同步 poe2db：{exc}"))
            return
        self.events.put(("sync_done", batch, datetime.now().isoformat()))

    def _finish_sync(self, batch, _finished_at: str) -> None:
        self.syncing = False
        self.progress.configure(mode="indeterminate", value=0)
        results = batch.results
        if not results:
            detail = "\n".join(batch.errors[:8]) if batch.errors else "没有返回任何分类数据。"
            messagebox.showerror("同步失败", f"没有同步到数据。\n\n{detail}")
            self.status_var.set("poe2db 同步失败。")
            self.progress_var.set("同步失败，未获得数据。")
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
        self.progress_var.set(f"同步完成：{len(results)} 个分类，{saved} 条数据。")
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
                "最小化到右下角小图标？\n\n是：后台运行\n否：保留在任务栏",
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
                "关闭后继续后台运行？\n\n是：最小化到右下角\n否：退出软件",
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
        image = Image.new("RGB", (64, 64), "#2f80ed")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill="#ffffff")
        draw.text((19, 19), "P2", fill="#2f80ed")

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
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None


def main() -> None:
    if tb is not None:
        root = tb.Window(themename="flatly")
    else:
        root = Tk()
    app = PriceTrackerApp(root)
    root.mainloop()


__all__ = ["main", "PriceTrackerApp"]
