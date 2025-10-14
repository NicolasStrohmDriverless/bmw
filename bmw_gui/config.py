import os

# ---- Corporate Design Farben TH Nürnberg ----
THN_RED   = "#C93030"    # Rot (201,48,48)
THN_WHITE = "#FDFDFD"    # nahezu Weiß
THN_BLACK = "#000000"    # Schwarz

DARK_BG   = "#121212"
DARK_FG   = "#EDEDED"

# ---- Status-Indikator Farben ----
# Verbunden: grün, Keine Verbindung: grau, Fehler: orange
PCAN_STATUS_GREEN  = "#2ECC71"
PCAN_STATUS_GRAY   = "#9E9E9E"
PCAN_STATUS_ORANGE = "#F39C12"

# Dein Logo-Pfad (Windows)
LOGO_PATH = r"C:\Users\Nico\Documents\BMW\logo.png"

# ---- CAN Setup (python-can) ----
CAN_BACKEND = os.getenv("CAN_BACKEND", "pcan")          # "pcan" oder "socketcan"
CAN_CHANNEL = os.getenv("CAN_CHANNEL", "PCAN_USBBUS1")  # pcan: PCAN_USBBUS1 / socketcan: can0
CAN_BITRATE = int(os.getenv("CAN_BITRATE", "500000"))
