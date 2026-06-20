# Copyright (c) 2026 大狗狗
# This file is part of this project and is licensed under the GNU GPL-3.0-only.
# See the LICENSE file for details.

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
        label="\u767d\u8272",
        ttk_theme="flatly",
        is_dark=False,
        background="#f5f7fb",
        surface="#ffffff",
        surface_alt="#eef4f8",
        sidebar="#eaf1f7",
        card="#ffffff",
        border="#d3dde8",
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
        overlay_bg="#eef3f7",
        overlay_surface="#fbfdff",
        overlay_text="#111827",
        overlay_muted="#64748b",
        overlay_accent="#9a5b12",
        overlay_border="#d7e0ea",
    ),
    "night": AppTheme(
        key="night",
        label="\u6df1\u8272",
        ttk_theme="darkly",
        is_dark=True,
        background="#0e1117",
        surface="#151a22",
        surface_alt="#1d2430",
        sidebar="#10141b",
        card="#181f29",
        border="#303a49",
        text="#edf2f8",
        muted="#a8b3c3",
        subtle="#7c8798",
        primary="#8ab4f8",
        primary_hover="#a6c8ff",
        primary_text="#07111f",
        accent="#f6c177",
        danger="#ff7b8a",
        success="#7dd3a8",
        warning="#f4bf75",
        pinned="#302b1d",
        input_bg="#0f141b",
        selection_bg="#26384f",
        tree_heading="#1d2430",
        overlay_bg="#090c12",
        overlay_surface="#151b23",
        overlay_text="#f1f5f9",
        overlay_muted="#9fb0c4",
        overlay_accent="#e8b86d",
        overlay_border="#2f3b4d",
    ),
    "poe2": AppTheme(
        key="poe2",
        label="\u9ed1\u91d1",
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
        primary="#c8923d",
        primary_hover="#e3b15f",
        primary_text="#171009",
        accent="#b6503f",
        danger="#c44a3d",
        success="#9bbf69",
        warning="#d6a84f",
        pinned="#332313",
        input_bg="#0f0b08",
        selection_bg="#3a2817",
        tree_heading="#231911",
        overlay_bg="#090705",
        overlay_surface="#16110d",
        overlay_text="#f2e6d2",
        overlay_muted="#b79b70",
        overlay_accent="#d2a14a",
        overlay_border="#4b3724",
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
