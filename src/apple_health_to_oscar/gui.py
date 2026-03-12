from __future__ import annotations

import queue
import re
import sys
import threading
import traceback
import weakref
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Union

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .app_paths import APP_DISPLAY_NAME, optional_asset_path, runtime_base_dir
from .engine import (
    DEFAULT_CLUSTER_GAP_HOURS,
    DEFAULT_GAP_POLICY,
    DEFAULT_GENERIC_ASLEEP_AS,
    DEFAULT_INCREMENTAL_OVERLAP_DAYS,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_START,
    DEFAULT_PREFIX,
    DEFAULT_TIMEZONE,
    ConversionConfig,
    ConversionResult,
    default_output_dir_for,
    run_conversion,
)
from .i18n import (
    SYSTEM_LANGUAGE,
    Translator,
    available_language_codes,
    detect_system_language,
    language_autonym,
    normalize_language_code,
)
from .options import OPTION_SPEC_BY_KEY, OptionSpec, default_option_values, option_specs_for_section
from .settings_store import SettingsStore
from .timezones import (
    SYSTEM_TIMEZONE,
    build_timezone_label,
    resolved_timezone_value,
    sorted_timezone_entries,
    system_timezone_label,
    timezone_search_blob,
)
from .version import get_display_version

WINDOW_SIZE = "1140x860"
BG_COLOR = "#eff4fb"
HERO_BG = "#163e72"
HERO_TEXT = "#ffffff"
MUTED_TEXT = "#5c6676"
CARD_BG = "#ffffff"
PROGRESS_IDLE = 0.0


@dataclass
class ChoiceBinding:
    key: str
    widget: ttk.Combobox
    display_var: tk.StringVar
    value_to_label: Dict[str, str]
    label_to_value: Dict[str, str]
    search_map: Dict[str, str]


class Tooltip:
    _instances: "weakref.WeakSet[Tooltip]" = weakref.WeakSet()

    def __init__(self, widget: tk.Widget, text: str, *, delay_ms: int = 450) -> None:
        self.widget = widget
        self.text = text.strip()
        self.delay_ms = delay_ms
        self.tip_window: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None
        Tooltip._instances.add(self)

        if not self.text:
            return

        widget.bind("<Enter>", self._schedule_show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<FocusOut>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")
        widget.bind("<Configure>", self._hide, add="+")

    @classmethod
    def hide_all(cls) -> None:
        for instance in list(cls._instances):
            instance._hide()

    def _schedule_show(self, _event: object = None) -> None:
        if self.tip_window is not None or not self.text:
            return
        self._cancel_scheduled_show()
        try:
            self._after_id = self.widget.after(self.delay_ms, self._show)
        except Exception:
            self._after_id = None

    def _cancel_scheduled_show(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self) -> None:
        self._after_id = None
        if self.tip_window is not None or not self.text:
            return
        if not self.widget.winfo_exists():
            return

        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 10
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        try:
            tw.wm_attributes("-topmost", True)
        except Exception:
            pass
        tw.wm_geometry(f"+{x}+{y}")
        tw.configure(background="#1e2530")
        label = tk.Label(
            tw,
            text=self.text,
            justify="left",
            background="#1e2530",
            foreground="#ffffff",
            relief="solid",
            borderwidth=1,
            padx=9,
            pady=7,
            wraplength=320,
        )
        label.pack()

    def _hide(self, _event: object = None) -> None:
        self._cancel_scheduled_show()
        if self.tip_window is not None:
            try:
                self.tip_window.destroy()
            except Exception:
                pass
            self.tip_window = None


class AutocompleteCombobox(ttk.Combobox):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._all_values: list[str] = []
        self._search_map: Dict[str, str] = {}
        self.bind("<KeyRelease>", self._on_key_release, add="+")
        self.bind("<Button-1>", self._show_all_values, add="+")

    def set_completion_items(self, values: list[str], search_map: Optional[Dict[str, str]] = None) -> None:
        self._all_values = list(values)
        self._search_map = dict(search_map or {value: value.casefold() for value in values})
        self.configure(values=self._all_values)

    def matching_values(self, query: str) -> list[str]:
        text = query.strip().casefold()
        if not text:
            return list(self._all_values)
        return [value for value in self._all_values if text in self._search_map.get(value, value.casefold())]

    def best_match(self, query: str) -> Optional[str]:
        matches = self.matching_values(query)
        return matches[0] if matches else None

    def _show_all_values(self, _event: object) -> None:
        self.configure(values=self._all_values)

    def _on_key_release(self, event: tk.Event[tk.Widget]) -> None:  # type: ignore[type-arg]
        if event.keysym in {
            "Up",
            "Down",
            "Left",
            "Right",
            "Return",
            "Tab",
            "Escape",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
            "Alt_L",
            "Alt_R",
            "Command",
        }:
            return
        current = self.get()
        matches = self.matching_values(current)
        self.configure(values=matches if matches else self._all_values)


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Widget, *, padding: int = 0) -> None:
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=BG_COLOR)
        self.v_scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.v_scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.v_scroll.grid(row=0, column=1, sticky="ns")

        self.content = ttk.Frame(self.canvas, padding=padding)
        self.content.columnconfigure(0, weight=0)
        self.content.columnconfigure(1, weight=1)
        self._window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")

        self.content.bind("<Configure>", self._on_content_configure, add="+")
        self.canvas.bind("<Configure>", self._on_canvas_configure, add="+")
        self.canvas.bind("<Enter>", self._bind_mousewheel, add="+")
        self.canvas.bind("<Leave>", self._unbind_mousewheel, add="+")

    def _on_content_configure(self, _event: object = None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event[tk.Widget]) -> None:  # type: ignore[type-arg]
        self.canvas.itemconfigure(self._window_id, width=event.width)

    def _bind_mousewheel(self, _event: object = None) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.canvas.bind_all("<Button-4>", self._on_mousewheel, add="+")
        self.canvas.bind_all("<Button-5>", self._on_mousewheel, add="+")

    def _unbind_mousewheel(self, _event: object = None) -> None:
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event: tk.Event[tk.Widget]) -> None:  # type: ignore[type-arg]
        if getattr(event, "num", None) == 4:
            self.canvas.yview_scroll(-1, "units")
            return
        if getattr(event, "num", None) == 5:
            self.canvas.yview_scroll(1, "units")
            return
        delta = int(-1 * (event.delta / 120)) if getattr(event, "delta", 0) else 0
        if delta:
            self.canvas.yview_scroll(delta, "units")



def _default_output_dir(base_dir: Path) -> Path:
    if getattr(sys, "frozen", False):
        return Path.home() / "Documents" / APP_DISPLAY_NAME / "output"
    return default_output_dir_for(base_dir)


class DreamPortApp(tk.Tk):
    def __init__(self, *, base_dir: Optional[Path] = None) -> None:
        super().__init__()
        self.base_dir = runtime_base_dir(base_dir)
        self.default_output_dir = _default_output_dir(self.base_dir)
        self.log_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.is_running = False
        self.settings_store = SettingsStore()
        self._saved_settings = self.settings_store.load()
        self._translator = Translator(str(self._saved_settings.get("ui_language", SYSTEM_LANGUAGE)))
        self.choice_bindings: Dict[str, ChoiceBinding] = {}
        self._preferences_window: Optional[tk.Toplevel] = None
        self._about_window: Optional[tk.Toplevel] = None
        self._root_container: Optional[ttk.Frame] = None
        self._header_icon_photo: Optional[tk.PhotoImage] = None
        self._settings_icon_photo: Optional[tk.PhotoImage] = None
        self._window_icon_photo: Optional[tk.PhotoImage] = None
        self._fonts: Dict[str, tkfont.Font] = {}
        self._log_lines: list[str] = []
        self._interactive_widgets: list[tk.Widget] = []
        self._last_applied_language = normalize_language_code(str(self._saved_settings.get("ui_language", SYSTEM_LANGUAGE)))

        self.timezone_entries = sorted_timezone_entries()
        self.timezone_label_map = {entry.value: build_timezone_label(entry) for entry in self.timezone_entries}
        self.timezone_search_map = {build_timezone_label(entry): timezone_search_blob(entry) for entry in self.timezone_entries}

        self.configure(bg=BG_COLOR)
        self.geometry(WINDOW_SIZE)
        self.minsize(1040, 760)

        self._build_fonts()
        self._build_variables()
        self._configure_styles()
        self._build_menu()
        self._build_ui()
        self._apply_window_icon()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_worker_queue)
        self._append_log(self.t("hint.app_ready"))

    def t(self, key: str, **kwargs: object) -> str:
        return self._translator.t(key, **kwargs)

    def _build_fonts(self) -> None:
        default_font = tkfont.nametofont("TkDefaultFont")
        heading_font = default_font.copy()
        heading_font.configure(size=max(11, default_font.cget("size") + 3), weight="bold")
        title_font = default_font.copy()
        title_font.configure(size=max(20, default_font.cget("size") + 8), weight="bold")
        subtitle_font = default_font.copy()
        subtitle_font.configure(size=max(10, default_font.cget("size") + 1))
        small_font = default_font.copy()
        small_font.configure(size=max(9, default_font.cget("size") - 1))
        percent_font = default_font.copy()
        percent_font.configure(size=max(11, default_font.cget("size") + 1), weight="bold")
        self._fonts = {
            "heading": heading_font,
            "title": title_font,
            "subtitle": subtitle_font,
            "small": small_font,
            "percent": percent_font,
        }

    def _build_variables(self) -> None:
        defaults = default_option_values()
        merged = {**defaults, **self._saved_settings}

        self.input_var = tk.StringVar(value="")
        self.output_var = tk.StringVar(value=str(self.default_output_dir))
        self.status_var = tk.StringVar(value=self.t("status.ready"))
        self.progress_var = tk.DoubleVar(value=PROGRESS_IDLE)
        self.progress_percent_var = tk.StringVar(value="0%")
        self.progress_detail_var = tk.StringVar(value=self.t("status.ready"))

        self.vars: Dict[str, tk.Variable] = {}
        for spec in option_specs_for_section("main") + option_specs_for_section("preferences_general") + option_specs_for_section("preferences_advanced"):
            value = merged.get(spec.key, spec.default)
            if spec.widget == "bool":
                self.vars[spec.key] = tk.BooleanVar(value=bool(value))
            else:
                self.vars[spec.key] = tk.StringVar(value=str(value))

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            if sys.platform != "darwin":
                style.theme_use("clam")
        except tk.TclError:
            pass
        try:
            style.configure("Card.TLabelframe", padding=14)
            style.configure("Card.TLabelframe.Label", font=self._fonts["heading"])
            style.configure("Subtle.TLabel", foreground=MUTED_TEXT)
            style.configure("Primary.TButton", padding=(16, 9))
            style.configure("Tool.TButton", padding=(8, 6))
            style.configure("Action.TButton", padding=(8, 6))
            style.configure("Dream.Horizontal.TProgressbar", troughcolor="#d9e3f2", thickness=14)
        except tk.TclError:
            pass

    def _register_interactive_widget(self, widget: tk.Widget) -> tk.Widget:
        self._interactive_widgets.append(widget)
        return widget

    def _bind_adaptive_wrap(self, label: Union[ttk.Label, tk.Label], parent: tk.Widget, *, padding: int = 48, min_width: int = 260) -> None:
        def update_wrap(_event: object = None) -> None:
            try:
                width = max(min_width, parent.winfo_width() - padding)
                label.configure(wraplength=width)
            except tk.TclError:
                return

        parent.bind("<Configure>", update_wrap, add="+")
        self.after_idle(update_wrap)

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        self.config(menu=menu)

        app_menu = tk.Menu(menu, tearoff=False)
        app_menu.add_command(label=self.t("menu.app.about"), command=self.open_about_window)
        app_menu.add_command(label=self.t("menu.app.preferences"), command=self.open_preferences_window)
        app_menu.add_separator()
        app_menu.add_command(label=self.t("menu.app.quit"), command=self._on_close, accelerator=self._shortcut_label("quit"))
        menu.add_cascade(label=self.t("menu.app"), menu=app_menu)

        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label=self.t("menu.file.open_input"), command=self._browse_input, accelerator=self._shortcut_label("open_input"))
        file_menu.add_command(label=self.t("menu.file.select_output"), command=self._browse_output, accelerator=self._shortcut_label("select_output"))
        file_menu.add_separator()
        file_menu.add_command(label=self.t("menu.file.convert"), command=self._start_conversion, accelerator=self._shortcut_label("convert"))
        file_menu.add_separator()
        file_menu.add_command(label=self.t("menu.file.quit"), command=self._on_close, accelerator=self._shortcut_label("quit"))
        menu.add_cascade(label=self.t("menu.file"), menu=file_menu)

        settings_menu = tk.Menu(menu, tearoff=False)
        settings_menu.add_command(label=self.t("menu.settings.preferences"), command=self.open_preferences_window, accelerator=self._shortcut_label("preferences"))
        menu.add_cascade(label=self.t("menu.settings"), menu=settings_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label=self.t("menu.help.supported_formats"), command=self.open_supported_formats)
        help_menu.add_command(label=self.t("menu.help.about"), command=self.open_about_window)
        menu.add_cascade(label=self.t("menu.help"), menu=help_menu)

    def _build_ui(self) -> None:
        if self._root_container is not None:
            self._root_container.destroy()
        self.choice_bindings.clear()
        self._interactive_widgets = []

        self.title(self.t("app.title"))
        root = ttk.Frame(self, padding=(18, 18, 18, 16))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=7)
        root.columnconfigure(1, weight=5)
        root.rowconfigure(2, weight=1)
        self._root_container = root

        header = tk.Frame(root, bg=HERO_BG, padx=22, pady=20)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        self._build_header(header)

        files_frame = ttk.LabelFrame(root, text=self.t("section.files"), style="Card.TLabelframe")
        files_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(14, 8))
        files_frame.columnconfigure(1, weight=1)
        self._build_files_panel(files_frame)

        conversion_frame = ttk.LabelFrame(root, text=self.t("section.quick"), style="Card.TLabelframe")
        conversion_frame.grid(row=1, column=1, sticky="nsew", padx=(10, 0), pady=(14, 8))
        conversion_frame.columnconfigure(1, weight=1)
        self._build_conversion_panel(conversion_frame)

        log_frame = ttk.LabelFrame(root, text=self.t("section.log"), style="Card.TLabelframe")
        log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        self._build_log_panel(log_frame)

        footer = ttk.Frame(root)
        footer.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=0)
        self._build_footer(footer)
        self._status_refresh_if_idle()

    def _resample_filter(self) -> object:
        return getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)

    def _load_scaled_asset(self, candidate_names: tuple[str, ...], *, size: int) -> Optional[tk.PhotoImage]:
        for candidate_name in candidate_names:
            image_path = optional_asset_path(candidate_name)
            if image_path is None:
                continue
            try:
                with Image.open(image_path) as image:
                    rendered = image.convert("RGBA").resize((size, size), self._resample_filter())
                    return ImageTk.PhotoImage(rendered)
            except Exception:
                continue
        return None

    def _dialog_parent(self) -> tk.Misc:
        if self._preferences_window is not None and self._preferences_window.winfo_exists():
            try:
                focus_widget = self.focus_get()
            except Exception:
                focus_widget = None
            if focus_widget is not None:
                try:
                    if str(focus_widget).startswith(str(self._preferences_window)):
                        return self._preferences_window
                except Exception:
                    pass
        return self

    def _restore_focus_after_dialog(self, target: Optional[tk.Misc] = None) -> None:
        focus_target = target or self

        def restore() -> None:
            self._release_stuck_interaction_state()
            try:
                focus_target.lift()
            except Exception:
                pass
            for method_name in ("focus_force", "focus_set"):
                method = getattr(focus_target, method_name, None)
                if callable(method):
                    try:
                        method()
                        break
                    except Exception:
                        continue

        self.after_idle(restore)
        self.after(60, restore)

    def _load_header_icon(self) -> Optional[tk.PhotoImage]:
        return self._load_scaled_asset(("icon_no_bg.png", "dreamport_header_icon.png", "oscar_icon_runtime.png", "oscar_icon.png"), size=96)

    def _load_settings_icon(self) -> Optional[tk.PhotoImage]:
        return self._load_scaled_asset(("settings.png",), size=26)

    def _build_header(self, parent: tk.Frame) -> None:
        self._header_icon_photo = self._load_header_icon()
        if self._header_icon_photo is not None:
            tk.Label(parent, image=self._header_icon_photo, bg=HERO_BG).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 18))

        title_label = tk.Label(parent, text=self.t("app.name"), bg=HERO_BG, fg=HERO_TEXT, font=self._fonts["title"])
        title_label.grid(row=0, column=1, sticky="sw")

        subtitle_label = tk.Label(
            parent,
            text=self.t("app.subtitle"),
            bg=HERO_BG,
            fg="#dbe7ff",
            font=self._fonts["subtitle"],
            justify="left",
            anchor="w",
        )
        subtitle_label.grid(row=1, column=1, sticky="nw", pady=(6, 0))
        self._bind_adaptive_wrap(subtitle_label, parent, padding=220, min_width=320)

        self._settings_icon_photo = self._load_settings_icon()
        if self._settings_icon_photo is not None:
            settings_widget = tk.Label(
                parent, image=self._settings_icon_photo, bg=HERO_BG,
                cursor="hand2", bd=0, relief="flat",
            )
        else:
            settings_widget = tk.Label(
                parent, text="⚙", bg=HERO_BG, fg=HERO_TEXT,
                cursor="hand2", font=self._fonts["heading"],
            )
        settings_widget.grid(row=0, column=2, rowspan=2, sticky="ne", padx=(18, 0))
        settings_widget.bind("<Button-1>", lambda _e: self.open_preferences_window())
        Tooltip(settings_widget, self.t("menu.app.preferences"))

    def _build_files_panel(self, parent: ttk.LabelFrame) -> None:
        self._add_row_label(parent, 0, self.t("label.input_file"))
        input_entry = ttk.Entry(parent, textvariable=self.input_var)
        input_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=8)
        browse_input = ttk.Button(parent, text=self.t("button.browse_file"), command=self._browse_input)
        browse_input.grid(row=0, column=2, pady=8)
        self._register_interactive_widget(input_entry)
        self._register_interactive_widget(browse_input)

        self._add_row_label(parent, 1, self.t("label.output_folder"))
        output_entry = ttk.Entry(parent, textvariable=self.output_var)
        output_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=8)
        browse_output = ttk.Button(parent, text=self.t("button.browse_folder"), command=self._browse_output)
        browse_output.grid(row=1, column=2, pady=8)
        self._register_interactive_widget(output_entry)
        self._register_interactive_widget(browse_output)

    def _build_conversion_panel(self, parent: ttk.LabelFrame) -> None:
        self._add_row_label(parent, 0, self.t("label.output_format"))
        format_widget = self._create_choice_widget(parent, key="output_format", searchable=False)
        format_widget.grid(row=0, column=1, sticky="ew", pady=8)
        self._register_interactive_widget(format_widget)

        self._add_row_label(parent, 1, self.t("label.timezone"))
        timezone_widget = self._create_choice_widget(parent, key="timezone", searchable=True)
        timezone_widget.grid(row=1, column=1, sticky="ew", pady=8)
        self._register_interactive_widget(timezone_widget)

    def _build_log_panel(self, parent: ttk.LabelFrame) -> None:
        top = ttk.Frame(parent)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top.columnconfigure(0, weight=1)
        intro = ttk.Label(top, text=self.t("hint.app_ready"), style="Subtle.TLabel", justify="left", anchor="w")
        intro.grid(row=0, column=0, sticky="ew")
        self._bind_adaptive_wrap(intro, top, padding=120, min_width=320)
        clear_button = ttk.Button(top, text=self.t("button.clear_log"), command=self._clear_log, style="Action.TButton")
        clear_button.grid(row=0, column=1, sticky="e")
        self._register_interactive_widget(clear_button)

        self.log_text = tk.Text(parent, wrap="word", height=18, state="disabled", relief="flat", borderwidth=0)
        self.log_text.grid(row=1, column=0, sticky="nsew")
        if self._log_lines:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", "".join(self._log_lines))
            self.log_text.configure(state="disabled")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _build_footer(self, parent: ttk.Frame) -> None:
        detail = ttk.Label(parent, textvariable=self.progress_detail_var, style="Subtle.TLabel", justify="left", anchor="w")
        detail.grid(row=0, column=0, sticky="ew")
        self._bind_adaptive_wrap(detail, parent, padding=170, min_width=280)
        percent = ttk.Label(parent, textvariable=self.progress_percent_var, font=self._fonts["percent"])
        percent.grid(row=0, column=1, sticky="e")

        self.progress = ttk.Progressbar(parent, style="Dream.Horizontal.TProgressbar", mode="determinate", maximum=100, variable=self.progress_var)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(6, 0), padx=(0, 12))
        self.run_button = ttk.Button(parent, text=self.t("button.convert"), style="Primary.TButton", command=self._start_conversion)
        self.run_button.grid(row=1, column=1, sticky="e")
        self._register_interactive_widget(self.run_button)

    def _add_row_label(self, parent: ttk.Widget, row: int, text: str) -> ttk.Label:
        label = ttk.Label(parent, text=text)
        label.grid(row=row, column=0, sticky="w", padx=(0, 12), pady=8)
        return label

    def _create_choice_widget(self, parent: ttk.Widget, *, key: str, searchable: bool) -> ttk.Combobox:
        spec = OPTION_SPEC_BY_KEY[key]
        internal_var = self.vars[key]
        if spec.widget == "timezone":
            auto_label = self.t("value.timezone.auto_current", timezone=system_timezone_label(fallback=DEFAULT_TIMEZONE))
            value_to_label = {SYSTEM_TIMEZONE: auto_label, **dict(self.timezone_label_map)}
            search_map = {auto_label: f"{auto_label} system auto timezone".casefold(), **dict(self.timezone_search_map)}
        elif spec.widget == "language":
            system_language = detect_system_language()
            value_to_label = {
                SYSTEM_LANGUAGE: self.t(
                    "value.language.auto_current",
                    language=language_autonym(system_language),
                )
            }
            for code in available_language_codes():
                value_to_label[code] = language_autonym(code)
            search_map = {label: f"{label} {value}".casefold() for value, label in value_to_label.items()}
        else:
            value_to_label = {choice.value: self.t(choice.label_key) for choice in spec.choices}
            search_map = {label: f"{label} {value}".casefold() for value, label in value_to_label.items()}

        current_value = str(internal_var.get())
        current_label = value_to_label.get(current_value, next(iter(value_to_label.values()), ""))
        display_var = tk.StringVar(value=current_label)
        if searchable:
            widget: ttk.Combobox = AutocompleteCombobox(parent, textvariable=display_var)
            widget.configure(state="normal")
            assert isinstance(widget, AutocompleteCombobox)
            widget.set_completion_items(list(value_to_label.values()), search_map)
            widget.bind("<FocusOut>", lambda _event, name=key: self._on_choice_committed(name), add="+")
        else:
            widget = ttk.Combobox(parent, textvariable=display_var, state="readonly", values=list(value_to_label.values()))
        widget.bind("<<ComboboxSelected>>", lambda _event, name=key: self._on_choice_committed(name), add="+")

        binding = ChoiceBinding(
            key=key,
            widget=widget,
            display_var=display_var,
            value_to_label=value_to_label,
            label_to_value={label: value for value, label in value_to_label.items()},
            search_map=search_map,
        )
        self.choice_bindings[key] = binding
        return widget

    def _on_choice_committed(self, key: str) -> None:
        Tooltip.hide_all()
        self._sync_choice_binding_to_internal(key)
        self.after_idle(self._release_stuck_interaction_state)

    def _sync_choice_binding_to_internal(self, key: str) -> None:
        binding = self.choice_bindings.get(key)
        if binding is None:
            return
        current_text = binding.display_var.get().strip()
        if current_text in binding.label_to_value:
            self.vars[key].set(binding.label_to_value[current_text])
            return
        if isinstance(binding.widget, AutocompleteCombobox):
            match = binding.widget.best_match(current_text)
            if match and match in binding.label_to_value:
                binding.display_var.set(match)
                self.vars[key].set(binding.label_to_value[match])
                return
        current_value = str(self.vars[key].get())
        fallback = binding.value_to_label.get(current_value)
        if fallback:
            binding.display_var.set(fallback)

    def _normalize_choice_bindings(self) -> None:
        for key in list(self.choice_bindings):
            self._sync_choice_binding_to_internal(key)

    def _refresh_choice_widgets(self) -> None:
        for key, binding in self.choice_bindings.items():
            current_value = str(self.vars[key].get())
            label = binding.value_to_label.get(current_value)
            if label:
                binding.display_var.set(label)
            values = list(binding.value_to_label.values())
            if isinstance(binding.widget, AutocompleteCombobox):
                binding.widget.set_completion_items(values, binding.search_map)
            else:
                binding.widget.configure(values=values)

    def _browse_input(self, _event: object = None) -> None:
        Tooltip.hide_all()
        parent = self._dialog_parent()
        try:
            file_path = filedialog.askopenfilename(
                parent=parent,
                title=self.t("dialog.choose_input"),
                filetypes=[
                    (self.t("dialog.filetypes.export"), ("*.xml", "*.zip")),
                    (self.t("dialog.filetypes.xml"), "*.xml"),
                    (self.t("dialog.filetypes.zip"), "*.zip"),
                    (self.t("dialog.filetypes.all"), "*.*"),
                ],
            )
        finally:
            self._restore_focus_after_dialog(parent)
        if not file_path:
            return
        self.input_var.set(file_path)
        current_output = self.output_var.get().strip()
        selected = Path(file_path)
        suggested_output = selected.parent / "output"
        if not current_output or Path(current_output) == self.default_output_dir:
            self.output_var.set(str(suggested_output))

    def _browse_output(self, _event: object = None) -> None:
        Tooltip.hide_all()
        parent = self._dialog_parent()
        try:
            folder_path = filedialog.askdirectory(parent=parent, title=self.t("dialog.choose_output"))
        finally:
            self._restore_focus_after_dialog(parent)
        if folder_path:
            self.output_var.set(folder_path)

    def _clear_log(self) -> None:
        self._log_lines.clear()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self._append_log(self.t("log.cleared"))

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self._log_lines.append(line)
        if not hasattr(self, "log_text"):
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _current_option_values(self) -> Dict[str, object]:
        self._normalize_choice_bindings()
        values: Dict[str, object] = {}
        for key, var in self.vars.items():
            values[key] = var.get()
        return values

    def _save_preferences(self) -> None:
        self.settings_store.save(self._current_option_values())

    def _build_config_from_form(self) -> ConversionConfig:
        input_path = self.input_var.get().strip()
        output_dir = self.output_var.get().strip()
        if not input_path:
            raise ValueError(self.t("dialog.error.missing_input"))
        if not output_dir:
            raise ValueError(self.t("dialog.error.missing_output"))

        suffix = Path(input_path).suffix.lower()
        if suffix not in {".xml", ".zip"}:
            raise ValueError(self.t("dialog.error.invalid_input"))

        return ConversionConfig(
            input_path=input_path,
            output_dir=output_dir,
            output_format=str(self.vars["output_format"].get()).strip() or "both",
            timezone=resolved_timezone_value(str(self.vars["timezone"].get()).strip(), fallback=DEFAULT_TIMEZONE),
            night_start=str(self.vars["night_start"].get()).strip() or DEFAULT_NIGHT_START.strftime("%H:%M"),
            night_end=str(self.vars["night_end"].get()).strip() or DEFAULT_NIGHT_END.strftime("%H:%M"),
            source_contains=(str(self.vars["source_contains"].get()).strip() or None),
            gap_policy=str(self.vars["gap_policy"].get()).strip() or DEFAULT_GAP_POLICY,
            generic_asleep_as=str(self.vars["generic_asleep_as"].get()).strip() or DEFAULT_GENERIC_ASLEEP_AS,
            cluster_gap_hours=float(str(self.vars["cluster_gap_hours"].get()).strip() or DEFAULT_CLUSTER_GAP_HOURS),
            incremental_overlap_days=int(str(self.vars["incremental_overlap_days"].get()).strip() or DEFAULT_INCREMENTAL_OVERLAP_DAYS),
            prefix=str(self.vars["prefix"].get()).strip() or DEFAULT_PREFIX,
            rebuild_all=bool(self.vars["rebuild_all"].get()),
        )

    def _set_interactive_state(self, enabled: bool) -> None:
        state = "!disabled" if enabled else "disabled"
        for widget in self._interactive_widgets:
            try:
                if enabled:
                    widget.state([state])  # type: ignore[attr-defined]
                else:
                    widget.state([state])  # type: ignore[attr-defined]
            except Exception:
                try:
                    widget.configure(state=("normal" if enabled else "disabled"))
                except Exception:
                    continue
        if hasattr(self, "run_button"):
            try:
                self.run_button.configure(state=("normal" if enabled else "disabled"))
            except Exception:
                pass

    def _set_progress(self, percent: float, *, detail: Optional[str] = None, force: bool = False) -> None:
        bounded = max(0.0, min(100.0, float(percent)))
        current = float(self.progress_var.get())
        if self.is_running and not force and bounded < current:
            bounded = current
        self.progress_var.set(bounded)
        self.progress_percent_var.set(f"{int(round(bounded))}%")
        if detail is not None:
            self.progress_detail_var.set(detail)

    def _status_refresh_if_idle(self) -> None:
        if not self.is_running:
            self.status_var.set(self.t("status.ready"))
            self.progress_detail_var.set(self.t("status.ready"))
            self._set_progress(PROGRESS_IDLE, force=True)

    def _set_running(self, running: bool) -> None:
        self.is_running = running
        self._set_interactive_state(not running)
        if running:
            self.status_var.set(self.t("status.running"))
            self._set_progress(2, detail=self.t("status.running"), force=True)
        else:
            self._release_stuck_interaction_state()

    def _progress_from_engine_message(self, message: str) -> tuple[Optional[float], Optional[str]]:
        stripped = message.strip()
        localized = self._localize_engine_message(stripped)

        static_progress = {
            "입력 파일 확인": 4,
            "출력 폴더 준비": 8,
            "기존 manifest 검사 중...": 12,
            "Apple Health XML 파싱 중...": 22,
            "파싱 완료": 44,
            "source 1차 필터링 중...": 48,
            "필터링 완료": 58,
            "세션 구성 중...": 68,
            "manifest 저장 완료": 97,
            "Apple Watch -> OSCAR 변환 요약": 98,
        }
        for prefix, percent in static_progress.items():
            if stripped == prefix or stripped.startswith(prefix):
                return float(percent), localized

        parse_progress = re.search(r"XML 파싱 진행: (\d+)% \((\d+)개 레코드 발견\)", stripped)
        if parse_progress:
            percent = float(parse_progress.group(1))
            return 22.0 + (percent / 100.0) * 22.0, localized

        session_done = re.search(r"세션 계산 완료: (\d+)개", stripped)
        if session_done:
            total = int(session_done.group(1))
            return (74.0 if total > 0 else 92.0), localized

        item_progress = re.match(r"\[(\d+)/(\d+)\] .+ 처리 완료$", stripped)
        if item_progress:
            index = int(item_progress.group(1))
            total = max(1, int(item_progress.group(2)))
            return 74.0 + (index / total) * 22.0, localized

        if stripped.startswith("-"):
            return 99.0, localized
        return None, localized

    def _start_conversion(self, _event: object = None) -> None:
        if self.is_running:
            return

        Tooltip.hide_all()
        try:
            config = self._build_config_from_form()
        except Exception as exc:
            messagebox.showerror(self.t("window.error.title"), str(exc), parent=self)
            return

        self._save_preferences()
        self._set_running(True)
        self._append_log(self.t("log.started"))

        def worker() -> None:
            try:
                result = run_conversion(config, base_dir=self.base_dir, logger=lambda msg: self.log_queue.put(("log", msg)))
                self.log_queue.put(("done", result))
            except Exception:
                self.log_queue.put(("error", traceback.format_exc()))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def _poll_worker_queue(self) -> None:
        while True:
            try:
                kind, payload = self.log_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                raw_message = str(payload)
                percent, detail = self._progress_from_engine_message(raw_message)
                if percent is not None or detail is not None:
                    self._set_progress(percent if percent is not None else float(self.progress_var.get()), detail=detail)
                self._append_log(self._localize_engine_message(raw_message))
            elif kind == "done":
                self._handle_success(payload)  # type: ignore[arg-type]
            elif kind == "error":
                self._handle_error(str(payload))

        self.after(100, self._poll_worker_queue)

    def _handle_success(self, result: ConversionResult) -> None:
        self._set_running(False)
        self.status_var.set(self.t("status.done"))
        self._set_progress(100, detail=self.t("status.done"), force=True)
        self._append_log(self.t("log.completed"))
        message = self.t(
            "dialog.success.body",
            sessions=result.stats.final_sessions,
            files_written=result.stats.files_written,
            files_reused=result.stats.files_reused,
            output_dir=result.output_dir,
        )
        messagebox.showinfo(self.t("window.success.title"), message, parent=self)

    def _handle_error(self, trace_text: str) -> None:
        self._set_running(False)
        self.status_var.set(self.t("status.error"))
        self.progress_detail_var.set(self.t("status.error"))
        self._append_log(self.t("log.error"))
        for line in trace_text.rstrip().splitlines():
            self._append_log(line)
        messagebox.showerror(self.t("window.error.title"), self.t("dialog.error.generic"), parent=self)

    def _release_stuck_interaction_state(self) -> None:
        Tooltip.hide_all()
        try:
            current = self.grab_current()
        except tk.TclError:
            current = None
        if current is not None:
            try:
                current.grab_release()
            except Exception:
                pass
        target = self._preferences_window if self._preferences_window and self._preferences_window.winfo_exists() else self
        try:
            target.lift()
        except Exception:
            pass
        for method_name in ("focus_force", "focus_set"):
            method = getattr(target, method_name, None)
            if callable(method):
                try:
                    method()
                    break
                except Exception:
                    continue

    def _has_language_change(self) -> bool:
        return normalize_language_code(str(self.vars["ui_language"].get())) != self._last_applied_language

    def _apply_preference_changes(self, *, close_window: bool) -> None:
        Tooltip.hide_all()
        self._save_preferences()
        language_changed = self._has_language_change()
        had_preferences = self._preferences_window is not None and self._preferences_window.winfo_exists()

        if close_window and had_preferences:
            self._preferences_window.destroy()
            self._preferences_window = None
            had_preferences = False

        if language_changed:
            self._last_applied_language = normalize_language_code(str(self.vars["ui_language"].get()))
            self._rebuild_ui(reopen_preferences=had_preferences)
        else:
            self._refresh_choice_widgets()
            self._release_stuck_interaction_state()

    def open_preferences_window(self) -> None:
        Tooltip.hide_all()
        if self._preferences_window is not None and self._preferences_window.winfo_exists():
            self._preferences_window.deiconify()
            self._preferences_window.lift()
            self._preferences_window.focus_set()
            return

        window = tk.Toplevel(self)
        self._preferences_window = window
        window.title(self.t("window.preferences.title"))
        window.geometry("820x660")
        window.minsize(720, 560)
        window.transient(self)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)

        intro = ttk.Label(window, text=self.t("dialog.preferences.intro"), style="Subtle.TLabel", justify="left", anchor="w")
        intro.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 8))
        self._bind_adaptive_wrap(intro, window, padding=48, min_width=360)

        notebook = ttk.Notebook(window)
        notebook.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 12))

        general_frame = ScrollableFrame(notebook, padding=16)
        advanced_frame = ScrollableFrame(notebook, padding=16)
        notebook.add(general_frame, text=self.t("section.preferences.general"))
        notebook.add(advanced_frame, text=self.t("section.preferences.advanced"))

        self._build_option_rows(general_frame.content, option_specs_for_section("preferences_general"))
        self._build_option_rows(advanced_frame.content, option_specs_for_section("preferences_advanced"))

        footer = ttk.Frame(window)
        footer.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 18))
        footer.columnconfigure(0, weight=1)
        ttk.Button(footer, text=self.t("button.restore_defaults"), command=self._restore_defaults).grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text=self.t("button.save"), command=self._save_and_apply_preferences).grid(row=0, column=1, sticky="e", padx=(0, 8))
        ttk.Button(footer, text=self.t("button.close"), command=self._close_preferences_window).grid(row=0, column=2, sticky="e")

        window.protocol("WM_DELETE_WINDOW", self._close_preferences_window)
        window.focus_set()

    def _build_option_rows(self, parent: ttk.Frame, specs: tuple[OptionSpec, ...]) -> None:
        row = 0
        for spec in specs:
            if spec.widget == "bool":
                widget = ttk.Checkbutton(parent, text=self.t(spec.label_key), variable=self.vars[spec.key])
                widget.grid(row=row, column=0, columnspan=2, sticky="w", pady=8)
            else:
                label = ttk.Label(parent, text=self.t(spec.label_key))
                label.grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=8)
                if spec.widget in {"choice", "timezone", "language"}:
                    widget = self._create_choice_widget(parent, key=spec.key, searchable=spec.widget == "timezone")
                    widget.grid(row=row, column=1, sticky="ew", pady=8)
                else:
                    widget = ttk.Entry(parent, textvariable=self.vars[spec.key])
                    widget.grid(row=row, column=1, sticky="ew", pady=8)

            description = ttk.Label(parent, text=self.t(spec.description_key), style="Subtle.TLabel", justify="left", anchor="w")
            description.grid(row=row + 1, column=1 if spec.widget != "bool" else 0, columnspan=1 if spec.widget != "bool" else 2, sticky="ew", pady=(0, 10))
            self._bind_adaptive_wrap(description, parent, padding=74 if spec.widget != "bool" else 40, min_width=280)
            row += 2

    def _save_and_apply_preferences(self) -> None:
        self._apply_preference_changes(close_window=False)

    def _close_preferences_window(self) -> None:
        self._apply_preference_changes(close_window=True)
        if self._preferences_window is not None and self._preferences_window.winfo_exists():
            self._preferences_window.destroy()
        self._preferences_window = None

    def _restore_defaults(self) -> None:
        if not messagebox.askyesno(self.t("dialog.restore_defaults.title"), self.t("dialog.restore_defaults.body"), parent=self._preferences_window or self):
            return
        defaults = default_option_values()
        for key, value in defaults.items():
            var = self.vars.get(key)
            if var is None:
                continue
            var.set(value)
        self._refresh_choice_widgets()
        self._apply_preference_changes(close_window=False)

    def _rebuild_ui(self, *, reopen_preferences: bool = False) -> None:
        self._translator.set_language(str(self.vars["ui_language"].get()))
        self._build_menu()
        self._build_ui()
        if self._about_window is not None and self._about_window.winfo_exists():
            self._about_window.destroy()
            self._about_window = None
        if self._preferences_window is not None and self._preferences_window.winfo_exists():
            self._preferences_window.destroy()
            self._preferences_window = None
        if reopen_preferences:
            self.after(60, self.open_preferences_window)
        self._release_stuck_interaction_state()

    def open_about_window(self) -> None:
        Tooltip.hide_all()
        if self._about_window is not None and self._about_window.winfo_exists():
            self._about_window.deiconify()
            self._about_window.lift()
            self._about_window.focus_set()
            return

        window = tk.Toplevel(self)
        self._about_window = window
        window.title(self.t("window.about.title"))
        window.geometry("620x470")
        window.minsize(520, 380)
        window.transient(self)
        window.columnconfigure(0, weight=1)

        wrapper = ttk.Frame(window, padding=18)
        wrapper.grid(row=0, column=0, sticky="nsew")
        wrapper.columnconfigure(0, weight=1)

        title = ttk.Label(wrapper, text=self.t("app.name"), font=self._fonts["title"])
        title.grid(row=0, column=0, sticky="w")
        version = ttk.Label(wrapper, text=f"{self.t('label.version')}: {get_display_version()}", style="Subtle.TLabel")
        version.grid(row=1, column=0, sticky="w", pady=(0, 12))

        sections = [
            ("section.about.summary", "dialog.about.summary"),
            ("section.about.supported_formats", "dialog.about.supported_formats"),
            ("section.about.credits", "dialog.about.credits"),
        ]
        row = 2
        for heading_key, body_key in sections:
            heading = ttk.Label(wrapper, text=self.t(heading_key), font=self._fonts["heading"])
            heading.grid(row=row, column=0, sticky="w")
            row += 1
            body = ttk.Label(wrapper, text=self.t(body_key), justify="left", anchor="w")
            body.grid(row=row, column=0, sticky="ew", pady=(4, 14))
            self._bind_adaptive_wrap(body, wrapper, padding=40, min_width=320)
            row += 1

        copyright_label = ttk.Label(wrapper, text=self.t("dialog.about.copyright"), style="Subtle.TLabel", justify="left", anchor="w")
        copyright_label.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        self._bind_adaptive_wrap(copyright_label, wrapper, padding=40, min_width=320)
        row += 1
        ttk.Button(wrapper, text=self.t("button.close"), command=self._close_about_window).grid(row=row, column=0, sticky="e")
        window.protocol("WM_DELETE_WINDOW", self._close_about_window)

    def _close_about_window(self) -> None:
        if self._about_window is not None and self._about_window.winfo_exists():
            self._about_window.destroy()
        self._about_window = None

    def open_supported_formats(self) -> None:
        Tooltip.hide_all()
        messagebox.showinfo(self.t("window.supported_formats.title"), self.t("dialog.supported_formats.body"), parent=self)

    def _apply_window_icon(self) -> None:
        ico_icon = optional_asset_path("oscar_icon.ico")
        runtime_png = optional_asset_path("oscar_icon_macos.png") if sys.platform == "darwin" else optional_asset_path("oscar_icon_runtime.png")
        if runtime_png is None:
            runtime_png = optional_asset_path("oscar_icon.png")

        if sys.platform == "darwin" and getattr(sys, "frozen", False):
            return

        if runtime_png is not None:
            try:
                photo = tk.PhotoImage(file=str(runtime_png))
                self.iconphoto(True, photo)
                self._window_icon_photo = photo
            except Exception:
                pass

        if sys.platform.startswith("win") and ico_icon is not None:
            try:
                self.iconbitmap(str(ico_icon))
            except Exception:
                pass

    def _shortcut_label(self, action: str) -> str:
        if sys.platform == "darwin":
            mapping = {
                "open_input": "⌘O",
                "select_output": "⌘⇧O",
                "convert": "⌘R",
                "preferences": "⌘,",
                "quit": "⌘Q",
            }
        else:
            mapping = {
                "open_input": "Ctrl+O",
                "select_output": "Ctrl+Shift+O",
                "convert": "Ctrl+R",
                "preferences": "Ctrl+,",
                "quit": "Ctrl+Q",
            }
        return mapping[action]

    def _bind_shortcuts(self) -> None:
        modifier = "Command" if sys.platform == "darwin" else "Control"
        self.bind_all(f"<{modifier}-o>", self._browse_input)
        self.bind_all(f"<{modifier}-Shift-O>", self._browse_output)
        self.bind_all(f"<{modifier}-r>", self._start_conversion)
        self.bind_all(f"<{modifier}-q>", lambda _event: self._on_close())
        self.bind_all(f"<{modifier}-comma>", lambda _event: self.open_preferences_window())

    def _on_close(self) -> None:
        self._save_preferences()
        self.destroy()

    def _localize_engine_message(self, message: str) -> str:
        stripped = message.strip()
        if stripped == "기존 manifest 검사 중...":
            return self.t("engine.inspect_manifest")
        if stripped == "Apple Health XML 파싱 중...":
            return self.t("engine.parse_xml")
        if stripped == "source 1차 필터링 중...":
            return self.t("engine.source_filter")
        if stripped == "세션 구성 중...":
            return self.t("engine.build_sessions")
        if stripped == "Apple Watch -> OSCAR 변환 요약":
            return self.t("engine.summary.title")
        if stripped == "- 버킷별로 실제 선택된 source family:":
            return self.t("engine.summary.chosen_sources")
        if stripped == "- 생성/평가한 세션:":
            return self.t("engine.summary.sessions")
        if set(stripped) == {"="}:
            return stripped

        prefix_map = {
            "입력 파일 확인: ": "engine.input_verified",
            "출력 폴더 준비: ": "engine.output_prepare",
            "manifest 저장 완료: ": "engine.manifest_saved",
            "- 입력 파일: ": "engine.summary.input",
            "- 출력 폴더: ": "engine.summary.output",
            "- manifest: ": "engine.summary.manifest",
            "- 1차 source 필터: ": "engine.summary.source_filter",
            "- 파싱된 수면 레코드 수: ": "engine.summary.parsed_count",
            "- 선택된 수면 레코드 수: ": "engine.summary.selected_count",
            "- provisional bucket 수: ": "engine.summary.bucket_count",
            "- 최종 세션 수: ": "engine.summary.final_sessions",
            "- 증분 컷오프: ": "engine.summary.incremental_cutoff",
            "- 새로 기록한 파일 수: ": "engine.summary.files_written",
            "- 재사용한 파일 수: ": "engine.summary.files_reused",
            "- 이동(migrate)한 파일 수: ": "engine.summary.files_migrated",
        }
        for prefix, key in prefix_map.items():
            if stripped.startswith(prefix):
                return self.t(key, value=stripped[len(prefix):], path=stripped[len(prefix):])

        parse_progress = re.search(r"XML 파싱 진행: (\d+)% \((\d+)개 레코드 발견\)", stripped)
        if parse_progress:
            return self.t("engine.parse_progress", percent=parse_progress.group(1), records=parse_progress.group(2))
        if stripped.startswith("파싱 완료: "):
            match = re.search(r"파싱 완료: (\d+)개", stripped)
            if match:
                return self.t("engine.parsed_count", count=match.group(1))
        if stripped.startswith("필터링 완료: "):
            match = re.search(r"필터링 완료: (\d+)개", stripped)
            if match:
                return self.t("engine.filtered_count", count=match.group(1))
        if stripped.startswith("세션 계산 완료: "):
            match = re.search(r"세션 계산 완료: (\d+)개", stripped)
            if match:
                return self.t("engine.session_count", count=match.group(1))
        if stripped.startswith("- 전체 재생성 모드: "):
            value = stripped.split(":", 1)[1].strip()
            if value == "예":
                value = "Yes" if self._translator.resolved_language != "ko" else "예"
            elif value == "아니오":
                value = "No" if self._translator.resolved_language != "ko" else "아니오"
            return self.t("engine.summary.rebuild_all", value=value)

        progress = re.match(r"\[(\d+)/(\d+)\] (.+) -> (.+) 처리 완료$", stripped)
        if progress:
            return self.t(
                "engine.progress_item",
                index=progress.group(1),
                total=progress.group(2),
                start=progress.group(3),
                stop=progress.group(4),
            )
        return message



def main(*, base_dir: Optional[Path] = None) -> int:
    app = DreamPortApp(base_dir=base_dir)
    app.mainloop()
    return 0
