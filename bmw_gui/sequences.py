from __future__ import annotations
import time
from typing import Iterable, Tuple, List

from can_utils import open_bus, print_tx, recv_drain, make_msg

# ---- Sequenzen ----

# Werkstattmodus (geänderte 0x6F1-Frames, jeweils DLC=8), 100 ms Abstand
WORKSHOP_SEQUENCE: List[Tuple[str, str]] = [
    ("6F1", "2902100300000000"),
    ("6F1", "29053101A8030200"),
]

# Betriebsmodus
OPERATION_SEQUENCE: List[Tuple[str, str]] = [
    ("6F1", "2902100300000000"),
    ("6F1", "290322F150000000"),
    ("6F1", "29042ED80F000000"),
]

# Scheinwerfer-Sequenz (vom Nutzer vorgegeben)
HEADLIGHT_SEQUENCE: List[Tuple[str, str]] = [
    ("6F1", "440322D639000000"),
    ("6F1", "4430000000000000"),
    ("6F1", "440322D63B000000"),
    ("6F1", "440322D631000000"),
    ("6F1", "4430000000000000"),
    ("6F1", "440322D63A000000"),
    ("6F1", "4430000000000000"),
    ("6F1", "440322D529000000"),
    ("6F1", "4430000000000000"),
    ("6F1", "440322D663000000"),
]

# Bremspedal-Sequenz (ID 0x6F1)
BRAKE_PEDAL_SEQUENCE: List[Tuple[str, str]] = [
    ("6F1", "290322DCD9000000"),
    ("6F1", "2930000000000000"),
    ("6F1", "290322DC1E000000"),
    ("6F1", "290322DBE5000000"),
    ("6F1", "2930000000000000"),
]

# Ganghebel-Zustaende: Name, CAN-ID, Datenhex (jeweils 6 bzw. 8 Byte)
GEAR_LEVER_STATES: List[Tuple[str, str, str]] = [
    ("Ruhestellung", "65E", "F10462D20000"),
    ("Tippen nach vorne", "65E", "F10462D20001"),
    ("Ueberdruecken nach vorne", "65E", "F10462D20002"),
    ("Tippen nach hinten", "65E", "F10462D20003"),
    ("Ueberdruecken nach hinten", "65E", "F10462D20004"),
    ("Parktaster ungedrueckt", "65E", "F1210000FFFFFFFF"),
    ("Parktaster gedrueckt", "65E", "F1210001FFFFFFFF"),
]

def send_sequence(seq: Iterable[Tuple[str, str]], delay_s: float = 0.02, rx_window_s: float = 0.2) -> bool:
    """
    Sendet eine Liste (id_hex, data_hex) mit Delay zwischen Frames.
    Nach jedem TX wird rx_window_s lang empfangen und alles geloggt.
    Gibt True/False zurück. Exceptions werden nach oben gereicht.
    """
    bus = open_bus()
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
    finally:
        try:
            bus.shutdown()
        except Exception:
            pass
