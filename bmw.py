import os
import time
import itertools
import threading
import ctypes
import queue
from typing import TYPE_CHECKING, Any
import tkinter as tk
from tkinter import ttk, messagebox
from collections import deque, Counter
from PIL import Image, ImageTk

# ---- Corporate Design Farben TH Nürnberg ----
THN_RED   = "#C93030"    # Rot (201,48,48)
THN_WHITE = "#FFFFFF"    # White
THN_BLACK = "#000000"    # Schwarz
THN_GRAY_DARK    = "#1A1A1A"
THN_GRAY_CARD    = "#262626"
THN_GRAY_BORDER  = "#4D4D4D"
THN_GRAY_MUTED   = "#B3B3B3"
THN_GRAY_LIGHT   = "#E6E6E6"
THN_GRAY_SURFACE = "#F2F2F2"

DARK_BG   = THN_BLACK
DARK_FG   = THN_WHITE

# Dein Logo-Pfad (Windows)
LOGO_PATH = r"C:\Users\Nico\Documents\BMW\logo.png"

# ---- CAN Setup (python-can) ----
CAN_BACKEND = os.getenv("CAN_BACKEND", "pcan")          # "pcan" oder "socketcan"
CAN_CHANNEL = os.getenv("CAN_CHANNEL", "PCAN_USBBUS1")  # pcan: PCAN_USBBUS1 / socketcan: can0
CAN_BITRATE = int(os.getenv("CAN_BITRATE", "500000"))

if TYPE_CHECKING:  # pragma: no cover - typing helper
    import can as can_types
else:  # pragma: no cover - typing helper
    can_types = None

CAN_AVAILABLE = True
try:
    import can  # python-can
except Exception:
    CAN_AVAILABLE = False
    can = None

if TYPE_CHECKING:
    CanMessageT = can_types.Message
    CanBusT = can_types.BusABC
else:
    CanMessageT = Any
    CanBusT = Any

UDS_PROFILES = {
    "Links (06F1/0643)": {"TX_ID": 0x06F1, "RX_ID": 0x0643, "EA_REQ": 0x43},
    "Rechts (06F2/0644)": {"TX_ID": 0x06F2, "RX_ID": 0x0644, "EA_REQ": 0x44},
}
UDS_PROFILE_ORDER = tuple(UDS_PROFILES.keys())
UDS_EA_RSP = 0xF1

def open_bus():
    if not CAN_AVAILABLE:
        raise RuntimeError("python-can ist nicht installiert.")
    backend = CAN_BACKEND.lower()
    if backend == "pcan":
        return can.Bus(interface="pcan", channel=CAN_CHANNEL, bitrate=CAN_BITRATE)
    elif backend == "socketcan":
        return can.Bus(interface="socketcan", channel=CAN_CHANNEL, bitrate=CAN_BITRATE)
    else:
        raise ValueError(f"Unbekannter CAN_BACKEND: {CAN_BACKEND}")

def fmt_bytes(by: bytes) -> str:
    return " ".join(f"{b:02X}" for b in by)

def print_tx(msg: CanMessageT) -> None:
    print(f"TX  ID=0x{msg.arbitration_id:03X}  DLC={msg.dlc}  Data={fmt_bytes(msg.data)}")

def print_rx(msg: CanMessageT) -> None:
    ts = getattr(msg, "timestamp", None)
    if ts is not None:
        print(f"RX  ID=0x{msg.arbitration_id:03X}  DLC={msg.dlc}  Data={fmt_bytes(msg.data)}  ts={ts:.6f}")
    else:
        print(f"RX  ID=0x{msg.arbitration_id:03X}  DLC={msg.dlc}  Data={fmt_bytes(msg.data)}")

def recv_drain(bus: CanBusT, max_duration: float = 0.2) -> None:
    """Liest bis zu max_duration Sekunden alle verfügbaren Frames und druckt sie."""
    end_t = time.time() + max_duration
    while time.time() < end_t:
        msg = bus.recv(timeout=0.01)
        if msg is None:
            continue
        try:
            print_rx(msg)
        except Exception:
            pass

def make_msg(can_id_hex: str, data_hex: str) -> CanMessageT:
    """Erzeugt ein Standard-CAN-Frame (11-bit) aus Hex-Strings."""
    arb_id = int(can_id_hex, 16)
    data = bytes.fromhex(data_hex)
    return can.Message(arbitration_id=arb_id, is_extended_id=False, data=data)

# ---- Sequenzen ----

# Werkstattmodus (deine geänderten 0x6F1-Frames, jeweils DLC=8), 100 ms Abstand
WORKSHOP_SEQUENCE = [
    ("6F1", "2902100300000000"),
    ("6F1", "29053101A8030200"),
]

# Betriebsmodus (deine Reihenfolge; dritter Frame aktuell 5 Bytes lang)
OPERATION_SEQUENCE = [
    ("1777", "29021003"),
    ("1777", "290322F150"),
    ("1777", "29042ED80F"),   # Falls 8 Bytes gewünscht, bitte vollständige Daten schicken
]

# Optional: frühere Release-Sequenz
RELEASE_SEQUENCE = [
    ("1777", "290322F150"),
    ("1577", "F10662F1500F1970"),
    ("1777", "29021003"),
    ("1577", "F1037F1078"),
    ("1577", "F1065003002801F4"),
    ("1777", "29042ED80F01"),
    ("1577", "F1037F2E22"),
    ("1777", "29053101A80302"),
    ("1577", "F1047101A803"),
]

# Ganghebel-Zustaende (Name, CAN-ID, Datenhex)
GEAR_LEVER_STATES = [
    ("Ruhestellung", "65E", "F10462D20000"),
    ("Tippen nach vorne", "65E", "F10462D20001"),
    ("Ueberdruecken nach vorne", "65E", "F10462D20002"),
    ("Tippen nach hinten", "65E", "F10462D20003"),
    ("Ueberdruecken nach hinten", "65E", "F10462D20004"),
    ("Parktaster ungedrueckt", "65E", "F1210000FFFFFFFF"),
    ("Parktaster gedrueckt", "65E", "F1210001FFFFFFFF"),
]

GEAR_LEVER_LOOKUP = {name: (can_id, data_hex) for name, can_id, data_hex in GEAR_LEVER_STATES}

GEAR_ACTIONS = {
    "rest": "Ruhestellung",
    "forward_tap": "Tippen nach vorne",
    "forward_hold": "Ueberdruecken nach vorne",
    "back_tap": "Tippen nach hinten",
    "back_hold": "Ueberdruecken nach hinten",
    "park_press": "Parktaster gedrueckt",
    "park_release": "Parktaster ungedrueckt",
}

def send_sequence(seq, delay_s=0.02, rx_window_s=0.2):
    """
    Sendet eine Liste (id_hex, data_hex) mit Delay zwischen Frames.
    Nach jedem TX wird rx_window_s lang empfangen und alles geloggt.
    """
    try:
        bus = open_bus()
    except Exception as e:
        messagebox.showerror("CAN Fehler", f"Bus konnte nicht geöffnet werden:\n{e}")
        return False

    try:
        for can_id, data_hex in seq:
            msg = make_msg(can_id, data_hex)
            bus.send(msg)
            try:
                print_tx(msg)
            except Exception:
                pass
            recv_drain(bus, max_duration=rx_window_s)
            time.sleep(delay_s)
        return True
    except Exception as e:
        messagebox.showerror("CAN Fehler", f"Senden fehlgeschlagen:\n{e}")
        return False
    finally:
        try:
            bus.shutdown()
        except Exception:
            pass

# ---------- Test-Seite: 8 Byte-Felder mit Wildcards (leer = alle 00..FF) ----------

def normalize_hex_byte(val: str) -> str | None:
    """
    Nimmt Eingabe eines Byte-Feldes:
      - ""      => None (Wildcard)
      - "?" / "??" => None (Wildcard)
      - "A"     => "0A"
      - "0A"    => "0A"
      - "GG"    => ValueError
    Gibt "00".."FF" zurück oder None für Wildcard.
    """
    s = val.strip().upper().replace("0X", "")
    if s == "" or s == "?" or s == "??":
        return None
    if len(s) == 1:
        s = "0" + s
    if len(s) != 2:
        raise ValueError("Byte muss 1–2 Hex-Zeichen sein (z. B. A oder 0A).")
    # Validate hex
    int(s, 16)
    return s

def tokens_from_boxes(byte_values: list[str]) -> tuple[list[str | None], int]:
    """
    Erzeugt eine Liste von 8 Tokens (Hex-String '00'..'FF' oder None für Wildcard).
    Gibt auch die Gesamtzahl der Varianten zurück.
    """
    tokens: list[str | None] = []
    total = 1
    for v in byte_values:
        t = normalize_hex_byte(v)
        tokens.append(t)
        if t is None:
            total *= 256
    return tokens, total

# ---- GUI ----
class THNApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('BMW Control Hub')
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        default_w, default_h = 1080, 640

        if screen_w and screen_w < default_w:
            width = max(screen_w - 20, 480)
        else:
            width = default_w

        if screen_h and screen_h < default_h:
            height = max(screen_h - 60, 400)
        else:
            height = default_h

        self.geometry(f'{int(width)}x{int(height)}')
        min_w = max(420, min(720, width))
        min_h = max(360, min(520, height))
        self.minsize(int(min_w), int(min_h))
        self.after(0, self._maximize_window)

        self.is_dark = False
        self.style = ttk.Style()
        self._load_logo()

        self.font_title = ('Segoe UI', 22, 'bold')
        self.font_subtitle = ('Segoe UI', 11, 'bold')
        self.font_body = ('Segoe UI', 11)

        self.container = ttk.Frame(self, style='App.TFrame')
        self.container.pack(fill='both', expand=True)

        self.header = ttk.Frame(self.container, padding=(24, 18), style='Header.TFrame')
        self.header.pack(side='top', fill='x')

        self.logo_label = ttk.Label(self.header, image=self.logo_img, style='Header.TLabel')
        self.logo_label.pack(side='left', padx=(0, 18))

        header_text = ttk.Frame(self.header, style='Header.TFrame')
        header_text.pack(side='left', fill='y')

        self.title_label = ttk.Label(header_text, text='BMW Control Hub', style='HeaderTitle.TLabel')
        self.title_label.pack(anchor='w')

        self.subtitle_label = ttk.Label(
            header_text,
            text='Service • Diagnose • Simulation',
            style='HeaderSub.TLabel',
        )
        self.subtitle_label.pack(anchor='w', pady=(4, 0))

        self.theme_btn = tk.Button(self.header, text='🌙 Dark Mode', command=self.toggle_theme, cursor='hand2')
        self.theme_btn.pack(side='right')

        self.page_frame = ttk.Frame(self.container, padding=(24, 24), style='App.TFrame')
        self.page_frame.pack(fill='both', expand=True)

        self.footer = ttk.Frame(self.container, padding=(24, 12), style='Footer.TFrame')
        self.footer.pack(side='bottom', fill='x')
        self.footer_label = ttk.Label(
            self.footer,
            text='BMW Diagnose Suite • python-can',
            style='Footer.TLabel',
        )
        self.footer_label.pack(side='left')

        self.pages: dict[str, ttk.Frame] = {}
        for P in (MainMenu, GearLeverPage, UdsTablePage, BrakePage, TestPage):
            page = P(parent=self.page_frame, app=self)
            self.pages[P.__name__] = page
            page.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.show('MainMenu')
        self.apply_theme()

    def _load_logo(self):
        try:
            img = Image.open(LOGO_PATH).convert('RGBA')
            base_w = 160
            w_percent = (base_w / float(img.width))
            h_size = int((float(img.height) * float(w_percent)))
            img = img.resize((base_w, h_size), Image.LANCZOS)
            self.logo_img = ImageTk.PhotoImage(img)
        except Exception:
            fallback = Image.new('RGB', (180, 54), (201, 48, 48))
            self.logo_img = ImageTk.PhotoImage(fallback)

    def show(self, name):
        self.pages[name].tkraise()

    def toggle_theme(self):
        self.is_dark = not self.is_dark
        self.apply_theme()

    def apply_theme(self):
        if self.is_dark:
            bg = THN_GRAY_DARK
            panel = THN_GRAY_CARD
            card = THN_GRAY_CARD
            surface = THN_GRAY_BORDER
            border = THN_GRAY_MUTED
            fg = THN_WHITE
            muted = THN_GRAY_MUTED
        else:
            bg = THN_GRAY_SURFACE
            panel = THN_GRAY_LIGHT
            card = THN_WHITE
            surface = THN_GRAY_LIGHT
            border = THN_GRAY_MUTED
            fg = THN_BLACK
            muted = THN_GRAY_BORDER

        primary = THN_RED
        primary_hover = THN_BLACK
        primary_active = THN_WHITE
        accent = THN_RED

        palette = {
            'bg': bg,
            'card': card,
            'panel': panel,
            'surface': surface,
            'border': border,
            'fg': fg,
            'muted': muted,
            'primary': primary,
            'primary_hover': primary_hover,
            'primary_active': primary_active,
            'accent': accent,
        }
        self.palette = palette

        self.configure(bg=bg)
        self.style.configure('App.TFrame', background=bg)
        self.style.configure('Header.TFrame', background=panel)
        self.style.configure('Footer.TFrame', background=panel)
        self.style.configure('Header.TLabel', background=panel, foreground=fg)
        self.style.configure('HeaderTitle.TLabel', background=panel, foreground=fg, font=self.font_title)
        self.style.configure('HeaderSub.TLabel', background=panel, foreground=muted, font=self.font_subtitle)
        self.style.configure('Footer.TLabel', background=panel, foreground=muted, font=self.font_body)
        self.style.configure('Hero.TFrame', background=palette['surface'])
        self.style.configure('HeroBadge.TLabel', background=palette['surface'], foreground=accent, font=('Segoe UI', 10, 'bold'))
        self.style.configure('HeroTitle.TLabel', background=palette['surface'], foreground=fg, font=('Segoe UI', 20, 'bold'))
        self.style.configure('HeroSub.TLabel', background=palette['surface'], foreground=muted, font=self.font_body)
        self.style.configure('Card.TFrame', background=card)
        self.style.configure('Card.TLabel', background=card, foreground=fg, font=self.font_body)
        self.style.configure('CardTitle.TLabel', background=card, foreground=fg, font=('Segoe UI', 15, 'bold'))
        self.style.configure('Muted.TLabel', background=card, foreground=muted, font=self.font_body)

        def paint_primary(button: tk.Button) -> None:
            button.configure(
                bg=primary,
                fg=THN_WHITE,
                activebackground=primary_hover,
                activeforeground=THN_WHITE,
                relief='flat',
                bd=0,
                highlightthickness=0,
                font=('Segoe UI', 12, 'bold'),
                padx=18,
                pady=10,
                cursor='hand2',
            )

        def paint_secondary(button: tk.Button) -> None:
            button.configure(
                bg=card,
                fg=fg,
                activebackground=primary,
                activeforeground=THN_WHITE,
                relief='flat',
                bd=1,
                highlightthickness=1,
                highlightcolor=border,
                highlightbackground=border,
                font=('Segoe UI', 11, 'bold'),
                padx=16,
                pady=9,
                cursor='hand2',
            )

        def paint_ghost(button: tk.Button) -> None:
            button.configure(
                bg=panel,
                fg=fg,
                activebackground=primary,
                activeforeground=THN_WHITE,
                relief='flat',
                bd=0,
                highlightthickness=0,
                font=('Segoe UI', 11, 'bold'),
                padx=16,
                pady=8,
                cursor='hand2',
            )

        self.paint_primary = paint_primary
        self.paint_secondary = paint_secondary
        self.paint_ghost = paint_ghost

        self.header.configure(style='Header.TFrame')
        self.footer.configure(style='Footer.TFrame')
        self.page_frame.configure(style='App.TFrame')
        self.container.configure(style='App.TFrame')

        self.logo_label.configure(style='Header.TLabel')
        self.title_label.configure(style='HeaderTitle.TLabel')
        self.subtitle_label.configure(style='HeaderSub.TLabel')
        self.footer_label.configure(style='Footer.TLabel')

        toggle_text = '🌙 Dark Mode' if not self.is_dark else '☀ Light Mode'
        self.theme_btn.configure(text=toggle_text)
        paint_ghost(self.theme_btn)

        for page in self.pages.values():
            try:
                page.apply_theme(palette, paint_primary)
            except TypeError:
                page.apply_theme(palette['bg'], palette['fg'], palette['card'], paint_primary)

    def _maximize_window(self):
        try:
            self.state('zoomed')
        except Exception:
            try:
                self.attributes('-zoomed', True)
            except Exception:
                try:
                    self.attributes('-fullscreen', True)
                except Exception:
                    pass

class MainMenu(ttk.Frame):
    def __init__(self, parent, app: THNApp):
        super().__init__(parent, style='App.TFrame')
        self.app = app

        self.wrapper = ttk.Frame(self, style='App.TFrame')
        self.wrapper.pack(expand=True, fill='both')

        self.hero = ttk.Frame(self.wrapper, style='Hero.TFrame', padding=(24, 20))
        self.hero.pack(fill='x')
        self.hero_badge = ttk.Label(self.hero, text='Dashboard', style='HeroBadge.TLabel')
        self.hero_badge.pack(anchor='w')
        self.hero_title = ttk.Label(self.hero, text='Willkommen zurück!', style='HeroTitle.TLabel')
        self.hero_title.pack(anchor='w', pady=(8, 4))
        self.hero_subtitle = ttk.Label(
            self.hero,
            text='Wähle ein Modul, um Simulationen oder Analysen zu starten.',
            style='HeroSub.TLabel',
            wraplength=520,
            justify='left',
        )
        self.hero_subtitle.pack(anchor='w')

        self.card_grid = ttk.Frame(self.wrapper, style='App.TFrame')
        self.card_grid.pack(expand=True, fill='both', pady=(24, 0))

        self.card_frames: list[ttk.Frame] = []
        self.card_titles: list[ttk.Label] = []
        self.card_desc: list[ttk.Label] = []
        self.card_buttons: list[tk.Button] = []

        cards = [
            {
                'title': 'Feststellbremse',
                'desc': 'Schalte zwischen Werkstatt- und Betriebsmodus und sende die Sequenzen.',
                'command': lambda: app.show('BrakePage'),
            },
            {
                'title': 'Ganghebel',
                'desc': 'Simuliere Tippen, Überdrücken oder Parkmodus direkt über den CAN-Bus.',
                'command': lambda: app.show('GearLeverPage'),
            },
            {
                'title': 'LED Analyse',
                'desc': 'Lese Ströme und Prozentwerte beider Scheinwerfer inklusive AHL und LWR.',
                'command': lambda: app.show('UdsTablePage'),
            },
            {
                'title': 'Testlabor',
                'desc': 'Sende manuelle Frames mit Wildcards und analysiere Rückmeldungen live.',
                'command': lambda: app.show('TestPage'),
            },
        ]

        for idx, info in enumerate(cards):
            frame = ttk.Frame(self.card_grid, style='Card.TFrame', padding=(20, 18))
            row, col = divmod(idx, 2)
            frame.grid(row=row, column=col, padx=12, pady=12, sticky='nsew')
            self.card_grid.grid_columnconfigure(col, weight=1)
            self.card_grid.grid_rowconfigure(row, weight=1)

            title = ttk.Label(frame, text=info['title'], style='CardTitle.TLabel')
            title.pack(anchor='w')

            desc = ttk.Label(
                frame,
                text=info['desc'],
                style='Muted.TLabel',
                wraplength=260,
                justify='left',
            )
            desc.pack(anchor='w', pady=(6, 18))

            btn = tk.Button(frame, text='Öffnen', command=info['command'], cursor='hand2')
            btn.pack(anchor='w')

            self.card_frames.append(frame)
            self.card_titles.append(title)
            self.card_desc.append(desc)
            self.card_buttons.append(btn)

        for col in range(2):
            self.card_grid.grid_columnconfigure(col, weight=1)

    def apply_theme(self, palette, paint_button):
        self.configure(style='App.TFrame')
        self.wrapper.configure(style='App.TFrame')
        self.hero.configure(style='Hero.TFrame')
        self.card_grid.configure(style='App.TFrame')

        self.hero_badge.configure(style='HeroBadge.TLabel')
        self.hero_title.configure(style='HeroTitle.TLabel')
        self.hero_subtitle.configure(style='HeroSub.TLabel')

        for frame in self.card_frames:
            frame.configure(style='Card.TFrame')
        for title in self.card_titles:
            title.configure(style='CardTitle.TLabel')
        for desc in self.card_desc:
            desc.configure(style='Muted.TLabel')
        for btn in self.card_buttons:
            paint_button(btn)

class GearLeverPage(ttk.Frame):
    HOLD_DELAY_MS = 600  # ms until Ueberdruecken is triggered

    def __init__(self, parent, app: THNApp):
        super().__init__(parent, style="App.TFrame")
        self.app = app

        self._frames: list[ttk.Frame] = []
        self._buttons: list[tk.Button] = []
        self._hold_job = None
        self._pressed_direction: str | None = None
        self._hold_sent = False
        self._park_active = False

        self.hero = ttk.Frame(self, padding=24, style="Hero.TFrame")
        self.hero.pack(fill="x")
        self._frames.append(self.hero)

        hero_header = ttk.Frame(self.hero, style="Hero.TFrame")
        hero_header.pack(fill="x")

        self.hero_badge = ttk.Label(hero_header, text="Simulation", style="HeroBadge.TLabel")
        self.hero_badge.pack(side="left")

        self.close_btn = tk.Button(hero_header, text="Zurueck", command=lambda: app.show("MainMenu"), cursor="hand2")
        self.close_btn.pack(side="right")
        self._buttons.append(self.close_btn)

        self.head = ttk.Label(self.hero, text="Ganghebel-Steuerung", style="HeroTitle.TLabel")
        self.head.pack(anchor="w", pady=(12, 4))

        self.subtitle = ttk.Label(
            self.hero,
            text="Tippen, Überdrücken und Parkmodus direkt aus der Anwendung auslösen.",
            style="HeroSub.TLabel",
            wraplength=520,
            justify="left",
        )
        self.subtitle.pack(anchor="w")

        self.body_container = ttk.Frame(self, padding=0, style="App.TFrame")
        self.body_container.pack(expand=True, fill="both")
        self._frames.append(self.body_container)

        self.grid = ttk.Frame(self.body_container, style="App.TFrame")
        self.grid.pack(expand=True, fill="both")
        self._frames.append(self.grid)
        self.grid.grid_columnconfigure(0, weight=1)
        self.grid.grid_columnconfigure(1, weight=1)

        self.lever_card = ttk.Frame(self.grid, style="Card.TFrame", padding=20)
        self.lever_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=(0, 12))
        self._frames.append(self.lever_card)

        self.lever_state_var = tk.StringVar(value="Ruhestellung")
        self.lever_state = ttk.Label(
            self.lever_card,
            textvariable=self.lever_state_var,
            style="CardTitle.TLabel",
        )
        self.lever_state.pack(anchor="w")

        self.lever_hint = ttk.Label(
            self.lever_card,
            text="Tippen = kurzer Klick • Überdrücken = gedrückt halten (≥ 0,6 s).",
            style="Muted.TLabel",
            wraplength=260,
            justify="left",
        )
        self.lever_hint.pack(anchor="w", pady=(6, 18))

        self.forward_btn = tk.Button(self.lever_card, text="Vorwärts tippen", cursor="hand2")
        self.forward_btn.pack(fill="x")
        self.forward_btn.bind("<ButtonPress-1>", lambda _e: self._on_direction_press("forward"))
        self.forward_btn.bind("<ButtonRelease-1>", lambda _e: self._on_direction_release("forward"))
        self.forward_btn.bind("<Leave>", lambda _e: self._on_direction_release("forward"))
        self._buttons.append(self.forward_btn)

        self.backward_btn = tk.Button(self.lever_card, text="Rückwärts tippen", cursor="hand2")
        self.backward_btn.pack(fill="x", pady=(12, 0))
        self.backward_btn.bind("<ButtonPress-1>", lambda _e: self._on_direction_press("back"))
        self.backward_btn.bind("<ButtonRelease-1>", lambda _e: self._on_direction_release("back"))
        self.backward_btn.bind("<Leave>", lambda _e: self._on_direction_release("back"))
        self._buttons.append(self.backward_btn)

        self.park_card = ttk.Frame(self.grid, style="Card.TFrame", padding=20)
        self.park_card.grid(row=0, column=1, sticky="nsew", padx=(12, 0), pady=(0, 12))
        self._frames.append(self.park_card)

        self.park_title = ttk.Label(self.park_card, text="Park-Funktion", style="CardTitle.TLabel")
        self.park_title.pack(anchor="w")

        self.park_desc = ttk.Label(
            self.park_card,
            text="Aktiviere oder löse den Parkmodus über den digitalen Tastendruck.",
            style="Muted.TLabel",
            wraplength=260,
            justify="left",
        )
        self.park_desc.pack(anchor="w", pady=(6, 18))

        self.park_btn = tk.Button(self.park_card, text="Park (frei)", command=self._toggle_park, cursor="hand2")
        self.park_btn.pack(anchor="w")
        self._buttons.append(self.park_btn)

        self.status_var = tk.StringVar(value="Bereit: keine Nachricht gesendet.")
        self.status = tk.Label(
            self,
            textvariable=self.status_var,
            anchor="w",
            font=("Segoe UI", 11, "bold"),
            padx=18,
            pady=12,
        )
        self.status.pack(fill="x", pady=(0, 16))

    def apply_theme(self, palette, paint_button):
        self.configure(style="App.TFrame")
        self.body_container.configure(style="App.TFrame")
        self.grid.configure(style="App.TFrame")

        self.hero.configure(style="Hero.TFrame")
        self.hero_badge.configure(style="HeroBadge.TLabel")
        self.head.configure(style="HeroTitle.TLabel")
        self.subtitle.configure(style="HeroSub.TLabel")

        self.lever_card.configure(style="Card.TFrame")
        self.park_card.configure(style="Card.TFrame")
        self.lever_state.configure(style="CardTitle.TLabel")
        self.lever_hint.configure(style="Muted.TLabel")
        self.park_title.configure(style="CardTitle.TLabel")
        self.park_desc.configure(style="Muted.TLabel")

        paint_button(self.forward_btn)
        paint_button(self.backward_btn)
        self.app.paint_secondary(self.close_btn)
        self._update_park_visual()
        self._set_status_palette("neutral")
        self.status.configure(relief="flat", bd=0)

    def _on_direction_press(self, direction: str) -> None:
        if self._pressed_direction == direction:
            return
        self._clear_hold_timer()
        self._pressed_direction = direction
        self._hold_sent = False
        if direction == "forward":
            self._send_action("forward_tap")
        else:
            self._send_action("back_tap")
        self._hold_job = self.after(self.HOLD_DELAY_MS, lambda: self._trigger_hold(direction))

    def _trigger_hold(self, direction: str) -> None:
        self._hold_job = None
        if self._pressed_direction != direction or self._hold_sent:
            return
        self._hold_sent = True
        if direction == "forward":
            self._send_action("forward_hold")
        else:
            self._send_action("back_hold")

    def _on_direction_release(self, direction: str) -> None:
        if self._pressed_direction != direction:
            self._clear_hold_timer()
            return
        self._clear_hold_timer()
        self._pressed_direction = None
        self._hold_sent = False
        self._send_action("rest")

    def _clear_hold_timer(self) -> None:
        if self._hold_job is not None:
            try:
                self.after_cancel(self._hold_job)
            except Exception:
                pass
            self._hold_job = None

    def _toggle_park(self) -> None:
        self._park_active = not self._park_active
        action = "park_press" if self._park_active else "park_release"
        self._send_action(action, update_indicator=False)
        self._update_park_visual()

    def _update_park_visual(self) -> None:
        if self._park_active:
            self.park_btn.configure(text="Park deaktivieren")
            painter = getattr(self.app, "paint_primary", None)
        else:
            self.park_btn.configure(text="Park aktivieren")
            painter = getattr(self.app, "paint_secondary", None)
        if callable(painter):
            painter(self.park_btn)

    def _set_status_palette(self, tone: str) -> None:
        palette = getattr(self.app, "palette", {})
        if tone == "ok":
            bg = palette.get("primary", THN_RED)
            fg = THN_WHITE
        elif tone == "warn":
            bg = palette.get("surface", THN_GRAY_SURFACE)
            fg = THN_RED
        else:
            bg = palette.get("surface", THN_GRAY_SURFACE)
            fg = palette.get("fg", THN_BLACK)
        self.status.configure(bg=bg, fg=fg)

    def _send_action(self, action_key: str, *, update_indicator: bool = True) -> None:
        state_name = GEAR_ACTIONS.get(action_key)
        if not state_name:
            self.status_var.set(f"{action_key}: unbekannte Aktion.")
            return
        self._send_state(state_name, update_indicator=update_indicator)

    def _send_state(self, name: str, *, update_indicator: bool = True) -> None:
        payload = GEAR_LEVER_LOOKUP.get(name)
        if not payload:
            self.status_var.set(f"{name}: nicht definiert.")
            return
        can_id_hex, data_hex = payload
        if update_indicator:
            self.lever_state_var.set(name)
        self.status_var.set(f"{name}: sende ...")
        self.update_idletasks()

        try:
            bus = open_bus()
        except Exception as e:
            self.status_var.set(f"{name}: Bus nicht verfuegbar.")
            messagebox.showerror("CAN Fehler", f"Bus konnte nicht geoeffnet werden:\n{e}")
            return

        try:
            msg = make_msg(can_id_hex, data_hex)
            bus.send(msg)
            try:
                print_tx(msg)
            except Exception:
                pass

            recv_found = False
            t_end = time.time() + 0.2
            while time.time() < t_end:
                m = bus.recv(timeout=0.01)
                if m is None:
                    continue
                recv_found = True
                try:
                    print_rx(m)
                except Exception:
                    pass

            note = "Antwort empfangen." if recv_found else "gesendet (keine Antwort)."
            self.status_var.set(f"{name}: {note}")
        except Exception as err:
            self.status_var.set(f"{name}: Fehler beim Senden.")
            messagebox.showerror("CAN Fehler", f"Senden fehlgeschlagen:\n{err}")
        finally:
            try:
                bus.shutdown()
            except Exception:
                pass

        if update_indicator and name == GEAR_ACTIONS["rest"] and self._park_active:
            # Keep lever indicator on rest while Park info stays separate
            self.lever_state_var.set("Ruhestellung")


class UdsTablePage(ttk.Frame):
    EA_RSP = UDS_EA_RSP
    DID_LED = 0xD631
    DID_AHL = 0xD663
    DID_LWR = 0xD63B
    AUTO_INTERVAL_MS = 1000

    def __init__(self, parent, app: THNApp):
        super().__init__(parent, style='App.TFrame')
        self.app = app

        self._frames: list[ttk.Frame] = []
        self._buttons: list[tk.Button] = []
        self._value_vars: list[tk.StringVar] = []
        self._auto_job: int | None = None
        self.auto = False

        self.hero = ttk.Frame(self, padding=24, style='Hero.TFrame')
        self.hero.pack(fill='x')

        self.hero_badge = ttk.Label(self.hero, text='Auswertung', style='HeroBadge.TLabel')
        self.hero_badge.pack(anchor='w')

        hero_header = ttk.Frame(self.hero, style='Hero.TFrame')
        hero_header.pack(fill='x', pady=(8, 0))

        self.head = ttk.Label(hero_header, text='LED Werte Tabelle', style='HeroTitle.TLabel')
        self.head.pack(side='left')

        self.close_btn = tk.Button(hero_header, text='Zurueck', command=lambda: app.show('MainMenu'), cursor='hand2')
        self.close_btn.pack(side='right')
        self._buttons.append(self.close_btn)

        self.subtitle = ttk.Label(
            self.hero,
            text='Lese live Werte der linken und rechten Leuchteinheiten inklusive Winkel.',
            style='HeroSub.TLabel',
            wraplength=520,
            justify='left',
        )
        self.subtitle.pack(anchor='w', pady=(8, 0))

        self.body_card = ttk.Frame(self, padding=24, style='App.TFrame')
        self.body_card.pack(expand=True, fill='both')
        self._frames.append(self.body_card)

        controls = ttk.Frame(self.body_card, style='Card.TFrame')
        controls.pack(fill='x', pady=(0, 12))
        self._frames.append(controls)

        ttk.Label(controls, text='Scheinwerfer:', style='Muted.TLabel').pack(side='left', padx=(0, 6))
        self.profile_var = tk.StringVar(value=UDS_PROFILE_ORDER[0])
        self.profile_menu = ttk.OptionMenu(controls, self.profile_var, UDS_PROFILE_ORDER[0], *UDS_PROFILE_ORDER)
        self.profile_menu.pack(side='left', padx=(0, 16))

        self.read_btn = tk.Button(controls, text='Einmal lesen', command=self.read_once)
        self.read_btn.pack(side='left', padx=(0, 8), ipadx=18, ipady=10)
        self._buttons.append(self.read_btn)

        self.auto_btn = tk.Button(controls, text='Auto (beide Profile) Start', command=self.toggle_auto)
        self.auto_btn.pack(side='left', ipadx=18, ipady=10)
        self._buttons.append(self.auto_btn)

        self.info_label = ttk.Label(
            self.body_card,
            text='Liest UDS DIDs D631 (LED), D663 (AHL) und D63B (LWR) via CAN.',
            style='Card.TLabel',
            justify='left',
        )
        self.info_label.pack(anchor='w', pady=(0, 8))

        scroll_outer = ttk.Frame(self.body_card, style='Card.TFrame')
        scroll_outer.pack(expand=True, fill='both')
        self._frames.append(scroll_outer)

        self.canvas = tk.Canvas(scroll_outer, highlightthickness=0, bd=0)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.scrollbar = ttk.Scrollbar(scroll_outer, orient='vertical', command=self.canvas.yview)
        self.scrollbar.pack(side='right', fill='y')
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.table_container = ttk.Frame(self.canvas, style='Card.TFrame')
        self._canvas_window = self.canvas.create_window((0, 0), window=self.table_container, anchor='nw')
        self.table_container.bind(
            '<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        )
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self._canvas_window, width=e.width))
        self.table_container.grid_columnconfigure(0, weight=1)
        self.table_container.grid_columnconfigure(1, weight=1)
        self._frames.append(self.table_container)

        led_order = list(range(1, 11))
        self._led_order = led_order
        self.percent_vars: list[tk.StringVar] = []
        self.current_vars: list[tk.StringVar] = []

        percent_frame = ttk.Frame(self.table_container, style='Card.TFrame')
        percent_frame.grid(row=0, column=0, sticky='nw', padx=(0, 12))
        self._frames.append(percent_frame)
        percent_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(percent_frame, text='LED Prozent', style='Card.TLabel', font=('Segoe UI', 11, 'bold')).grid(
            row=0, column=0, columnspan=3, sticky='w', pady=(0, 6)
        )
        for row, idx in enumerate(led_order, start=1):
            ttk.Label(percent_frame, text=f'LED {idx}', style='Card.TLabel').grid(
                row=row, column=0, sticky='w', padx=(0, 6), pady=2
            )
            var = tk.StringVar(value='-')
            self.percent_vars.append(var)
            self._value_vars.append(var)
            ttk.Label(percent_frame, textvariable=var, style='Card.TLabel', width=8).grid(
                row=row, column=1, sticky='w', pady=2
            )
            ttk.Label(percent_frame, text='%', style='Card.TLabel').grid(
                row=row, column=2, sticky='w', padx=(6, 0), pady=2
            )

        current_frame = ttk.Frame(self.table_container, style='Card.TFrame')
        current_frame.grid(row=0, column=1, sticky='nw')
        self._frames.append(current_frame)
        current_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(current_frame, text='LED Strom', style='Card.TLabel', font=('Segoe UI', 11, 'bold')).grid(
            row=0, column=0, columnspan=3, sticky='w', pady=(0, 6)
        )
        for row, idx in enumerate(led_order, start=1):
            ttk.Label(current_frame, text=f'LED {idx}', style='Card.TLabel').grid(
                row=row, column=0, sticky='w', padx=(0, 6), pady=2
            )
            var = tk.StringVar(value='-')
            self.current_vars.append(var)
            self._value_vars.append(var)
            ttk.Label(current_frame, textvariable=var, style='Card.TLabel', width=8).grid(
                row=row, column=1, sticky='w', pady=2
            )
            ttk.Label(current_frame, text='mA', style='Card.TLabel').grid(
                row=row, column=2, sticky='w', padx=(6, 0), pady=2
            )

        extra_frame = ttk.Frame(self.table_container, style='Card.TFrame')
        extra_frame.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(16, 0))
        extra_frame.grid_columnconfigure(1, weight=1)
        extra_frame.grid_columnconfigure(4, weight=1)
        self._frames.append(extra_frame)

        ttk.Label(extra_frame, text='AHL Position', style='Card.TLabel').grid(row=0, column=0, sticky='w', padx=(0, 6))
        self.ahl_var = tk.StringVar(value='-')
        ttk.Label(extra_frame, textvariable=self.ahl_var, style='Card.TLabel', width=8).grid(
            row=0, column=1, sticky='w'
        )
        ttk.Label(extra_frame, text='deg', style='Card.TLabel').grid(row=0, column=2, sticky='w', padx=(6, 18))

        ttk.Label(extra_frame, text='LWR Position', style='Card.TLabel').grid(row=0, column=3, sticky='w', padx=(0, 6))
        self.lwr_var = tk.StringVar(value='-')
        ttk.Label(extra_frame, textvariable=self.lwr_var, style='Card.TLabel', width=8).grid(
            row=0, column=4, sticky='w'
        )
        ttk.Label(extra_frame, text='deg', style='Card.TLabel').grid(row=0, column=5, sticky='w', padx=(6, 0))

        self._value_vars.extend([self.ahl_var, self.lwr_var])

        self.status_var = tk.StringVar(value='Bereit: keine Daten gelesen.')
        self.status = tk.Label(
            self,
            textvariable=self.status_var,
            anchor='w',
            font=('Segoe UI', 11, 'bold'),
            padx=18,
            pady=12,
        )
        self.status.pack(fill='x', pady=(12, 16))

    def apply_theme(self, palette, paint_button):
        self.configure(style='App.TFrame')
        self.hero.configure(style='Hero.TFrame')
        self.hero_badge.configure(style='HeroBadge.TLabel')
        self.head.configure(style='HeroTitle.TLabel')
        self.subtitle.configure(style='HeroSub.TLabel')
        self.body_card.configure(style='App.TFrame')
        for frame in self._frames:
            frame.configure(style='Card.TFrame')
        self.info_label.configure(style='Muted.TLabel')
        for btn in (self.read_btn, self.auto_btn):
            paint_button(btn)
        if hasattr(self.app, 'paint_secondary'):
            self.app.paint_secondary(self.close_btn)
        self._set_status_palette('neutral')
        bg = palette.get('card', THN_WHITE)
        try:
            self.canvas.configure(background=bg)
        except Exception:
            pass

    def _set_status_palette(self, tone: str) -> None:
        palette = getattr(self.app, "palette", {})
        if tone == "ok":
            bg = palette.get("primary", THN_RED)
            fg = THN_WHITE
        elif tone == "warn":
            bg = palette.get("surface", THN_GRAY_SURFACE)
            fg = THN_RED
        else:
            bg = palette.get("surface", THN_GRAY_SURFACE)
            fg = palette.get("fg", THN_BLACK)
        self.status.configure(bg=bg, fg=fg)


    def destroy(self):
        self._stop_auto()
        super().destroy()

    def read_once(self):
        profile_name = self.profile_var.get()
        self.status_var.set(f"{profile_name}: lese Daten ...")
        self._set_status_palette("neutral")
        if self._update_for_profile(profile_name):
            self.status_var.set(f"{profile_name}: Daten aktualisiert.")
            self._set_status_palette("ok")

    def toggle_auto(self):
        if self.auto:
            self._stop_auto()
            return
        self.auto = True
        self.auto_btn.configure(text='Auto Stop')
        self.status_var.set('Auto-Modus: pruefe Links und Rechts.')
        self._set_status_palette('neutral')
        self._schedule_auto()

    def _schedule_auto(self):
        if not self.auto:
            return
        self._auto_cycle()
        if self.auto:
            self._auto_job = self.after(self.AUTO_INTERVAL_MS, self._schedule_auto)

    def _auto_cycle(self):
        self._set_status_palette("neutral")
        try:
            bus = open_bus()
        except Exception as exc:
            self.status_var.set(f"Auto: Busfehler {exc}")
            if self._value_vars:
                self._value_vars[0].set(f"Err: {exc}")
            self._set_status_palette("warn")
            self._stop_auto()
            return
        try:
            for name in UDS_PROFILE_ORDER:
                try:
                    values = self._fetch_values(UDS_PROFILES[name], bus=bus)
                except Exception:
                    continue
                self.profile_var.set(name)
                self._apply_values(values)
                self.status_var.set(f"Auto: {name} aktualisiert.")
                self._set_status_palette("ok")
                return
            self.status_var.set('Auto: keine Antwort von Links/Rechts.')
            if self._value_vars:
                self._value_vars[0].set('n/a (keine Antwort)')
            self._set_status_palette("warn")
        finally:
            try:
                bus.shutdown()
            except Exception:
                pass

    def _stop_auto(self):
        if self.auto:
            self.status_var.set('Auto-Modus gestoppt.')
            self._set_status_palette('neutral')
        self.auto = False
        self.auto_btn.configure(text='Auto (beide Profile) Start')
        if self._auto_job is not None:
            try:
                self.after_cancel(self._auto_job)
            except Exception:
                pass
        self._auto_job = None

    def _update_for_profile(self, profile_name: str, *, show_error: bool = True) -> bool:
        cfg = UDS_PROFILES.get(profile_name)
        if cfg is None:
            if show_error:
                self.status_var.set(f"{profile_name}: unbekanntes Profil.")
                self._set_status_palette("warn")
            return False
        try:
            bus = open_bus()
        except Exception as exc:
            if show_error:
                self.status_var.set(f"{profile_name}: Busfehler {exc}")
                if self._value_vars:
                    self._value_vars[0].set(f"Err: {exc}")
                self._set_status_palette("warn")
            return False
        try:
            values = self._fetch_values(cfg, bus=bus)
        except Exception as exc:
            if show_error:
                self.status_var.set(f"{profile_name}: Fehler {exc}")
                if self._value_vars:
                    self._value_vars[0].set(f"Err: {exc}")
                self._set_status_palette("warn")
            return False
        finally:
            try:
                bus.shutdown()
            except Exception:
                pass
        self.profile_var.set(profile_name)
        self._apply_values(values)
        self.status_var.set(f"{profile_name}: Daten aktualisiert.")
        self._set_status_palette("ok")
        return True

    def _fetch_values(self, cfg: dict[str, int], *, bus) -> list[str]:
        payload_led = self._uds_read_by_identifier(
            bus,
            tx_id=cfg['TX_ID'],
            rx_id=cfg['RX_ID'],
            ea_req=cfg['EA_REQ'],
            did=self.DID_LED,
        )
        payload_ahl = self._uds_read_by_identifier(
            bus,
            tx_id=cfg['TX_ID'],
            rx_id=cfg['RX_ID'],
            ea_req=cfg['EA_REQ'],
            did=self.DID_AHL,
        )
        payload_lwr = self._uds_read_by_identifier(
            bus,
            tx_id=cfg['TX_ID'],
            rx_id=cfg['RX_ID'],
            ea_req=cfg['EA_REQ'],
            did=self.DID_LWR,
        )
        pct_vals, ma_vals = self._decode_led(payload_led)
        ahl_val = f"{self._decode_ahl(payload_ahl):.2f}"
        lwr_val = f"{self._decode_lwr(payload_lwr):.2f}"
        return pct_vals + ma_vals + [ahl_val, lwr_val]

    def _apply_values(self, values: list[str]) -> None:
        count = 0
        for count, (var, val) in enumerate(zip(self._value_vars, values), start=1):
            var.set(val)
        for var in self._value_vars[count:]:
            var.set('-')

    def _decode_led(self, payload: list[int]) -> tuple[list[str], list[str]]:
        """Split the LED payload into percentage and current strings.

        According to the traces, the ECU returns up to 20 data bytes for DID
        D631: the first ten bytes are duty-cycle percentages, the remaining ten
        bytes are LED currents in 10 mA steps. Responses can occasionally be
        shorter (for example only the first frame arrives). In that case the
        missing bytes should be treated as zeros so that the UI still shows a
        defined value instead of a dash.
        """

        padded = (payload[:20] + [0] * (20 - len(payload))) if len(payload) < 20 else payload[:20]
        perc_raw = padded[:10]
        curr_raw = padded[10:20]

        percent = [str(max(0, min(100, val))) for val in perc_raw]
        current = [str(max(0, val) * 10) for val in curr_raw]
        return percent, current

    def _decode_ahl(self, payload: list[int]) -> float:
        """Decode AHL position (D663) from a two-byte value in 0.1° steps."""

        if len(payload) >= 2:
            raw = (payload[0] << 8) | payload[1]
        elif payload:
            raw = payload[0]
        else:
            raw = 0
        return raw / 10.0

    def _decode_lwr(self, payload: list[int]) -> float:
        """Decode LWR position (D63B) from a one-byte value in 0.1° steps."""

        raw = payload[0] if payload else 0
        return raw / 10.0

    def _send_frame(self, bus, arbitration_id: int, data: list[int]) -> None:
        msg = can.Message(arbitration_id=arbitration_id, is_extended_id=False, data=bytes(data))
        bus.send(msg)
        try:
            print_tx(msg)
        except Exception:
            pass

    def _recv_until(self, bus, arbitration_id: int, timeout_s: float = 1.0):
        end = time.time() + timeout_s
        while time.time() < end:
            msg = bus.recv(timeout=0.01)
            if msg is None:
                continue
            if msg.arbitration_id != arbitration_id:
                continue
            raw = list(msg.data)
            if len(raw) < 8:
                raw.extend([0] * (8 - len(raw)))
            try:
                print_rx(msg)
            except Exception:
                pass
            return raw
        return None

    def _uds_read_by_identifier(self, bus, *, tx_id: int, rx_id: int, ea_req: int, did: int) -> list[int]:
        did_hi = (did >> 8) & 0xFF
        did_lo = did & 0xFF
        request = [ea_req, 0x03, 0x22, did_hi, did_lo, 0x00, 0x00, 0x00]
        self._send_frame(bus, tx_id, request)

        first = self._recv_until(bus, rx_id, timeout_s=1.0)
        if not first or first[0] != self.EA_RSP:
            raise RuntimeError('Keine gueltige UDS Antwort.')
        pci = first[1] & 0xF0

        if pci == 0x00:
            if first[2] != 0x62 or first[3] != did_hi or first[4] != did_lo:
                raise RuntimeError('Negative Antwort (SF).')
            length = first[1] & 0x0F
            return first[5 : 5 + length]

        if pci == 0x10:
            self._send_frame(bus, tx_id, [ea_req, 0x30, 0x00, 0x00, 0, 0, 0, 0])
            if first[3] != 0x62 or first[4] != did_hi or first[5] != did_lo:
                raise RuntimeError('Negative Antwort (FF).')
            payload = first[6:]
            while True:
                cf = self._recv_until(bus, rx_id, timeout_s=1.0)
                if not cf or cf[0] != self.EA_RSP or (cf[1] & 0xF0) != 0x20:
                    break
                payload += cf[2:]
                if len(payload) > 128:
                    break
            return payload

        raise RuntimeError('Unerwartete PCI Art.')

class BrakePage(ttk.Frame):
    def __init__(self, parent, app: THNApp):
        super().__init__(parent, style='App.TFrame')
        self.app = app

        hero = ttk.Frame(self, padding=24, style='Hero.TFrame')
        hero.pack(fill='x')
        self.hero_badge = ttk.Label(hero, text='Sequenzen', style='HeroBadge.TLabel')
        self.hero_badge.pack(anchor='w')

        header_row = ttk.Frame(hero, style='Hero.TFrame')
        header_row.pack(fill='x', pady=(8, 0))
        self.head = ttk.Label(header_row, text='Feststellbremse - Modi', style='HeroTitle.TLabel')
        self.head.pack(side='left')

        self.close_btn = tk.Button(header_row, text='Zurueck', command=lambda: app.show('MainMenu'), cursor='hand2')
        self.close_btn.pack(side='right')

        self.subtitle = ttk.Label(
            hero,
            text='Schalte zwischen Werkstatt- und Betriebsmodus und sende die passenden Frames.',
            style='HeroSub.TLabel',
            wraplength=520,
            justify='left',
        )
        self.subtitle.pack(anchor='w', pady=(8, 0))

        self.action_card = ttk.Frame(self, padding=24, style='Card.TFrame')
        self.action_card.pack(fill='x', padx=0, pady=(24, 0))

        self.btn_workshop = tk.Button(self.action_card, text='Werkstattmodus', command=self.run_workshop, cursor='hand2')
        self.btn_workshop.pack(fill='x')

        self.btn_operation = tk.Button(self.action_card, text='Betriebsmodus', command=self.run_operation, cursor='hand2')
        self.btn_operation.pack(fill='x', pady=(12, 0))

        self.status_var = tk.StringVar(value='Bereit: keine Aktion.')
        self.status = tk.Label(
            self,
            textvariable=self.status_var,
            anchor='w',
            font=('Segoe UI', 11, 'bold'),
            padx=18,
            pady=12,
        )
        self.status.pack(fill='x', pady=(24, 16))


    def apply_theme(self, palette, paint_button):
        self.configure(style="App.TFrame")
        self.hero_badge.configure(style="HeroBadge.TLabel")
        self.head.configure(style="HeroTitle.TLabel")
        self.subtitle.configure(style="HeroSub.TLabel")
        self.action_card.configure(style="Card.TFrame")
        paint_button(self.btn_workshop)
        paint_button(self.btn_operation)
        if hasattr(self.app, "paint_secondary"):
            self.app.paint_secondary(self.close_btn)
        self._set_status_palette("neutral")

    def _set_status_palette(self, tone: str) -> None:
        palette = getattr(self.app, "palette", {})
        if tone == "ok":
            bg = palette.get("primary", THN_RED)
            fg = THN_WHITE
        elif tone == "warn":
            bg = palette.get("surface", THN_GRAY_SURFACE)
            fg = THN_RED
        else:
            bg = palette.get("surface", THN_GRAY_SURFACE)
            fg = palette.get("fg", THN_BLACK)
        self.status.configure(bg=bg, fg=fg)

    def run_workshop(self):
        self.status_var.set("Sende Werkstatt-Sequenz ...")
        self._set_status_palette("neutral")
        self.update_idletasks()
        ok = send_sequence(WORKSHOP_SEQUENCE, delay_s=0.1, rx_window_s=0.2)  # 100 ms
        if ok:
            self.status_var.set("OK – Werkstatt-Sequenz gesendet (100 ms Delay).")
            self._set_status_palette("ok")
        else:
            self.status_var.set("Fehler beim Senden – Details im Dialog.")
            self._set_status_palette("warn")

    def run_operation(self):
        self.status_var.set("Sende Betriebs-Sequenz ...")
        self._set_status_palette("neutral")
        self.update_idletasks()
        ok = send_sequence(OPERATION_SEQUENCE, delay_s=0.02, rx_window_s=0.2)
        if ok:
            self.status_var.set("OK – Betriebs-Sequenz gesendet.")
            self._set_status_palette("ok")
            messagebox.showinfo("Hinweis", "Bitte jetzt an der Handbremse ziehen.")
        else:
            self.status_var.set("Fehler beim Senden – Details im Dialog.")
            self._set_status_palette("warn")

class TestPage(ttk.Frame):
    def __init__(self, parent, app: THNApp):
        super().__init__(parent, style="Card.TFrame")
        self.app = app

        top = ttk.Frame(self, padding=16, style="Card.TFrame")
        top.pack(fill="x")

        self.head = ttk.Label(top, text="Test – Manuelle CAN-Nachricht", style="Card.TLabel", font=("Segoe UI", 16, "bold"))
        self.head.pack(side="left")

        self.close_btn = tk.Button(top, text="X", command=lambda: app.show("MainMenu"))
        self.close_btn.pack(side="right")

        body = ttk.Frame(self, padding=24, style="Card.TFrame")
        body.pack(expand=True, fill="both")

        # CAN-ID
        id_row = ttk.Frame(body, style="Card.TFrame")
        id_row.pack(fill="x", pady=6)
        ttk.Label(id_row, text="CAN-ID (hex, z.B. 1777 / 6F1):", style="Card.TLabel").pack(side="left")
        self.entry_id = ttk.Entry(id_row, width=20)
        self.entry_id.pack(side="left", padx=8)

        # 8 Byte-Felder (kleine Kästen)
        bytes_row = ttk.Frame(body, style="Card.TFrame")
        bytes_row.pack(fill="x", pady=10)
        ttk.Label(bytes_row, text="Daten (8 Bytes):", style="Card.TLabel").pack(side="left", padx=(0,8))

        self.byte_entries: list[ttk.Entry] = []
        for i in range(8):
            e = ttk.Entry(bytes_row, width=4, justify="center")
            e.pack(side="left", padx=3)
            self.byte_entries.append(e)

        hint = ttk.Label(
            body,
            text="Hinweis: Jedes Feld akzeptiert 0–FF. Leer lassen = alle 256 Werte an dieser Position durchprobieren.",
            style="Card.TLabel"
        )
        hint.pack(anchor="w", pady=(6, 0))

        # Sende-Parameter
        param_row = ttk.Frame(body, style="Card.TFrame")
        param_row.pack(fill="x", pady=10)
        ttk.Label(param_row, text="Delay zwischen Varianten (ms):", style="Card.TLabel").pack(side="left")
        self.entry_delay = ttk.Entry(param_row, width=8)
        self.entry_delay.insert(0, "20")
        self.entry_delay.pack(side="left", padx=8)

        ttk.Label(param_row, text="RX-Fenster je TX (ms):", style="Card.TLabel").pack(side="left")
        self.entry_rx = ttk.Entry(param_row, width=8)
        self.entry_rx.insert(0, "200")
        self.entry_rx.pack(side="left", padx=8)

        # Senden-Button
        self.send_btn = tk.Button(body, text="Senden", command=self.on_send)
        self.send_btn.pack(pady=16, ipadx=18, ipady=10)

        # Status
        self.status = ttk.Label(self, text="", style="Card.TLabel")
        self.status.pack(pady=(0, 16))

    def apply_theme(self, bg, fg, card, paint_button):
        self.configure(style="Card.TFrame")
        for w in self.winfo_children():
            if isinstance(w, ttk.Frame):
                w.configure(style="Card.TFrame")
        self.head.configure(style="Card.TLabel")
        self.status.configure(style="Card.TLabel")
        paint_button(self.close_btn)
        paint_button(self.send_btn)

    def on_send(self):
        can_id = self.entry_id.get().strip().upper().replace("0X", "")
        if not can_id:
            messagebox.showerror("Eingabe", "Bitte eine CAN-ID angeben (hex).")
            return

        try:
            delay_ms = int(self.entry_delay.get())
            rx_ms = int(self.entry_rx.get())
        except ValueError:
            messagebox.showerror("Eingabe", "Delay/RX-Fenster müssen ganze Millisekunden sein.")
            return

        # Tokens aus 8 Byte-Feldern
        try:
            user_vals = [e.get() for e in self.byte_entries]
            tokens, total = tokens_from_boxes(user_vals)  # list von '00'..'FF' oder None
        except ValueError as e:
            messagebox.showerror("Eingabe", f"Byte-Eingabe fehlerhaft: {e}")
            return

        # Sicherheitscheck
        if total > 4096:
            if not messagebox.askyesno("Viele Varianten", f"Es würden {total} Varianten gesendet.\nFortfahren?"):
                return

        # Vorbereiten: merken, welche Felder Wildcards sind (damit wir live anzeigen)
        wildcard_idx = [i for i, t in enumerate(tokens) if t is None]

        # Alle Choices zusammenstellen
        choices = []
        for t in tokens:
            if t is None:
                choices.append([f"{i:02X}" for i in range(256)])
            else:
                choices.append([t])

        # Senden
        self.status.configure(text="Sende …")
        self.update_idletasks()

        try:
            bus = open_bus()
        except Exception as e:
            messagebox.showerror("CAN Fehler", f"Bus konnte nicht geöffnet werden:\n{e}")
            return

        ok = True
        delay_s = max(0.0, delay_ms / 1000.0)
        rx_window_s = max(0.0, rx_ms / 1000.0)

        try:
            arb_id = int(can_id, 16)
            for combo in itertools.product(*choices):
                # Live-Anzeige: Wildcard-Felder mit aktuellem Wert befüllen
                for idx in wildcard_idx:
                    self.byte_entries[idx].delete(0, tk.END)
                    self.byte_entries[idx].insert(0, combo[idx])
                self.update_idletasks()

                data_hex = "".join(combo)
                msg = can.Message(arbitration_id=arb_id, is_extended_id=False, data=bytes.fromhex(data_hex))
                bus.send(msg)
                try:
                    print_tx(msg)
                except Exception:
                    pass

                # RX-Logging
                recv_drain(bus, max_duration=rx_window_s)
                time.sleep(delay_s)
        except Exception as e:
            ok = False
            messagebox.showerror("CAN Fehler", f"Senden fehlgeschlagen:\n{e}")
        finally:
            try:
                bus.shutdown()
            except Exception:
                pass

        if ok:
            self.status.configure(text="OK – Senden abgeschlossen.")
        else:
            self.status.configure(text="Abgebrochen / Fehler – Details im Dialog.")

if __name__ == "__main__":
    app = THNApp()
    app.mainloop()
