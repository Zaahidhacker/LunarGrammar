"""On-demand, keyboard-accessible settings and model availability check."""

import ctypes as c
import os
import tkinter as tk
from ctypes import wintypes as w
from dataclasses import replace
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Thread
from tkinter import font as tkfont, ttk

import win32 as win
from config import AppError, SETTINGS_PATH, api_key, app_command, load_settings, update_settings
from grammar_engine import GrammarEngine
from pill_art import ASSETS, FONT_DIR, LIME


def startup_link() -> Path:
    return Path(os.environ["APPDATA"]) / (
        "Microsoft/Windows/Start Menu/Programs/Startup/Luna Grammar.lnk"
    )


def save_startup(enabled):
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


def user_has_startup_key():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as env:
            value, _ = winreg.QueryValueEx(env, "OPENAI_API_KEY")
            return isinstance(value, str) and bool(value.strip())
    except OSError:
        return False


def show_settings():
    from overlay import set_dpi_context
    from windows_hotkey import reload_listener

    set_dpi_context(-4)  # Per-monitor DPI aware v2.
    settings = load_settings(SETTINGS_PATH)
    fonts = win.bind(win.gdi, "AddFontResourceExW", c.c_int, w.LPCWSTR, w.DWORD, w.LPVOID)
    for weight in ("Regular", "Medium"):
        fonts(str(FONT_DIR / f"Poppins-{weight}.ttf"), 0x10, None)
    root = tk.Tk()
    root.title("Luna Grammar · Settings")
    root.resizable(False, False)
    root.iconbitmap(str(ASSETS / "luna.ico"))
    family = "Poppins" if "Poppins" in tkfont.families(root) else "Segoe UI"
    root.option_add("*Font", (family, 10))
    dark = settings.appearance == "dark"
    bg, card, border = ("#121414", "#1B1E1B", "#363B35") if dark else ("#F1F4EC", "#FFFFFF", "#C7CFC0")
    ink, secondary, accent = ("#F1F4EF", "#B8C0B5", LIME) if dark else ("#20261E", "#535E50", "#365716")
    root.configure(background=bg)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TCombobox", fieldbackground=card, background=card, foreground=ink,
                    arrowcolor=ink, bordercolor=border, selectbackground=card, selectforeground=ink)
    style.map("TCombobox", fieldbackground=[("readonly", card)],
              foreground=[("readonly", ink)], selectbackground=[("readonly", card)],
              selectforeground=[("readonly", ink)])

    body = tk.Frame(root, background=bg, padx=25, pady=19)
    body.pack(fill="both")
    tk.Label(body, text="LUNA GRAMMAR", bg=bg, fg=accent, font=(family, 10)).pack(anchor="w")
    tk.Label(body, text="Settings", bg=bg, fg=ink, font=(family, 22)).pack(anchor="w", pady=(1, 12))

    enabled = tk.BooleanVar(value=settings.enabled)
    startup = tk.BooleanVar(value=startup_link().exists())
    feedback = tk.BooleanVar(value=settings.feedback)
    shorthand = tk.BooleanVar(value=settings.expand_shorthand)
    model = tk.StringVar(value=settings.model)
    appearance = tk.StringVar(value=settings.appearance.title())
    motion = tk.StringVar(value="Follow Windows" if settings.motion == "system" else "Reduced")
    key_present = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    connection = tk.StringVar(value="API key available" if key_present else "API key missing")
    status = tk.StringVar(value="")

    def section(title):
        box = tk.Frame(body, background=card, padx=13, pady=8,
                       highlightthickness=1, highlightbackground=border)
        box.pack(fill="x", pady=(0, 7))
        tk.Label(box, text=title, bg=card, fg=accent, font=(family, 10)).pack(anchor="w", pady=(0, 3))
        return box

    def toggle(parent, text, variable):
        widget = tk.Checkbutton(parent, text=text, variable=variable, bg=card, fg=ink, selectcolor=bg,
                                activebackground=card, activeforeground=accent, highlightcolor=accent,
                                highlightbackground=card, padx=0)
        widget.pack(anchor="w")

    def button(parent, text, callback, primary=False):
        return tk.Button(parent, text=text, command=callback, bg=accent if primary else card,
                         fg=bg if primary else ink, activebackground=ink, activeforeground=bg,
                         relief="flat", highlightcolor=accent, highlightbackground=border,
                         padx=10, pady=4)

    def row(parent, title):
        line = tk.Frame(parent, bg=card)
        line.pack(fill="x", pady=2)
        tk.Label(line, text=title, bg=card, fg=ink).pack(side="left", padx=(0, 17))
        return line

    general = section("General")
    toggle(general, "Enable Luna Grammar", enabled)
    toggle(general, "Run at Windows sign-in", startup)
    toggle(general, "Show overlay feedback", feedback)

    ai = section("AI")
    model_row = row(ai, "Model")
    model_input = tk.Entry(model_row, textvariable=model, width=24, bg=bg, fg=ink,
                           insertbackground=ink, disabledbackground=bg, disabledforeground=secondary,
                           relief="flat", highlightthickness=1, highlightbackground=border)
    model_input.pack(side="right", ipady=3)
    override = "LUNA_GRAMMAR_MODEL" in os.environ
    if override:
        model_input.configure(state="disabled")
        tk.Label(ai, text="Model set by LUNA_GRAMMAR_MODEL", bg=card, fg=secondary).pack(anchor="w")
    toggle(ai, "Expand chat shorthand", shorthand)
    api_row = row(ai, "API")
    tk.Label(api_row, textvariable=connection, bg=card, fg=secondary, wraplength=235).pack(side="left")
    results = SimpleQueue()

    def check_connection():
        chosen = model.get().strip()
        if not chosen:
            connection.set("Enter a model ID")
            return
        connection.set("Checking model access…")
        check.configure(state="disabled")

        def request():
            engine = None
            try:
                engine = GrammarEngine(replace(settings, model=chosen), api_key())
                engine.check_model()
                results.put("Model access confirmed")
            except AppError as error:
                results.put(error.status if key_present else "API key missing")
            except Exception:
                results.put("Connection check failed")
            finally:
                if engine:
                    engine.close()

        def poll():
            try:
                connection.set(results.get_nowait())
                check.configure(state="normal")
            except Empty:
                root.after(80, poll)

        Thread(target=request, daemon=True).start()
        poll()

    check = button(api_row, "Check", check_connection)
    check.pack(side="right")

    visuals = section("Appearance")
    ttk.Combobox(row(visuals, "Overlay theme"), width=16, textvariable=appearance,
                 values=("Dark", "Light"), state="readonly").pack(side="right")
    ttk.Combobox(row(visuals, "Animation"), width=16, textvariable=motion,
                 values=("Follow Windows", "Reduced"), state="readonly").pack(side="right")
    shortcut = section("Shortcut")
    tk.Label(shortcut, text="Ctrl  +  Win  +  Z", bg=card, fg=ink).pack(anchor="w")

    def save():
        changes = {
            "enabled": enabled.get(), "feedback": feedback.get(), "expand_shorthand": shorthand.get(),
            "appearance": appearance.get().lower(), "motion": "reduced" if motion.get() == "Reduced" else "system",
        }
        if not override:
            changes["model"] = model.get().strip()
        try:
            if startup.get() and not startup_link().exists() and not user_has_startup_key():
                raise AppError("Save your key as a user environment variable before enabling startup.")
            update_settings(changes)
            save_startup(startup.get())
        except AppError as error:
            status.set(str(error))
            return
        except Exception:
            status.set("Settings saved, but Windows startup could not be changed.")
            reload_listener()
            return
        reload_listener()
        root.destroy()

    tk.Label(body, textvariable=status, bg=bg, fg=secondary, wraplength=345, justify="left").pack(anchor="w")
    footer = tk.Frame(body, bg=bg)
    footer.pack(fill="x", pady=(4, 0))
    button(footer, "Save", save, True).pack(side="right")
    button(footer, "Cancel", root.destroy).pack(side="right", padx=(0, 8))
    root.bind("<Escape>", lambda _event: root.destroy())
    root.mainloop()
    return 0
