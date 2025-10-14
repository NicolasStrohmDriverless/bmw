from __future__ import annotations
import time
import tkinter as tk
from tkinter import ttk, messagebox
import tkinter.font as tkfont

from PIL import Image, ImageTk, ImageColor

from config import (
    THN_RED,
    THN_WHITE,
    THN_BLACK,
    DARK_BG,
    DARK_FG,
    LOGO_PATH,
    CAN_BACKEND,
    CAN_CHANNEL,
    PCAN_STATUS_GREEN,
    PCAN_STATUS_GRAY,
    PCAN_STATUS_ORANGE,
)
from can_utils import open_bus

# Import pages (relative within ui package)
from .pages.main_menu import MainMenu, ensure_red_button_style
from .pages.brake import BrakePage
from .pages.gear import GearLeverPage
from .pages.test import TestPage
from .pages.trigger_finder import TriggerFinderPage


class THNApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # Window title and geometry
        try:
            self.title("TH Nürnberg – BMW Steuerung")
        except Exception:
            self.title("TH Nuernberg - BMW Steuerung")
        self.geometry("1024x600")
        self.minsize(780, 420)

        self.is_dark = False  # start in light mode
        self.style = ttk.Style()
        self._load_logo()
        # Ensure Red.TButton style exists early (used by theme toggle)
        try:
            ensure_red_button_style()
        except Exception:
            pass

        # Container for pages
        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True)

        # Header with logo and PCAN status dot
        header = ttk.Frame(self.container)
        header.pack(side="top", fill="x")
        self.header = header

        self._pcan_check_running = False
        self._pcan_last_status = "unknown"
        self.pcan_dot = tk.Canvas(header, width=14, height=14, highlightthickness=0, bg=THN_WHITE)
        self.pcan_dot_id = self.pcan_dot.create_oval(2, 2, 12, 12, fill=PCAN_STATUS_GRAY, outline="#666666")
        self.pcan_dot.pack(side="left", padx=(8, 4), pady=6)

        self.logo_label = ttk.Label(header, image=self.logo_img)
        self.logo_label.pack(side="left", padx=8, pady=6)

        self.title_label = ttk.Label(header, text="Steuerung BMW", font=("Segoe UI", 14, "bold"))
        self.title_label.pack(side="left", padx=8, pady=6)
        ttk.Separator(self.container, orient="horizontal").pack(fill="x")

        # Page area
        self.page_frame = ttk.Frame(self.container)
        self.page_frame.pack(fill="both", expand=True, padx=16, pady=(4, 16))

        # Footer with theme toggle and bus info
        footer = ttk.Frame(self.container)
        footer.pack(side="bottom", fill="x", pady=6)
        self.theme_btn = ttk.Button(footer, text="🌙/☀️", command=self.toggle_theme)
        self.theme_btn.pack(side="left", padx=8)
        self.bus_info = ttk.Label(footer, text=f"Bus: {CAN_BACKEND} / {CAN_CHANNEL}")
        self.bus_info.pack(side="right", padx=8)

        # Pages
        self.pages: dict[str, ttk.Frame] = {}
        for P in (MainMenu, GearLeverPage, BrakePage, TestPage, TriggerFinderPage):
            page = P(parent=self.page_frame, app=self)
            self.pages[P.__name__] = page
            page.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.show("MainMenu")
        self.apply_theme()
        # Schedule periodic PCAN status check
        self.after(200, self._schedule_pcan_check)

    # ---- Theme & Logo ----

    def _load_logo(self):
        self._logo_base = None
        self._logo_variants: dict[str, ImageTk.PhotoImage] = {}
        try:
            img = Image.open(LOGO_PATH).convert("RGBA")
            base_w = 160
            w_percent = (base_w / float(img.width))
            h_size = int((float(img.height) * float(w_percent)))
            img = img.resize((base_w, h_size), Image.LANCZOS)
            self._logo_base = img
        except Exception:
            self._logo_base = Image.new("RGBA", (160, 50), (0, 0, 0, 0))

        if self._logo_base is not None:
            self.logo_img = ImageTk.PhotoImage(self._logo_base)
        else:
            placeholder = Image.new("RGBA", (160, 50), (255, 255, 255, 0))
            self.logo_img = ImageTk.PhotoImage(placeholder)

    def _render_logo_with_bg(self, bg_color: str) -> None:
        if not getattr(self, "_logo_base", None):
            return

        key = bg_color.lower()
        if key in self._logo_variants:
            self.logo_img = self._logo_variants[key]
        else:
            try:
                r, g, b = ImageColor.getrgb(bg_color)
            except ValueError:
                return

            base = self._logo_base
            if base.mode != "RGBA":
                base = base.convert("RGBA")

            background = Image.new("RGBA", base.size, (r, g, b, 255))
            composed = Image.alpha_composite(background, base)
            photo = ImageTk.PhotoImage(composed)
            self._logo_variants[key] = photo
            self.logo_img = photo

        if hasattr(self, "logo_label"):
            self.logo_label.configure(image=self.logo_img)

    def show(self, name: str):
        self.pages[name].tkraise()

    def toggle_theme(self):
        self.is_dark = not self.is_dark
        self.apply_theme()

    def apply_theme(self):
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Brand + state colors
        red_norm = THN_RED
        red_hover = "#B42B2B"
        red_active = "#9E2626"
        focus_rgba = (201, 48, 48, 90)

        # Theme surfaces
        if self.is_dark:
            bg = DARK_BG
            fg = DARK_FG
            surface = "#1C1C1C"
            border = "#2A2A2A"
        else:
            bg = THN_WHITE
            fg = THN_BLACK
            surface = "#F6F6F6"
            border = "#E6E6E6"

        # Sizing & radii
        btn_h = 44
        btn_w = 220
        btn_radius = 12

        # Primary button fg/bg
        btn_fg = THN_WHITE

        self.configure(bg=bg)
        try:
            self.pcan_dot.configure(bg=bg)
        except Exception:
            pass
        self.style.configure("Header.TFrame", background=bg)
        logo_bg = THN_BLACK if self.is_dark else THN_WHITE
        self.style.configure("HeaderLogo.TLabel", background=logo_bg, foreground=fg)
        if hasattr(self, "header"):
            self.header.configure(style="Header.TFrame")
        if hasattr(self, "logo_label"):
            self.logo_label.configure(style="HeaderLogo.TLabel")
        self._render_logo_with_bg(logo_bg)
        for w in (self.container, self.page_frame):
            w.configure(style="Card.TFrame")

        # Frames / Labels
        self.style.configure("TFrame", background=bg)
        self.style.configure("Card.TFrame", background=surface, bordercolor=border)
        self.style.configure("TLabel", background=bg, foreground=fg)
        self.style.configure("Card.TLabel", background=surface, foreground=fg)
        self.style.configure("Title.TLabel", background=bg, foreground=fg, font=("Segoe UI", 14, "bold"))

        # Treeview
        self.style.configure(
            "Treeview",
            background=surface,
            fieldbackground=surface,
            foreground=fg,
            bordercolor=border,
            rowheight=28,
        )
        self.style.configure(
            "Treeview.Heading",
            background=surface,
            foreground=fg,
            bordercolor=border,
            font=("Segoe UI", 10, "bold"),
        )

        # Button base styles
        self.style.configure(
            "THNPrimary.TButton",
            foreground=btn_fg,
            padding=(16, 12),
            font=("Segoe UI", 11, "bold"),
            anchor="center",
            relief="flat",
            borderwidth=0,
        )
        self.style.map(
            "THNPrimary.TButton",
            foreground=[("disabled", "#999999"), ("!disabled", btn_fg)],
        )
        self.style.configure(
            "THNSecondary.TButton",
            foreground=fg,
            padding=(16, 12),
            font=("Segoe UI", 11, "bold"),
            anchor="center",
            relief="flat",
            borderwidth=0,
        )
        self.style.map(
            "THNSecondary.TButton",
            foreground=[("disabled", "#999999"), ("!disabled", fg)],
        )
        self.style.configure(
            "THNTertiary.TButton",
            foreground=red_norm,
            padding=(6, 6),
            font=("Segoe UI", 11, "bold"),
            anchor="center",
            relief="flat",
            borderwidth=0,
        )
        self.style.map(
            "THNTertiary.TButton",
            foreground=[("disabled", "#9E9E9E"), ("active", red_hover), ("pressed", red_active)],
        )

        # Painters for variants
        def paint_primary(b):
            self._decorate_button(
                b,
                red_norm,
                THN_WHITE,
                red_hover,
                red_active,
                btn_w,
                btn_h,
                btn_radius,
                focus_rgba,
                "THNPrimary.TButton",
            )

        def paint_secondary(b):
            # Align secondary with brand: make it red as well
            paint_primary(b)

        def paint_tertiary(b):
            # Align tertiary with brand: make it red as well
            paint_primary(b)

        # Expose painters
        self._paint_primary = paint_primary
        self._paint_secondary = paint_secondary
        self._paint_tertiary = paint_tertiary

        # Back-compat paint function (primary)
        def paint_button(b):
            paint_primary(b)

        # Title in THN red
        self.style.configure("Title.TLabel", background=bg, foreground=red_norm, font=("Segoe UI", 14, "bold"))
        self.title_label.configure(style="Title.TLabel")

        # Ensure footer theme toggle button uses Red.TButton style
        try:
            self.theme_btn.configure(style="Red.TButton")
        except Exception:
            pass

        card = surface
        for page in self.pages.values():
            # type: ignore[call-arg]
            page.apply_theme(bg, fg, card, paint_button)

    # ---- PCAN Status ----

    def _set_pcan_dot(self, status: str):
        if status == "connected":
            color = PCAN_STATUS_GREEN
        elif status == "disconnected":
            color = PCAN_STATUS_GRAY
        else:
            color = PCAN_STATUS_ORANGE
        try:
            self.pcan_dot.itemconfigure(self.pcan_dot_id, fill=color)
        except Exception:
            pass

    def _schedule_pcan_check(self):
        if not self._pcan_check_running:
            self._pcan_check_running = True
            self.after(0, self._check_pcan_status)
        self.after(1500, self._schedule_pcan_check)

    def _check_pcan_status(self):
        status = "error"
        try:
            if CAN_BACKEND.lower() != "pcan":
                status = "disconnected"
            else:
                try:
                    import can  # type: ignore
                    configs = None
                    try:
                        from can.interfaces import detect_available_configs  # type: ignore
                        try:
                            configs = list(detect_available_configs(interface="pcan"))  # type: ignore
                        except TypeError:
                            configs = list(detect_available_configs())  # type: ignore
                    except Exception:
                        try:
                            from can.util import detect_available_configs  # type: ignore
                            configs = list(detect_available_configs())  # type: ignore
                        except Exception:
                            configs = None

                    found = False
                    if configs is not None:
                        for c in configs:
                            try:
                                if str(c.get("interface", "")).lower() not in ("pcan", ""):
                                    continue
                            except Exception:
                                pass
                            chan = str(c.get("channel", ""))
                            if chan and chan.upper() == str(CAN_CHANNEL).upper():
                                found = True
                                break
                    if configs is not None:
                        status = "connected" if found else "disconnected"
                    else:
                        try:
                            bus = open_bus()
                            try:
                                bus.shutdown()
                            except Exception:
                                pass
                            status = "connected"
                        except Exception as e:
                            msg = str(e).lower()
                            if any(k in msg for k in [
                                "channel", "not found", "no such", "unavailable", "kein", "nicht"
                            ]):
                                status = "disconnected"
                            else:
                                status = "error"
                except Exception:
                    status = "error"
        except Exception:
            status = "error"

        self._set_pcan_dot(status)
        self._pcan_last_status = status
        self._pcan_check_running = False

    # ---- Rounded Buttons Helper ----

    def _decorate_button(
        self,
        b,
        bg_color: str,
        fg_color: str,
        hover_color: str | None = None,
        press_color: str | None = None,
        width_px: int | None = None,
        height_px: int = 44,
        radius_px: int = 12,
        focus_rgba: tuple[int, int, int, int] | None = None,
        style_name: str | None = None,
    ):
        try:
            if isinstance(b, ttk.Button):
                if style_name:
                    b.configure(style=style_name)
                b.configure(foreground=fg_color)
            self.after(
                10,
                lambda: self._apply_round_to_button(
                    b,
                    base_color=bg_color,
                    hover_color=hover_color or bg_color,
                    press_color=press_color or bg_color,
                    width_px=width_px,
                    height_px=height_px,
                    radius_px=radius_px,
                    focus_rgba=focus_rgba,
                ),
            )
        except Exception:
            try:
                if isinstance(b, tk.Button):
                    b.configure(
                        bg=bg_color,
                        fg=fg_color,
                        activebackground=(press_color or bg_color),
                        activeforeground=THN_WHITE,
                        relief="flat",
                        bd=0,
                        highlightthickness=3 if focus_rgba else 0,
                        font=("Segoe UI", 11, "bold"),
                    )
            except Exception:
                pass

    def _apply_round_to_button(
        self,
        b: tk.Widget,
        base_color: str,
        hover_color: str,
        press_color: str,
        width_px: int | None,
        height_px: int,
        radius_px: int,
        focus_rgba: tuple[int, int, int, int] | None,
    ):
        try:
            txt = b.cget("text")
        except Exception:
            return

        try:
            fnt = tkfont.nametofont(b.cget("font")) if b.cget("font") else tkfont.nametofont("TkDefaultFont")
        except Exception:
            fnt = tkfont.nametofont("TkDefaultFont")

        text_w = fnt.measure(txt or " ")
        w = width_px if width_px else max(160, text_w + 32)
        h = height_px
        r = radius_px

        col_norm = base_color
        col_hover = hover_color
        col_press = press_color

        def make(fill):
            return self._make_round_image(w, h, r, fill, focus_rgba=None)

        def make_focus(fill):
            return self._make_round_image(w, h, r, fill, focus_rgba=focus_rgba) if focus_rgba else make(fill)

        imgs = {
            "normal": make(col_norm),
            "hover": make(col_hover),
            "press": make(col_press),
            "focus_normal": make_focus(col_norm),
            "focus_hover": make_focus(col_hover),
            "focus_press": make_focus(col_press),
        }
        setattr(b, "_round_imgs", imgs)

        try:
            b.configure(image=imgs["normal"], compound="center")
        except Exception:
            return

        state = {"inside": False, "pressed": False, "focused": False}

        def pick():
            key = "press" if state["pressed"] else ("hover" if state["inside"] else "normal")
            if state["focused"]:
                key = f"focus_{key}"
            return imgs.get(key) or imgs["normal"]

        def redraw():
            try:
                b.configure(image=pick())  # type: ignore
            except Exception:
                pass

        def _on_enter(_e=None):
            state["inside"] = True
            redraw()

        def _on_leave(_e=None):
            state["inside"] = False
            redraw()

        def _on_press(_e=None):
            state["pressed"] = True
            redraw()

        def _on_release(_e=None):
            state["pressed"] = False
            redraw()

        def _on_focus_in(_e=None):
            state["focused"] = True
            redraw()

        def _on_focus_out(_e=None):
            state["focused"] = False
            redraw()

        try:
            b.bind("<Enter>", _on_enter, add=True)
            b.bind("<Leave>", _on_leave, add=True)
            b.bind("<ButtonPress-1>", _on_press, add=True)
            b.bind("<ButtonRelease-1>", _on_release, add=True)
            b.bind("<FocusIn>", _on_focus_in, add=True)
            b.bind("<FocusOut>", _on_focus_out, add=True)
        except Exception:
            pass

    @staticmethod
    def _make_round_image(
        width: int,
        height: int,
        radius: int,
        color: str,
        focus_rgba: tuple[int, int, int, int] | None = None,
    ):
        try:
            from PIL import Image, ImageDraw, ImageTk
        except Exception:
            return None
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([(0, 0), (width - 1, height - 1)], radius=radius, fill=color)
        if focus_rgba:
            inset = 2
            draw.rounded_rectangle(
                [(inset, inset), (width - 1 - inset, height - 1 - inset)],
                radius=max(1, radius - 2),
                outline=focus_rgba,
                width=3,
            )
        return ImageTk.PhotoImage(img)
