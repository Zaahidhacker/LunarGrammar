"""On-demand, keyboard-accessible settings and model availability check.

Elevated configuration center featuring:
- General Tab: Default Mode selector (0-5), Windows startup, waveform/sound toggle, diff preview.
- AI Engine Tab: Model selector dropdown, API key input with mask & 'Test Connection', custom temperature/instructions.
- Cache & Diagnostics Tab: Live cache hits/misses, memory usage, 'Clear Cache' button.
- Exclusions Tab: Add/remove process names (e.g. game.exe, keepass.exe) where shortcuts are suppressed.
- About & Shortcut Cheatsheet: Visual table of all Luna shortcuts (Ctrl+Win+Z, 0-5, Ctrl+Win+U).
"""

import ctypes as c
import math
import os
import sys
import tkinter as tk
from ctypes import wintypes as w
from dataclasses import replace
from pathlib import Path, PureWindowsPath
from queue import Empty, SimpleQueue
from threading import Thread
from tkinter import font as tkfont, ttk

import win32 as win
from config import (
    AppError,
    SETTINGS_PATH,
    api_key,
    app_command,
    load_api_key_dpapi,
    load_settings,
    store_api_key_dpapi,
    update_settings,
)
from pill_art import ASSETS, FONT_DIR, LIME


def startup_link() -> Path:
    return Path(os.environ["APPDATA"]) / (
        "Microsoft/Windows/Start Menu/Programs/Startup/Luna Grammar.lnk"
    )


def save_startup(enabled: bool):
    path = startup_link()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    from comtypes.client import CreateObject

    executable, *arguments = app_command(windowless=True)
    if not Path(executable).is_file():
        raise AppError("Could not locate the Luna Grammar executable for Windows startup.")
    shell = CreateObject("WScript.Shell", dynamic=True)
    shortcut = shell.CreateShortcut(str(path))
    shortcut.TargetPath = executable
    shortcut.Arguments = f'"{arguments[0]}"' if arguments else ""
    shortcut.WorkingDirectory = str(Path(arguments[0] if arguments else executable).parent)
    shortcut.Save()


def user_has_startup_key() -> bool:
    if load_api_key_dpapi():
        return True
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as env:
            value, _ = winreg.QueryValueEx(env, "OPENAI_API_KEY")
            return isinstance(value, str) and bool(value.strip())
    except OSError:
        return False


def get_process_memory_mb() -> float:
    """Return current process Working Set Size in MB using Win32 psapi."""
    try:
        class PROCESS_MEMORY_COUNTERS(c.Structure):
            _fields_ = [
                ("cb", w.DWORD),
                ("PageFaultCount", w.DWORD),
                ("PeakWorkingSetSize", c.c_size_t),
                ("WorkingSetSize", c.c_size_t),
                ("QuotaPeakPagedPoolUsage", c.c_size_t),
                ("QuotaPagedPoolUsage", c.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", c.c_size_t),
                ("QuotaNonPagedPoolUsage", c.c_size_t),
                ("PagefileUsage", c.c_size_t),
                ("PeakPagefileUsage", c.c_size_t),
            ]

        psapi = c.WinDLL("psapi.dll")
        kernel32 = c.WinDLL("kernel32.dll")
        psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, c.POINTER(PROCESS_MEMORY_COUNTERS), w.DWORD]
        psapi.GetProcessMemoryInfo.restype = w.BOOL
        kernel32.GetCurrentProcess.restype = w.HANDLE

        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = c.sizeof(PROCESS_MEMORY_COUNTERS)
        if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), c.byref(pmc), pmc.cb):
            return round(pmc.WorkingSetSize / (1024 * 1024), 2)
    except Exception:
        pass
    return 0.0


def query_cache_stats() -> dict:
    """Inspect GrammarEngine's RefinementCache for hits, misses, size, and hit ratio."""
    try:
        import grammar_engine
        if hasattr(grammar_engine, "get_default_cache"):
            cache = grammar_engine.get_default_cache()
            if hasattr(cache, "stats"):
                return cache.stats()
        if hasattr(grammar_engine, "get_cache_stats"):
            return grammar_engine.get_cache_stats()
        if hasattr(grammar_engine, "CACHE"):
            cache = grammar_engine.CACHE
            if hasattr(cache, "stats"):
                return cache.stats()
            if hasattr(cache, "get_stats"):
                return cache.get_stats()
        if hasattr(grammar_engine, "RefinementCache"):
            rc = grammar_engine.RefinementCache
            if hasattr(rc, "instance") and hasattr(rc.instance(), "stats"):
                return rc.instance().stats()
            if hasattr(rc, "get_stats"):
                return rc.get_stats()
    except Exception:
        pass
    return {"hits": 0, "misses": 0, "size": 0, "hit_ratio": 0.0}


def execute_clear_cache() -> bool:
    """Clear response cache across any cache engine implementation."""
    try:
        import grammar_engine
        if hasattr(grammar_engine, "get_default_cache"):
            cache = grammar_engine.get_default_cache()
            if hasattr(cache, "clear"):
                cache.clear()
                return True
        if hasattr(grammar_engine, "clear_cache"):
            grammar_engine.clear_cache()
            return True
        if hasattr(grammar_engine, "CACHE") and hasattr(grammar_engine.CACHE, "clear"):
            grammar_engine.CACHE.clear()
            return True
        if hasattr(grammar_engine, "RefinementCache"):
            rc = grammar_engine.RefinementCache
            if hasattr(rc, "instance") and hasattr(rc.instance(), "clear"):
                rc.instance().clear()
                return True
            if hasattr(rc, "clear"):
                rc.clear()
                return True
    except Exception:
        pass
    return False


class SettingsDialog:
    """Encapsulates the elevated Luna Settings dialog window and tabs."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings(SETTINGS_PATH)
        self._init_theme()
        self._init_variables()
        self._build_ui()
        self._init_shortcuts()

    def _init_theme(self):
        self.dark = self.settings.appearance == "dark"
        self.bg = "#121414" if self.dark else "#F4F6F0"
        self.card = "#1B1E1B" if self.dark else "#FFFFFF"
        self.card_secondary = "#232723" if self.dark else "#F8FAF5"
        self.border = "#363B35" if self.dark else "#D2D9CE"
        self.ink = "#F1F4EF" if self.dark else "#1C211B"
        self.secondary = "#9EAAA0" if self.dark else "#5C675B"
        self.accent = LIME if self.dark else "#365716"
        self.accent_bg = "#22351E" if self.dark else "#E5EED8"
        self.danger = "#FF6B6B" if self.dark else "#C82333"

        # Fonts
        self.family = "Poppins" if "Poppins" in tkfont.families(self.root) else "Segoe UI"
        self.root.option_add("*Font", (self.family, 10))
        self.root.configure(background=self.bg)

        # TTK styles
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        self.style.configure(
            "TCombobox",
            fieldbackground=self.card,
            background=self.card,
            foreground=self.ink,
            arrowcolor=self.ink,
            bordercolor=self.border,
            selectbackground=self.card,
            selectforeground=self.ink,
            padding=5,
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.card)],
            foreground=[("readonly", self.ink)],
            selectbackground=[("readonly", self.card)],
            selectforeground=[("readonly", self.ink)],
        )

    def _init_variables(self):
        s = self.settings
        self.enabled_var = tk.BooleanVar(value=s.enabled)
        self.startup_var = tk.BooleanVar(value=startup_link().exists())
        self.waveform_var = tk.BooleanVar(value=s.sound_enabled)
        self.feedback_var = tk.BooleanVar(value=s.feedback)
        self.shorthand_var = tk.BooleanVar(value=s.expand_shorthand)
        self.diff_preview_var = tk.BooleanVar(value=s.show_diff_preview)
        self.cache_enabled_var = tk.BooleanVar(value=s.cache_enabled)
        self.copy_only_var = tk.BooleanVar(value=s.copy_only)
        self.strict_clipboard_var = tk.BooleanVar(value=s.clipboard_strict_preservation)
        self.review_var = tk.BooleanVar(value=s.review_before_apply)

        # Mode selection (0-5)
        self.mode_labels = [
            "0: Grammar & Spelling (Ctrl+Win+Z)",
            "1: Casual Polish (Ctrl+Win+1+Z)",
            "2: Executive Concise (Ctrl+Win+2+Z)",
            "3: Academic & Formal (Ctrl+Win+3+Z)",
            "4: Bulletize & Summarize (Ctrl+Win+4+Z)",
            "5: Translate to English (Ctrl+Win+5+Z)",
        ]
        curr_mode = s.default_mode if 0 <= s.default_mode < len(self.mode_labels) else 0
        self.default_mode_var = tk.StringVar(value=self.mode_labels[curr_mode])

        # Model & AI
        self.model_var = tk.StringVar(value=s.active_model)
        self.temperature_var = tk.StringVar(value=f"{s.temperature:.1f}")
        self.custom_prompt_var = tk.StringVar(value=s.custom_prompt)
        self.appearance_var = tk.StringVar(value=s.appearance.title())
        self.motion_var = tk.StringVar(value="Follow Windows" if s.motion == "system" else "Reduced")

        # API Key
        env_key = os.environ.get("OPENAI_API_KEY", "").strip()
        stored_key = load_api_key_dpapi()
        self.api_key_var = tk.StringVar()
        self.key_masked = tk.BooleanVar(value=True)
        if env_key:
            connection_status = "API key detected in environment"
        elif stored_key:
            connection_status = "API key saved for this Windows user"
        else:
            connection_status = "No API key configured"
        self.connection_status_var = tk.StringVar(value=connection_status)
        self.connection_color_var = tk.StringVar(value=self.accent if env_key or stored_key else self.secondary)

        # Diagnostics variables
        self.diag_hits_var = tk.StringVar(value="0")
        self.diag_misses_var = tk.StringVar(value="0")
        self.diag_ratio_var = tk.StringVar(value="0.0%")
        self.diag_size_var = tk.StringVar(value="0 items")
        self.diag_memory_var = tk.StringVar(value=f"{get_process_memory_mb():.1f} MB")
        self.diag_status_var = tk.StringVar(value="Ready")

        # Global status
        self.status_var = tk.StringVar(value="")

    def _build_ui(self):
        # Outer container
        self.main_container = tk.Frame(self.root, bg=self.bg, padx=22, pady=16)
        self.main_container.pack(fill="both", expand=True)

        # Top Header
        header = tk.Frame(self.main_container, bg=self.bg)
        header.pack(fill="x", pady=(0, 10))

        title_row = tk.Frame(header, bg=self.bg)
        title_row.pack(fill="x")
        tk.Label(
            title_row,
            text="LUNA GRAMMAR",
            bg=self.bg,
            fg=self.accent,
            font=(self.family, 9, "bold"),
        ).pack(side="left")
        tk.Label(
            title_row,
            text="· Configuration Center",
            bg=self.bg,
            fg=self.secondary,
            font=(self.family, 9),
        ).pack(side="left", padx=(4, 0))

        tk.Label(
            header,
            text="Settings",
            bg=self.bg,
            fg=self.ink,
            font=(self.family, 20, "bold"),
        ).pack(anchor="w", pady=(1, 0))

        # Modern Tab Navigation Bar
        self.nav_bar = tk.Frame(self.main_container, bg=self.bg)
        self.nav_bar.pack(fill="x", pady=(2, 10))

        self.tabs = [
            ("general", "General"),
            ("ai", "AI Engine"),
            ("cache", "Cache & Diagnostics"),
            ("exclusions", "Exclusions"),
            ("about", "Shortcuts & About"),
        ]
        self.tab_buttons = {}
        self.tab_frames = {}

        # Content container
        self.content_area = tk.Frame(self.main_container, bg=self.bg)
        self.content_area.pack(fill="both", expand=True, pady=(0, 8))

        for key, label in self.tabs:
            btn = tk.Button(
                self.nav_bar,
                text=label,
                command=lambda k=key: self.switch_tab(k),
                bg=self.bg,
                fg=self.secondary,
                activebackground=self.card,
                activeforeground=self.accent,
                relief="flat",
                bd=0,
                padx=11,
                pady=6,
                font=(self.family, 9),
                cursor="hand2",
            )
            btn.pack(side="left", padx=(0, 4))
            self.tab_buttons[key] = btn

            # Create container frame for each tab
            t_frame = tk.Frame(self.content_area, bg=self.bg)
            self.tab_frames[key] = t_frame

        # Build each tab's contents
        self._build_general_tab(self.tab_frames["general"])
        self._build_ai_tab(self.tab_frames["ai"])
        self._build_cache_tab(self.tab_frames["cache"])
        self._build_exclusions_tab(self.tab_frames["exclusions"])
        self._build_about_tab(self.tab_frames["about"])

        # Bottom Footer (persistent across all tabs)
        footer = tk.Frame(self.main_container, bg=self.bg)
        footer.pack(fill="x", side="bottom", pady=(4, 0))

        self.status_lbl = tk.Label(
            footer,
            textvariable=self.status_var,
            bg=self.bg,
            fg=self.secondary,
            font=(self.family, 9),
            anchor="w",
            wraplength=320,
            justify="left",
        )
        self.status_lbl.pack(side="left", fill="x", expand=True)

        tk.Button(
            footer,
            text="Cancel",
            command=self.root.destroy,
            bg=self.card,
            fg=self.ink,
            activebackground=self.border,
            activeforeground=self.ink,
            relief="flat",
            bd=0,
            padx=14,
            pady=6,
            font=(self.family, 9),
            cursor="hand2",
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            footer,
            text="Save Settings",
            command=self.save,
            bg=self.accent,
            fg=self.bg if self.dark else "#FFFFFF",
            activebackground=self.ink,
            activeforeground=self.bg,
            relief="flat",
            bd=0,
            padx=16,
            pady=6,
            font=(self.family, 9, "bold"),
            cursor="hand2",
        ).pack(side="right")

        # Default to first tab
        self.switch_tab("general")

    def _section_box(self, parent: tk.Widget, title: str) -> tk.Frame:
        card_frame = tk.Frame(
            parent,
            bg=self.card,
            padx=14,
            pady=10,
            highlightthickness=1,
            highlightbackground=self.border,
        )
        card_frame.pack(fill="x", pady=(0, 8))
        tk.Label(
            card_frame,
            text=title,
            bg=self.card,
            fg=self.accent,
            font=(self.family, 9, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        return card_frame

    def _toggle(self, parent: tk.Widget, text: str, variable: tk.BooleanVar) -> tk.Checkbutton:
        cb = tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            bg=self.card,
            fg=self.ink,
            selectcolor=self.bg,
            activebackground=self.card,
            activeforeground=self.accent,
            highlightcolor=self.accent,
            highlightbackground=self.card,
            font=(self.family, 9),
            padx=0,
            pady=2,
        )
        cb.pack(anchor="w")
        return cb

    def _row(self, parent: tk.Widget, label_text: str) -> tk.Frame:
        line = tk.Frame(parent, bg=self.card)
        line.pack(fill="x", pady=3)
        tk.Label(
            line,
            text=label_text,
            bg=self.card,
            fg=self.ink,
            font=(self.family, 9),
        ).pack(side="left", padx=(0, 12))
        return line

    # ---------------- TAB 1: GENERAL ----------------
    def _build_general_tab(self, parent: tk.Frame):
        # Section 1: Refinement Default
        mode_box = self._section_box(parent, "Default Refinement Mode")
        m_row = self._row(mode_box, "Default Mode:")
        mode_combo = ttk.Combobox(
            m_row,
            textvariable=self.default_mode_var,
            values=self.mode_labels,
            state="readonly",
            width=32,
        )
        mode_combo.pack(side="right")
        tk.Label(
            mode_box,
            text="Primary mode triggered by standard shortcut (Ctrl+Win+Z).",
            bg=self.card,
            fg=self.secondary,
            font=(self.family, 8),
        ).pack(anchor="w", pady=(4, 0))

        # Section 2: Windows & Features
        general_box = self._section_box(parent, "Core Options & Windows Integration")
        self._toggle(general_box, "Enable Luna Grammar", self.enabled_var)
        self._toggle(general_box, "Run at Windows sign-in", self.startup_var)
        self._toggle(general_box, "Play a sound when a correction finishes", self.waveform_var)
        self._toggle(general_box, "Show word-level diff preview in overlay", self.diff_preview_var)
        self._toggle(general_box, "Show floating overlay feedback", self.feedback_var)
        self._toggle(general_box, "Expand chat shorthand (e.g. idk → I don't know)", self.shorthand_var)

        # Section 2b: Safety & Review
        safety_box = self._section_box(parent, "Safety & Review")
        self._toggle(safety_box, "Copy correction to clipboard instead of pasting", self.copy_only_var)
        self._toggle(safety_box, "Review each correction before applying (Apply / Discard)", self.review_var)
        self._toggle(safety_box, "Refuse a correction rather than lose clipboard formats", self.strict_clipboard_var)
        tk.Label(
            safety_box,
            text="Copy-only mode stages the correction for manual Ctrl+V — use it for fragile fields.",
            bg=self.card,
            fg=self.secondary,
            font=(self.family, 8),
        ).pack(anchor="w", pady=(4, 0))

        # Section 3: Appearance & Motion
        vis_box = self._section_box(parent, "Appearance & Motion")
        theme_row = self._row(vis_box, "Overlay Theme:")
        ttk.Combobox(
            theme_row,
            textvariable=self.appearance_var,
            values=("Dark", "Light"),
            state="readonly",
            width=18,
        ).pack(side="right")

        motion_row = self._row(vis_box, "Waveform Animation:")
        ttk.Combobox(
            motion_row,
            textvariable=self.motion_var,
            values=("Follow Windows", "Reduced"),
            state="readonly",
            width=18,
        ).pack(side="right")

    # ---------------- TAB 2: AI ENGINE ----------------
    def _build_ai_tab(self, parent: tk.Frame):
        # Section 1: Model & Temperature
        model_box = self._section_box(parent, "OpenAI Model & Inference")

        m_row = self._row(model_box, "Active Model:")
        model_models = ("gpt-6-luna", "gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo")
        self.model_combo = ttk.Combobox(
            m_row,
            textvariable=self.model_var,
            values=model_models,
            width=22,
        )
        self.model_combo.pack(side="right")

        if "LUNA_GRAMMAR_MODEL" in os.environ:
            self.model_combo.configure(state="disabled")
            tk.Label(
                model_box,
                text="Active model locked by environment variable: LUNA_GRAMMAR_MODEL",
                bg=self.card,
                fg=self.secondary,
                font=(self.family, 8),
            ).pack(anchor="w", pady=(2, 0))

        temp_row = self._row(model_box, "Temperature (0.0 - 2.0):")
        temp_entry = tk.Entry(
            temp_row,
            textvariable=self.temperature_var,
            width=8,
            bg=self.bg,
            fg=self.ink,
            insertbackground=self.ink,
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.border,
            justify="center",
            font=(self.family, 9),
        )
        temp_entry.pack(side="right", ipady=2)
        tk.Label(
            model_box,
            text="0.0 provides deterministic, exact refinement; higher values increase stylistic variety.",
            bg=self.card,
            fg=self.secondary,
            font=(self.family, 8),
        ).pack(anchor="w", pady=(2, 0))

        # Section 2: Custom Instructions
        custom_box = self._section_box(parent, "Custom Refinement Instructions")
        tk.Label(
            custom_box,
            text="Define specific personal writing rules (e.g. 'Use British spelling; avoid passive voice'):",
            bg=self.card,
            fg=self.secondary,
            font=(self.family, 8),
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(0, 4))

        self.custom_prompt_text = tk.Text(
            custom_box,
            height=3,
            bg=self.bg,
            fg=self.ink,
            insertbackground=self.ink,
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.border,
            font=(self.family, 9),
            wrap="word",
        )
        self.custom_prompt_text.pack(fill="x", pady=2)
        if self.settings.custom_prompt:
            self.custom_prompt_text.insert("1.0", self.settings.custom_prompt)

        # Section 3: API Key & Connection Test
        api_box = self._section_box(parent, "OpenAI API Authentication")
        key_row = self._row(api_box, "API Key:")

        self.key_entry = tk.Entry(
            key_row,
            textvariable=self.api_key_var,
            show="*",
            width=24,
            bg=self.bg,
            fg=self.ink,
            insertbackground=self.ink,
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.border,
            font=(self.family, 9),
        )
        self.key_entry.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=2)

        def toggle_key_mask():
            is_masked = self.key_masked.get()
            self.key_masked.set(not is_masked)
            self.key_entry.configure(show="*" if not is_masked else "")
            mask_btn.configure(text="Hide" if not is_masked else "Show")

        mask_btn = tk.Button(
            key_row,
            text="Show",
            command=toggle_key_mask,
            bg=self.card_secondary,
            fg=self.ink,
            relief="flat",
            bd=0,
            padx=8,
            pady=2,
            font=(self.family, 8),
            cursor="hand2",
        )
        mask_btn.pack(side="right")

        test_row = tk.Frame(api_box, bg=self.card)
        test_row.pack(fill="x", pady=(6, 0))

        self.conn_label = tk.Label(
            test_row,
            textvariable=self.connection_status_var,
            bg=self.card,
            fg=self.secondary,
            font=(self.family, 8),
            wraplength=320,
            justify="left",
        )
        self.conn_label.pack(side="left", fill="x", expand=True)

        self.test_btn = tk.Button(
            test_row,
            text="Test Connection",
            command=self.test_connection,
            bg=self.accent,
            fg=self.bg if self.dark else "#FFFFFF",
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            font=(self.family, 8, "bold"),
            cursor="hand2",
        )
        self.test_btn.pack(side="right")

    # ---------------- TAB 3: CACHE & DIAGNOSTICS ----------------
    def _build_cache_tab(self, parent: tk.Frame):
        # Section 1: Response Caching
        cache_box = self._section_box(parent, "Response Refinement Cache (<15ms Instant Refine)")
        self._toggle(cache_box, "Enable thread-safe in-memory LRU response cache", self.cache_enabled_var)

        tk.Label(
            cache_box,
            text="Identical selections refined in the same mode return instantly without API latency.",
            bg=self.card,
            fg=self.secondary,
            font=(self.family, 8),
        ).pack(anchor="w", pady=(0, 8))

        # Metrics Card Grid
        grid_frame = tk.Frame(cache_box, bg=self.card)
        grid_frame.pack(fill="x", pady=(0, 8))

        def metric_card(parent_frame, col, title, variable):
            box = tk.Frame(
                parent_frame,
                bg=self.card_secondary,
                padx=10,
                pady=6,
                highlightthickness=1,
                highlightbackground=self.border,
            )
            box.grid(row=0, column=col, padx=4, sticky="nsew")
            parent_frame.grid_columnconfigure(col, weight=1)
            tk.Label(box, text=title, bg=self.card_secondary, fg=self.secondary, font=(self.family, 8)).pack(anchor="center")
            tk.Label(box, textvariable=variable, bg=self.card_secondary, fg=self.accent, font=(self.family, 12, "bold")).pack(anchor="center")

        metric_card(grid_frame, 0, "Cache Hits", self.diag_hits_var)
        metric_card(grid_frame, 1, "Cache Misses", self.diag_misses_var)
        metric_card(grid_frame, 2, "Hit Ratio", self.diag_ratio_var)
        metric_card(grid_frame, 3, "Cache Size", self.diag_size_var)

        btn_row = tk.Frame(cache_box, bg=self.card)
        btn_row.pack(fill="x", pady=(4, 0))

        tk.Button(
            btn_row,
            text="Clear Response Cache",
            command=self.clear_cache,
            bg=self.danger,
            fg="#FFFFFF",
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            font=(self.family, 8, "bold"),
            cursor="hand2",
        ).pack(side="left")

        self.cache_clear_status = tk.Label(
            btn_row,
            textvariable=self.diag_status_var,
            bg=self.card,
            fg=self.secondary,
            font=(self.family, 8),
        )
        self.cache_clear_status.pack(side="left", padx=(10, 0))

        # Section 2: Live Memory & Diagnostics
        sys_box = self._section_box(parent, "Process Diagnostics & Resource Utilization")
        self._row_value(sys_box, "Working Set Memory:", self.diag_memory_var)
        self._row_value(sys_box, "Process ID (PID):", tk.StringVar(value=str(os.getpid())))
        self._row_value(sys_box, "Max Selection Chars:", tk.StringVar(value=f"{self.settings.max_selection_chars:,} chars"))
        self._row_value(sys_box, "Request Timeout:", tk.StringVar(value=f"{self.settings.timeout_seconds:.1f} s"))

        tk.Button(
            sys_box,
            text="Refresh Diagnostics",
            command=self.refresh_diagnostics,
            bg=self.card_secondary,
            fg=self.ink,
            relief="flat",
            bd=0,
            padx=10,
            pady=3,
            font=(self.family, 8),
            cursor="hand2",
        ).pack(anchor="w", pady=(6, 0))

    def _row_value(self, parent: tk.Widget, label_text: str, variable: tk.StringVar):
        line = tk.Frame(parent, bg=self.card)
        line.pack(fill="x", pady=2)
        tk.Label(line, text=label_text, bg=self.card, fg=self.ink, font=(self.family, 9)).pack(side="left")
        tk.Label(line, textvariable=variable, bg=self.card, fg=self.secondary, font=(self.family, 9, "bold")).pack(side="right")

    # ---------------- TAB 4: EXCLUSIONS ----------------
    def _build_exclusions_tab(self, parent: tk.Frame):
        desc_box = self._section_box(parent, "Excluded Target Applications")
        tk.Label(
            desc_box,
            text="Luna Grammar hotkeys will be automatically ignored when these applications are focused.\nUseful for password managers, games, and terminal sessions.",
            bg=self.card,
            fg=self.secondary,
            font=(self.family, 8),
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))

        # Listbox for excluded apps
        list_frame = tk.Frame(desc_box, bg=self.card)
        list_frame.pack(fill="both", expand=True, pady=(0, 6))

        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        self.exclusions_listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            bg=self.bg,
            fg=self.ink,
            selectbackground=self.accent,
            selectforeground=self.bg if self.dark else "#FFFFFF",
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.border,
            font=(self.family, 9),
            height=6,
        )
        scrollbar.config(command=self.exclusions_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.exclusions_listbox.pack(side="left", fill="both", expand=True)

        for app in self.settings.excluded_apps:
            self.exclusions_listbox.insert("end", app)

        # Add / Remove Controls
        input_row = tk.Frame(desc_box, bg=self.card)
        input_row.pack(fill="x", pady=(4, 0))

        self.new_app_var = tk.StringVar(value="")
        self.app_entry = tk.Entry(
            input_row,
            textvariable=self.new_app_var,
            width=22,
            bg=self.bg,
            fg=self.ink,
            insertbackground=self.ink,
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.border,
            font=(self.family, 9),
        )
        self.app_entry.pack(side="left", padx=(0, 6), ipady=3)
        self.app_entry.bind("<Return>", lambda _e: self.add_exclusion())

        tk.Button(
            input_row,
            text="+ Add Application",
            command=self.add_exclusion,
            bg=self.accent,
            fg=self.bg if self.dark else "#FFFFFF",
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            font=(self.family, 8, "bold"),
            cursor="hand2",
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            input_row,
            text="- Remove Selected",
            command=self.remove_exclusion,
            bg=self.card_secondary,
            fg=self.danger,
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            font=(self.family, 8),
            cursor="hand2",
        ).pack(side="left")

        self.exclusion_msg_var = tk.StringVar(value="Enter executable name (e.g. game.exe, keepass.exe)")
        tk.Label(
            desc_box,
            textvariable=self.exclusion_msg_var,
            bg=self.card,
            fg=self.secondary,
            font=(self.family, 8),
        ).pack(anchor="w", pady=(4, 0))

        # Per-app default mode: a bare Ctrl+Win+Z uses this mode in that app.
        per_app_box = self._section_box(parent, "Per-App Default Mode (bare Ctrl+Win+Z)")
        tk.Label(
            per_app_box,
            text="A bare Ctrl+Win+Z uses this mode in that app. An explicit digit (e.g. Ctrl+Win+2+Z) always wins.",
            bg=self.card,
            fg=self.secondary,
            font=(self.family, 8),
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))
        self.per_app_listbox = tk.Listbox(
            per_app_box,
            bg=self.bg,
            fg=self.ink,
            selectbackground=self.accent,
            selectforeground=self.bg if self.dark else "#FFFFFF",
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.border,
            font=(self.family, 9),
            height=4,
        )
        self.per_app_listbox.pack(fill="both", expand=True, pady=(0, 6))
        for exe, level in sorted(self.settings.per_app_modes.items()):
            if 0 <= level < len(self.mode_labels):
                self.per_app_listbox.insert("end", f"{exe} → {self.mode_labels[level]}")

        per_app_row = tk.Frame(per_app_box, bg=self.card)
        per_app_row.pack(fill="x", pady=(4, 0))
        self.new_per_app_var = tk.StringVar(value="")
        tk.Entry(
            per_app_row,
            textvariable=self.new_per_app_var,
            width=16,
            bg=self.bg,
            fg=self.ink,
            insertbackground=self.ink,
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.border,
            font=(self.family, 9),
        ).pack(side="left", padx=(0, 6), ipady=3)
        self.per_app_mode_var = tk.StringVar(value=self.mode_labels[0])
        ttk.Combobox(
            per_app_row,
            textvariable=self.per_app_mode_var,
            values=self.mode_labels,
            state="readonly",
            width=30,
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            per_app_row,
            text="+ Add",
            command=self.add_per_app_mode,
            bg=self.accent,
            fg=self.bg if self.dark else "#FFFFFF",
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            font=(self.family, 8, "bold"),
            cursor="hand2",
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            per_app_row,
            text="- Remove",
            command=self.remove_per_app_mode,
            bg=self.card_secondary,
            fg=self.danger,
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            font=(self.family, 8),
            cursor="hand2",
        ).pack(side="left")
        self.per_app_msg_var = tk.StringVar(value="Enter an app, pick its mode, then Add.")
        tk.Label(
            per_app_box,
            textvariable=self.per_app_msg_var,
            bg=self.card,
            fg=self.secondary,
            font=(self.family, 8),
        ).pack(anchor="w", pady=(4, 0))

    def add_per_app_mode(self):
        exe = self.new_per_app_var.get().strip().casefold()
        if not exe:
            self.per_app_msg_var.set("Please enter an executable name.")
            return
        if PureWindowsPath(exe).name != exe or not exe.endswith(".exe"):
            self.per_app_msg_var.set("Executable name must be like 'outlook.exe'.")
            return
        label = self.per_app_mode_var.get()
        row = f"{exe} → {label}"
        for i in range(self.per_app_listbox.size()):
            if self.per_app_listbox.get(i).split(" → ")[0] == exe:
                self.per_app_listbox.delete(i)
                self.per_app_listbox.insert(i, row)
                self.per_app_msg_var.set(f"Updated {exe}.")
                return
        self.per_app_listbox.insert("end", row)
        self.per_app_msg_var.set(f"Added {exe}.")

    def remove_per_app_mode(self):
        selected = self.per_app_listbox.curselection()
        if not selected:
            self.per_app_msg_var.set("Select a per-app mode to remove.")
            return
        self.per_app_listbox.delete(selected[0])
        self.per_app_msg_var.set("Removed.")

    def _per_app_modes_dict(self) -> dict:
        modes = {}
        for i in range(self.per_app_listbox.size()):
            row = self.per_app_listbox.get(i)
            exe, _, label = row.partition(" → ")
            for level, mode_label in enumerate(self.mode_labels):
                if label == mode_label:
                    modes[exe] = level
                    break
        return modes

    def add_exclusion(self):
        val = self.new_app_var.get().strip()
        if not val:
            self.exclusion_msg_var.set("Please enter an executable name.")
            return
        # Validation: must be executable filename
        if PureWindowsPath(val).name != val or not val.casefold().endswith(".exe"):
            self.exclusion_msg_var.set("Executable name must be like 'notepad.exe' or 'game.exe'.")
            return
        casefolded = val.casefold()
        existing = [self.exclusions_listbox.get(i).casefold() for i in range(self.exclusions_listbox.size())]
        if casefolded in existing:
            self.exclusion_msg_var.set(f"'{casefolded}' is already in exclusions.")
            return
        self.exclusions_listbox.insert("end", casefolded)
        self.new_app_var.set("")
        self.exclusion_msg_var.set(f"Added '{casefolded}'.")

    def remove_exclusion(self):
        selected = self.exclusions_listbox.curselection()
        if not selected:
            self.exclusion_msg_var.set("Select an application from the list to remove.")
            return
        for idx in reversed(selected):
            val = self.exclusions_listbox.get(idx)
            self.exclusions_listbox.delete(idx)
        self.exclusion_msg_var.set(f"Removed '{val}'.")

    # ---------------- TAB 5: SHORTCUTS & ABOUT ----------------
    def _build_about_tab(self, parent: tk.Frame):
        # Section 1: Hotkey Reference Table
        sc_box = self._section_box(parent, "Keyboard Shortcuts Cheatsheet")

        cheatsheet = [
            ("Ctrl + Win + Z", "Default Refinement", "Triggers default mode (configured in General tab)"),
            ("Ctrl + Win + 0 + Z", "Mode 0: Grammar & Spelling", "Minimal edits, fixes typos and punctuation"),
            ("Ctrl + Win + 1 + Z", "Mode 1: Casual Polish", "Natural, conversational flow and gentle clarity"),
            ("Ctrl + Win + 2 + Z", "Mode 2: Executive Concise", "Direct, professional, workplace-ready wording"),
            ("Ctrl + Win + 3 + Z", "Mode 3: Academic & Formal", "Elevated vocabulary and formal scholarly syntax"),
            ("Ctrl + Win + 4 + Z", "Mode 4: Bulletize & Summarize", "Transforms dense text into crisp, punchy bullets"),
            ("Ctrl + Win + 5 + Z", "Mode 5: Translate to English", "Translates any foreign text into natural English"),
            ("Ctrl + Win + U", "Instant Undo", "Reverts the last refinement back to original text"),
        ]

        table_frame = tk.Frame(sc_box, bg=self.card)
        table_frame.pack(fill="x", pady=2)

        for hotkey, title, desc in cheatsheet:
            row_f = tk.Frame(table_frame, bg=self.card)
            row_f.pack(fill="x", pady=2)
            tk.Label(
                row_f,
                text=hotkey,
                bg=self.card_secondary,
                fg=self.accent,
                font=(self.family, 8, "bold"),
                padx=6,
                pady=1,
                width=18,
                anchor="w",
            ).pack(side="left")
            col = tk.Frame(row_f, bg=self.card)
            col.pack(side="left", padx=(8, 0), fill="x", expand=True)
            tk.Label(
                col,
                text=title,
                bg=self.card,
                fg=self.ink,
                font=(self.family, 8, "bold"),
                anchor="w",
            ).pack(anchor="w")
            tk.Label(
                col,
                text=desc,
                bg=self.card,
                fg=self.secondary,
                font=(self.family, 7),
                anchor="w",
            ).pack(anchor="w")

        # Section 2: About
        about_box = self._section_box(parent, "About Luna Grammar")
        tk.Label(
            about_box,
            text="Luna Grammar 2.0 Pro · Ultra-Low Latency Desktop Assistant\n"
                 "High-performance Win32 layered overlay with GDI+ alpha blending,\n"
                 "in-memory LRU response caching (<15ms), and native clipboard preservation.",
            bg=self.card,
            fg=self.secondary,
            font=(self.family, 8),
            justify="left",
        ).pack(anchor="w")

    # ---------------- TAB SWITCHING ----------------
    def switch_tab(self, target_key: str):
        for key, frame in self.tab_frames.items():
            if key == target_key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

        for key, btn in self.tab_buttons.items():
            if key == target_key:
                btn.configure(
                    bg=self.card,
                    fg=self.accent,
                    font=(self.family, 9, "bold"),
                )
            else:
                btn.configure(
                    bg=self.bg,
                    fg=self.secondary,
                    font=(self.family, 9),
                )

        if target_key == "cache":
            self.refresh_diagnostics()

    # ---------------- CONNECTION TEST ----------------
    def test_connection(self):
        chosen_model = self.model_var.get().strip()
        entered_key = self.api_key_var.get().strip()
        if not chosen_model:
            self.connection_status_var.set("Please enter or select a model ID.")
            return
        try:
            entered_key = entered_key or api_key()
        except AppError:
            self.connection_status_var.set("Enter an OpenAI API key to test connection.")
            return

        self.connection_status_var.set("Checking model access with OpenAI…")
        self.test_btn.configure(state="disabled")

        results = SimpleQueue()

        def request():
            engine = None
            try:
                from grammar_engine import GrammarEngine
                temp_settings = replace(self.settings, active_model=chosen_model, model=chosen_model)
                engine = GrammarEngine(temp_settings, entered_key)
                engine.check_model()
                results.put(("ok", f"✓ Model access confirmed ({chosen_model})"))
            except AppError as error:
                results.put(("err", f"✗ {error.status}"))
            except Exception as exc:
                results.put(("err", f"✗ Connection failed: {exc}"))
            finally:
                if engine:
                    try:
                        engine.close()
                    except Exception:
                        pass

        def poll():
            try:
                status_type, msg = results.get_nowait()
                self.connection_status_var.set(msg)
                self.conn_label.configure(fg=self.accent if status_type == "ok" else self.danger)
                self.test_btn.configure(state="normal")
            except Empty:
                self.root.after(80, poll)

        Thread(target=request, daemon=True).start()
        poll()

    # ---------------- DIAGNOSTICS & CACHE ----------------
    def refresh_diagnostics(self):
        self.diag_memory_var.set(f"{get_process_memory_mb():.1f} MB")
        stats = query_cache_stats()
        hits = stats.get("hits", 0)
        misses = stats.get("misses", 0)
        total = hits + misses
        ratio = (hits / total * 100.0) if total > 0 else 0.0
        size = stats.get("size", 0)

        self.diag_hits_var.set(str(hits))
        self.diag_misses_var.set(str(misses))
        self.diag_ratio_var.set(f"{ratio:.1f}%")
        self.diag_size_var.set(f"{size} items")
        # Last failure (written by the listener process, metadata only —
        # never selected/corrected text): stage, app, field and reason.
        try:
            import diagnostics as _diagnostics
            last = _diagnostics.read_last_failure_file()
        except Exception:
            last = None
        if last:
            self.diag_status_var.set(
                f"Last failure: {last.get('stage', '-')}/{last.get('code', '-')} "
                f"in {last.get('app', '-')} — {last.get('status', '-')}")
        else:
            self.diag_status_var.set("Stats updated — no failures recorded")

    def clear_cache(self):
        success = execute_clear_cache()
        listener_cleared = False
        try:
            from windows_hotkey import clear_listener_cache
            listener_cleared = clear_listener_cache()
        except Exception:
            pass
        self.refresh_diagnostics()
        if success or listener_cleared:
            self.diag_status_var.set("✓ Cache cleared (listener cache cleared too)"
                                     if listener_cleared else "✓ Cache cleared (listener not running)")
        else:
            self.diag_status_var.set("Cache reset (0 items)")

    # ---------------- PERSISTENCE & SAVE ----------------
    def save(self):
        # 1. Parse Mode ID
        mode_str = self.default_mode_var.get()
        default_mode = 0
        for i, opt in enumerate(self.mode_labels):
            if mode_str == opt:
                default_mode = i
                break

        # 2. Parse Temperature
        try:
            temperature = float(self.temperature_var.get().strip())
            if not (0.0 <= temperature <= 2.0):
                raise ValueError()
        except ValueError:
            self.status_var.set("Temperature must be a number between 0.0 and 2.0.")
            return

        # 3. Model
        model_name = self.model_var.get().strip()
        if not model_name:
            self.status_var.set("Please provide a valid OpenAI model ID.")
            return

        # 4. Excluded apps
        excluded = [self.exclusions_listbox.get(i) for i in range(self.exclusions_listbox.size())]

        # 4b. Per-app default modes
        per_app_modes = self._per_app_modes_dict()

        # 5. Custom instructions
        custom_instructions = self.custom_prompt_text.get("1.0", "end-1c").strip()

        # Build changes dict
        changes = {
            "enabled": self.enabled_var.get(),
            "sound_enabled": self.waveform_var.get(),
            "feedback": self.feedback_var.get(),
            "expand_shorthand": self.shorthand_var.get(),
            "show_diff_preview": self.diff_preview_var.get(),
            "cache_enabled": self.cache_enabled_var.get(),
            "copy_only": self.copy_only_var.get(),
            "clipboard_strict_preservation": self.strict_clipboard_var.get(),
            "review_before_apply": self.review_var.get(),
            "default_mode": default_mode,
            "temperature": temperature,
            "custom_prompt": custom_instructions,
            "excluded_apps": excluded,
            "per_app_modes": per_app_modes,
            "appearance": self.appearance_var.get().lower(),
            "motion": "reduced" if self.motion_var.get() == "Reduced" else "system",
        }

        if "LUNA_GRAMMAR_MODEL" not in os.environ:
            changes["active_model"] = model_name
            changes["model"] = model_name

        try:
            entered_key = self.api_key_var.get().strip()
            if entered_key:
                store_api_key_dpapi(entered_key)
            if self.startup_var.get() and not startup_link().exists() and not user_has_startup_key():
                raise AppError("Save an API key before enabling startup.")
            # Save the settings FIRST: the old order ran the startup gate
            # before update_settings(), so a startup problem discarded every
            # other change as well. Now a startup failure only affects startup.
            update_settings(changes, SETTINGS_PATH)
            try:
                save_startup(self.startup_var.get())
            except AppError as error:
                self.status_var.set(f"Settings saved, but Windows startup could not be changed: {error}")
                self._reload()
                return
        except AppError as error:
            self.status_var.set(str(error))
            return
        except OSError:
            self.status_var.set("Windows could not save the API key or settings.")
            return
        except Exception:
            self.status_var.set("Settings saved, but Windows startup could not be changed.")
            self._reload()
            return

        self._reload()
        self.root.destroy()

    def _reload(self):
        try:
            from windows_hotkey import reload_listener
            reload_listener()
        except Exception:
            pass

    def _init_shortcuts(self):
        self.root.bind("<Escape>", lambda _e: self.root.destroy())
        self.root.bind("<Control-s>", lambda _e: self.save())
        self.root.bind("<Control-S>", lambda _e: self.save())


def show_settings() -> int:
    """Entry point for the Luna Settings configuration center."""
    from overlay import set_dpi_context

    set_dpi_context(-4)  # Per-monitor DPI aware v2.

    # Register Poppins fonts if available
    try:
        fonts = win.bind(win.gdi, "AddFontResourceExW", c.c_int, w.LPCWSTR, w.DWORD, w.LPVOID)
        for weight in ("Regular", "Medium"):
            fonts(str(FONT_DIR / f"Poppins-{weight}.ttf"), 0x10, None)
    except Exception:
        pass

    root = tk.Tk()
    root.title("Luna Grammar · Configuration Center")
    # DPI-aware size + centred on the primary display: fixed 540x600 was
    # relatively smaller (and its fixed wraplengths wrapped early) at
    # 150-200% scaling, and Tk otherwise cascades onto the primary monitor.
    try:
        scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
    except Exception:
        scale = 1.0
    width, height = round(540 * scale), round(600 * scale)
    root.geometry(f"{width}x{height}")
    root.minsize(round(500 * scale), round(560 * scale))
    try:
        root.update_idletasks()
        x = (root.winfo_screenwidth() - width) // 2
        y = (root.winfo_screenheight() - height) // 2
        root.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
    except Exception:
        pass
    try:
        root.iconbitmap(str(ASSETS / "luna.ico"))
    except Exception:
        pass

    dialog = SettingsDialog(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(show_settings())
