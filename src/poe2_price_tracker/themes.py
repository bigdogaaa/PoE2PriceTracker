from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppTheme:
    key: str
    label: str
    ttk_theme: str
    is_dark: bool
    background: str
    surface: str
    surface_alt: str
    sidebar: str
    card: str
    border: str
    text: str
    muted: str
    subtle: str
    primary: str
    primary_hover: str
    primary_text: str
    accent: str
    danger: str
    success: str
    warning: str
    pinned: str
    input_bg: str
    selection_bg: str
    tree_heading: str
    overlay_bg: str
    overlay_surface: str
    overlay_text: str
    overlay_muted: str
    overlay_accent: str
    overlay_border: str


THEMES: dict[str, AppTheme] = {
    "default": AppTheme(
        key="default",
        label="\u9ed8\u8ba4",
        ttk_theme="flatly",
        is_dark=False,
        background="#f5f7fb",
        surface="#ffffff",
        surface_alt="#eef3f8",
        sidebar="#edf3f8",
        card="#ffffff",
        border="#d7e0ea",
        text="#162033",
        muted="#536273",
        subtle="#7b8794",
        primary="#2563eb",
        primary_hover="#1d4ed8",
        primary_text="#ffffff",
        accent="#d92d20",
        danger="#d92d20",
        success="#067647",
        warning="#b54708",
        pinned="#fff7d6",
        input_bg="#ffffff",
        selection_bg="#dbeafe",
        tree_heading="#edf3f8",
        overlay_bg="#f1f5f9",
        overlay_surface="#ffffff",
        overlay_text="#172033",
        overlay_muted="#667085",
        overlay_accent="#ffd166",
        overlay_border="#d8e1ea",
    ),
    "night": AppTheme(
        key="night",
        label="\u591c\u95f4",
        ttk_theme="darkly",
        is_dark=True,
        background="#0f172a",
        surface="#111c2f",
        surface_alt="#17243a",
        sidebar="#0b1220",
        card="#121f33",
        border="#27364d",
        text="#e5edf7",
        muted="#a6b4c8",
        subtle="#718096",
        primary="#60a5fa",
        primary_hover="#3b82f6",
        primary_text="#08111f",
        accent="#f59e0b",
        danger="#fb7185",
        success="#34d399",
        warning="#fbbf24",
        pinned="#2f2a16",
        input_bg="#0b1220",
        selection_bg="#1e3a5f",
        tree_heading="#17243a",
        overlay_bg="#0b1220",
        overlay_surface="#101b2d",
        overlay_text="#edf4ff",
        overlay_muted="#9fb0c8",
        overlay_accent="#fbbf24",
        overlay_border="#2a3b55",
    ),
    "poe2": AppTheme(
        key="poe2",
        label="\u6d41\u653e\u4e4b\u8def2",
        ttk_theme="darkly",
        is_dark=True,
        background="#0d0b09",
        surface="#17120e",
        surface_alt="#211914",
        sidebar="#100c09",
        card="#1c1510",
        border="#4a3928",
        text="#eadfca",
        muted="#c4ad86",
        subtle="#8f7857",
        primary="#b88a3b",
        primary_hover="#d2a85a",
        primary_text="#130e09",
        accent="#8f2f24",
        danger="#c44a3d",
        success="#9bbf69",
        warning="#d6a84f",
        pinned="#332313",
        input_bg="#0f0b08",
        selection_bg="#3a2817",
        tree_heading="#231911",
        overlay_bg="#090705",
        overlay_surface="#17110c",
        overlay_text="#f1e5d0",
        overlay_muted="#bda37a",
        overlay_accent="#d6a84f",
        overlay_border="#5a4028",
    ),
}

THEME_LABELS = tuple(theme.label for theme in THEMES.values())
THEME_KEYS = tuple(THEMES.keys())


def normalize_theme_key(value: str) -> str:
    key = str(value or "").strip().lower()
    return key if key in THEMES else "default"


def theme_for_key(value: str) -> AppTheme:
    return THEMES[normalize_theme_key(value)]


def theme_label_for_key(value: str) -> str:
    return theme_for_key(value).label


def theme_key_for_label(value: str) -> str:
    label = str(value or "").strip()
    for key, theme in THEMES.items():
        if theme.label == label:
            return key
    return normalize_theme_key(label)
