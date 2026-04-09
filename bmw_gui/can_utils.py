from __future__ import annotations
import time
from typing import Optional, Tuple, List, TYPE_CHECKING

from config import CAN_BACKEND, CAN_CHANNEL, CAN_BITRATE

# python-can optional laden (Runtime-Import getrennt von Typing-Import)
try:
    import can as _can  # type: ignore
except Exception:  # pragma: no cover
    _can = None

# Nur für Type Checking importieren, damit Pylance die Typen auflösen kann
if TYPE_CHECKING:  # pragma: no cover - nur statisch
    import can  # noqa: F401

CAN_AVAILABLE = _can is not None

def open_bus() -> "can.BusABC":
    """Öffnet den CAN-Bus gemäß ENV/Config."""
    if not CAN_AVAILABLE:
        raise RuntimeError("python-can ist nicht installiert.")
    backend = CAN_BACKEND.lower()
    if backend == "pcan":
        return _can.Bus(interface="pcan", channel=CAN_CHANNEL, bitrate=CAN_BITRATE)  # type: ignore[union-attr]
    elif backend == "socketcan":
        return _can.Bus(interface="socketcan", channel=CAN_CHANNEL, bitrate=CAN_BITRATE)  # type: ignore[union-attr]
    else:
        raise ValueError(f"Unbekannter CAN_BACKEND: {CAN_BACKEND}")

def open_sniffer_bus() -> "can.BusABC":
    """Open a CAN bus for passive sniffing.

    Uses listen-only/passive options when they are supported by the backend.
    Falls back to a normal open operation if the driver rejects passive flags.
    """
    if not CAN_AVAILABLE:
        raise RuntimeError("python-can ist nicht installiert.")

    backend = CAN_BACKEND.lower()
    common_kwargs = dict(channel=CAN_CHANNEL, bitrate=CAN_BITRATE)

    if backend == "socketcan":
        # SocketCAN supports listen_only on many drivers.
        for extra in (
            {"listen_only": True},
            {"receive_own_messages": False, "local_loopback": False},
            {},
        ):
            try:
                return _can.Bus(interface="socketcan", **common_kwargs, **extra)  # type: ignore[union-attr]
            except Exception:
                continue
        raise RuntimeError("SocketCAN-Bus konnte nicht geoeffnet werden.")

    if backend == "pcan":
        # Depending on PCAN/python-can version, passive mode may be exposed via
        # state/listen_only or not at all.
        state_passive = None
        try:
            state_passive = getattr(_can, "BusState").PASSIVE  # type: ignore[union-attr]
        except Exception:
            state_passive = None

        attempts = []
        if state_passive is not None:
            attempts.append({"state": state_passive})
        attempts.extend(
            [
                {"listen_only": True},
                {"receive_own_messages": False},
                {},
            ]
        )

        for extra in attempts:
            try:
                return _can.Bus(interface="pcan", **common_kwargs, **extra)  # type: ignore[union-attr]
            except Exception:
                continue
        raise RuntimeError("PCAN-Bus konnte nicht geoeffnet werden.")

    raise ValueError(f"Unbekannter CAN_BACKEND: {CAN_BACKEND}")

def fmt_bytes(by: bytes) -> str:
    return " ".join(f"{b:02X}" for b in by)

def print_tx(msg: "can.Message") -> None:
    print(f"TX  ID=0x{msg.arbitration_id:03X}  DLC={msg.dlc}  Data={fmt_bytes(msg.data)}")

def print_rx(msg: "can.Message") -> None:
    ts = getattr(msg, "timestamp", None)
    if ts is not None:
        print(f"RX  ID=0x{msg.arbitration_id:03X}  DLC={msg.dlc}  Data={fmt_bytes(msg.data)}  ts={ts:.6f}")
    else:
        print(f"RX  ID=0x{msg.arbitration_id:03X}  DLC={msg.dlc}  Data={fmt_bytes(msg.data)}")

def recv_drain(bus: "can.BusABC", max_duration: float = 0.2) -> None:
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

def make_msg(can_id_hex: str, data_hex: str) -> "can.Message":
    """Erzeugt ein Standard-CAN-Frame (11-bit) aus Hex-Strings."""
    if _can is None:
        raise RuntimeError("python-can ist nicht installiert.")
    arb_id = int(can_id_hex, 16)
    data = bytes.fromhex(data_hex)
    return _can.Message(arbitration_id=arb_id, is_extended_id=False, data=data)  # type: ignore[union-attr]

# -------- Eingabe-/Hex-Helfer für TestPage --------

def normalize_hex_byte(val: str) -> Optional[str]:
    """
    Byte-Eingabe normalisieren:
      "" / "?" / "??" => None (Wildcard)
      "A" -> "0A", "0A" -> "0A"
      invalid -> ValueError
    """
    s = val.strip().upper().replace("0X", "")
    if s in ("", "?", "??"):
        return None
    if len(s) == 1:
        s = "0" + s
    if len(s) != 2:
        raise ValueError("Byte muss 1–2 Hex-Zeichen sein (z. B. A oder 0A).")
    int(s, 16)  # validate
    return s

def tokens_from_boxes(byte_values: List[str]) -> Tuple[List[Optional[str]], int]:
    """
    Liste von 8 Tokens ('00'..'FF' oder None) + Gesamtzahl der Varianten zurückgeben.
    """
    tokens: List[Optional[str]] = []
    total = 1
    for v in byte_values:
        t = normalize_hex_byte(v)
        tokens.append(t)
        if t is None:
            total *= 256
    return tokens, total
