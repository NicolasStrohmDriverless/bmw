"""Background runner for the CAN trigger finder.

This module contains a lightly refactored version of the standalone
``find_trigger_generic.py`` script that was provided by the user.  The code is
wrapped so that it can be executed from the GUI without blocking the Tk main
loop.  The heavy lifting still happens in a tight loop inside a worker thread
and the GUI receives textual status updates through a callback.

The implementation intentionally mirrors the original script so that existing
workflow knowledge still applies.  Only a few small changes were necessary to
make the script cooperate with the rest of the application:

* graceful handling of missing ``PCANBasic`` (so the GUI can display a helpful
  message instead of crashing when the library is not installed),
* cooperative cancellation support via ``threading.Event``,
* dependency injection of a log callback so that the GUI can render textual
  output, and
* light refactoring to avoid reliance on command line parsing.

The public entry point is :class:`TriggerFinderRunner` which exposes ``start``
and ``stop`` methods and can be polled for its running state from the GUI.
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Iterable, Optional, Tuple, TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing helper
    from PCANBasic import PCANBasic as PCANBasicT, TPCANMsg as TPCANMsgT
else:  # pragma: no cover - typing helper
    PCANBasicT = Any
    TPCANMsgT = Any

# ``PCANBasic`` is optional in many development environments.  Import errors are
# converted into a ``None`` sentinel so that the GUI can surface a friendly
# explanation instead of crashing.
try:  # pragma: no cover - optional dependency
    from PCANBasic import (  # type: ignore
        PCANBasic,
        TPCANMsg,
        PCAN_USBBUS1,
        PCAN_BAUD_500K,
        PCAN_MESSAGE_STANDARD,
        PCAN_ERROR_OK,
        PCAN_ERROR_QRCVEMPTY,
    )
except Exception:  # pragma: no cover - optional dependency
    PCANBasic = None  # type: ignore
    TPCANMsg = object  # type: ignore
    PCAN_USBBUS1 = 0x51  # dummy placeholders
    PCAN_BAUD_500K = 0
    PCAN_MESSAGE_STANDARD = 0
    PCAN_ERROR_OK = 0
    PCAN_ERROR_QRCVEMPTY = 0x02000


# Default CAN settings – identical to the original script.  They can easily be
# expanded later if required by the GUI.
CHANNEL = PCAN_USBBUS1
BAUD = PCAN_BAUD_500K


# Profile „Links“/„Rechts“ (IDs/Extended Address im Request)
PROFILES: Dict[str, Dict[str, int]] = {
    "links": dict(TX_ID=0x06F1, RX_ID=0x0643, EA_REQ=0x43, EA_RSP=0xF1),
    "rechts": dict(TX_ID=0x06F2, RX_ID=0x0644, EA_REQ=0x44, EA_RSP=0xF1),
}


def _mk_msg(arbid: int, data8: Iterable[int]) -> TPCANMsgT:
    msg = TPCANMsg()
    msg.ID = arbid
    msg.MSGTYPE = PCAN_MESSAGE_STANDARD
    msg.LEN = 8
    arr = (ctypes.c_ubyte * 8)(*([0] * 8))
    for i, b in enumerate(list(data8)[:8]):
        arr[i] = b
    msg.DATA = arr
    return msg


def _pcan_write(api: PCANBasicT, arbid: int, data8: Iterable[int]):
    res = api.Write(CHANNEL, _mk_msg(arbid, list(data8)))
    if res != PCAN_ERROR_OK:
        raise RuntimeError(f"PCAN Write error 0x{int(res):X}")


def _pcan_read_once(api: PCANBasicT) -> Tuple[bool, Optional[int], Optional[int], Optional[Tuple[int, ...]], Optional[float]]:
    res, msg, _ = api.Read(CHANNEL)
    if res == PCAN_ERROR_OK:
        dlc = msg.LEN
        data = tuple(int(msg.DATA[i]) for i in range(dlc))
        return True, msg.ID, dlc, data, time.monotonic()
    if res == PCAN_ERROR_QRCVEMPTY:
        return False, None, None, None, None
    return False, None, None, None, None


def uds_read_by_id(api: PCANBasicT, did: int, *, tx_id: int, rx_id: int, ea_req: int, ea_rsp: int, timeout: float = 1.0) -> Tuple[int, ...]:
    """UDS 0x22 (Extended Addressing): liefert Payload-Bytes (ohne 0x62 DID)."""

    did_h, did_l = (did >> 8) & 0xFF, did & 0xFF
    # Request (Single Frame)
    _pcan_write(api, tx_id, [ea_req, 0x03, 0x22, did_h, did_l, 0, 0, 0])
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        ok, arbid, dlc, data, _ = _pcan_read_once(api)
        if not ok or arbid != rx_id or dlc is None or data is None or len(data) < 2:
            continue
        if data[0] != ea_rsp:
            continue
        pci = data[1] & 0xF0
        # Single Frame: [EA_RSP][0x0L][0x62][DID_H][DID_L][payload...]
        if pci == 0x00 and len(data) >= 5 and data[2] == 0x62 and data[3] == did_h and data[4] == did_l:
            L = data[1] & 0x0F
            return tuple(data[5 : 5 + L])
        # First Frame: [EA_RSP][0x10][LEN][0x62][DID_H][DID_L][payload...]
        if pci == 0x10 and len(data) >= 6 and data[3] == 0x62 and data[4] == did_h and data[5] == did_l:
            _pcan_write(api, tx_id, [ea_req, 0x30, 0x00, 0x00, 0, 0, 0, 0])
            payload = list(data[6:])
            tf = time.monotonic()
            while time.monotonic() - tf < timeout:
                ok2, arbid2, dlc2, data2, _ = _pcan_read_once(api)
                if not ok2 or arbid2 != rx_id or data2 is None or len(data2) < 2 or data2[0] != ea_rsp:
                    continue
                if (data2[1] & 0xF0) == 0x20:
                    payload += list(data2[2:])
                    tf = time.monotonic()
                else:
                    break
            return tuple(payload)
    raise TimeoutError(f"UDS 0x22 Timeout (DID 0x{did:04X})")


class DetectorBase:
    name = "BASE"

    def reset(self) -> None:
        """Resets internal state before a new measurement begins."""

    def read_state(self, api: PCANBasicT, profile: Dict[str, int]) -> bool:
        """Return ``True`` when the watched event is currently active."""
        raise NotImplementedError


class LEDAnyOn(DetectorBase):
    name = "LED_ANY_ON"

    def read_state(self, api: PCANBasicT, profile: Dict[str, int]) -> bool:
        payload = uds_read_by_id(api, 0xD631, **profile)
        # 10 Paare (mA, %) -> Ereignis bei irgendeiner LED >0% oder >=50mA
        for i in range(0, min(len(payload), 20), 2):
            milliamp = payload[i] * 10
            pct = payload[i + 1] if i + 1 < len(payload) else 0
            if pct > 0 or milliamp >= 50:
                return True
        return False


class AHLMove(DetectorBase):
    name = "AHL_MOVE"

    def __init__(self, delta: float = 1.0):
        self.prev: Optional[float] = None
        self.delta = float(delta)

    def reset(self) -> None:
        self.prev = None

    def read_state(self, api: PCANBasicT, profile: Dict[str, int]) -> bool:
        payload = uds_read_by_id(api, 0xD663, **profile)
        if len(payload) < 2:
            return False
        val = ((payload[0] << 8) | payload[1]) / 10.0
        if self.prev is None:
            self.prev = val
            return False
        trig = abs(val - self.prev) >= self.delta
        self.prev = val
        return trig


class LWRMove(DetectorBase):
    name = "LWR_MOVE"

    def __init__(self, delta: float = 0.5):
        self.prev: Optional[float] = None
        self.delta = float(delta)

    def reset(self) -> None:
        self.prev = None

    def read_state(self, api: PCANBasicT, profile: Dict[str, int]) -> bool:
        payload = uds_read_by_id(api, 0xD63B, **profile)
        if not payload:
            return False
        val = payload[0] / 10.0
        if self.prev is None:
            self.prev = val
            return False
        trig = abs(val - self.prev) >= self.delta
        self.prev = val
        return trig


class UDSCustom(DetectorBase):
    name = "UDS_CUSTOM"

    _OPS = {
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
    }

    def __init__(self, did: int, op: str = ">", th: float = 0.0, index: int = 0):
        if op not in self._OPS:
            raise ValueError(f"Ungültiger Vergleichsoperator: {op}")
        self.did = int(did)
        self.op = op
        self.th = float(th)
        self.index = int(index)

    def read_state(self, api: PCANBasicT, profile: Dict[str, int]) -> bool:
        payload = uds_read_by_id(api, self.did, **profile)
        value = payload[self.index] if len(payload) > self.index else 0
        return self._OPS[self.op](int(value), self.th)


class CanBit(DetectorBase):
    name = "CAN_BIT"

    def __init__(self, can_id: int, byte_idx: int, mask: int, value: int):
        self.cid = int(can_id)
        self.byte = int(byte_idx)
        self.mask = int(mask)
        self.value = int(value)
        self._last = 0

    def reset(self) -> None:
        self._last = 0

    def read_state(self, api: "PCANBasic", profile: Dict[str, int]) -> bool:
        """„Ground Truth“ direkt vom CAN: Bit wird == value."""

        target_value = self.value & self.mask
        t0 = time.monotonic()
        while time.monotonic() - t0 < 0.2:
            ok, arbid, dlc, data, _ = _pcan_read_once(api)
            if ok and arbid == self.cid and dlc is not None and data is not None and self.byte < dlc:
                masked = data[self.byte] & self.mask
                if masked == target_value:
                    rising = self._last != target_value
                    self._last = masked
                    return rising
                self._last = masked
        return False


DETECTORS = {
    LEDAnyOn.name: LEDAnyOn,
    AHLMove.name: AHLMove,
    LWRMove.name: LWRMove,
    UDSCustom.name: UDSCustom,
    CanBit.name: CanBit,
}


RING_SECONDS = 5.0
PRE_WIN = 0.300  # 300 ms vor Ereignis
POST_WIN = 0.050  # 50 ms nach Ereignis


@dataclass
class TriggerFinderResult:
    id_hits: Counter
    bit_hits: Counter


LogCallback = Callable[[str], None]


class TriggerFinderRunner:
    """Executes the trigger finder inside a background thread."""

    def __init__(
        self,
        *,
        profile: str,
        target: str,
        log_callback: LogCallback,
        uds_did: Optional[int] = None,
        uds_op: str = ">",
        uds_th: float = 0.0,
        uds_index: int = 0,
        can_id: Optional[int] = None,
        can_byte: Optional[int] = None,
        can_mask: Optional[int] = None,
        can_value: Optional[int] = None,
    ) -> None:
        self.profile_name = profile
        self.target_name = target
        self.log_callback = log_callback
        self.uds_params = dict(did=uds_did, op=uds_op, th=uds_th, index=uds_index)
        self.can_params = dict(can_id=can_id, can_byte=can_byte, can_mask=can_mask, can_value=can_value)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ---- Public control -------------------------------------------------

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="TriggerFinderThread", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- Internal helpers -----------------------------------------------

    def _log(self, message: str) -> None:
        try:
            self.log_callback(message)
        except Exception:
            pass

    def _instantiate_detector(self) -> DetectorBase:
        det_cls = DETECTORS.get(self.target_name)
        if det_cls is None:
            raise ValueError(f"Unbekanntes Target: {self.target_name}")

        if det_cls is UDSCustom:
            if self.uds_params["did"] is None:
                raise ValueError("Bitte eine UDS DID angeben.")
            return det_cls(  # type: ignore[call-arg]
                self.uds_params["did"],
                op=self.uds_params["op"],
                th=self.uds_params["th"],
                index=self.uds_params["index"],
            )
        if det_cls is CanBit:
            if None in self.can_params.values():
                raise ValueError("Bitte CAN-ID, Byte, Maske und Wert angeben.")
            return det_cls(  # type: ignore[call-arg]
                self.can_params["can_id"],
                self.can_params["can_byte"],
                self.can_params["can_mask"],
                self.can_params["can_value"],
            )
        return det_cls()

    def _run(self) -> None:
        if PCANBasic is None:
            self._log("PCANBasic konnte nicht importiert werden. Bitte Treiber/SDK installieren.")
            return

        profile = PROFILES.get(self.profile_name)
        if profile is None:
            self._log(f"Unbekanntes Profil: {self.profile_name}")
            return

        try:
            detector = self._instantiate_detector()
        except Exception as exc:
            self._log(f"Fehler beim Initialisieren des Targets: {exc}")
            return

        api = PCANBasic()
        if api.Initialize(CHANNEL, BAUD) != PCAN_ERROR_OK:
            self._log("PCAN Initialisierung fehlgeschlagen (Kanal/Baudrate prüfen).")
            return

        ring: Deque[Tuple[float, int, int, bytes]] = deque()
        id_hits: Counter = Counter()
        bit_hits: Counter = Counter()

        detector.reset()
        self._running = True
        self._log(f"Starte Target: {detector.name} – Profil: {self.profile_name}")
        self._log("Schalte das gewählte Feature mehrmals an/aus … (Stopp beendet)")

        last_state = False
        try:
            while not self._stop_event.is_set():
                ok, arbid, dlc, data, ts = _pcan_read_once(api)
                if ok and arbid is not None and dlc is not None and data is not None and ts is not None:
                    ring.append((ts, arbid, dlc, bytes(data)))
                    t_cut = ts - RING_SECONDS
                    while ring and ring[0][0] < t_cut:
                        ring.popleft()

                try:
                    state = detector.read_state(api, profile)
                except TimeoutError as exc:
                    self._log(f"UDS Timeout: {exc}")
                    state = False
                except Exception as exc:  # pragma: no cover - hardware dependent
                    self._log(f"Fehler beim Lesen des Ground-Truth-Signals: {exc}")
                    state = False

                if state and not last_state:
                    t_event = time.monotonic()
                    t_start, t_end = t_event - PRE_WIN, t_event + POST_WIN

                    before: Dict[int, bytes] = {}
                    for ts_prev, can_id, _dlc_prev, data_prev in ring:
                        if ts_prev < t_start:
                            before[can_id] = data_prev

                    in_win = [frame for frame in ring if t_start <= frame[0] <= t_end]
                    seen_ids = set()
                    for _ts_frame, can_id, _dlc_frame, data_frame in in_win:
                        seen_ids.add(can_id)
                        prev = before.get(can_id)
                        if prev is None or len(prev) != len(data_frame):
                            continue
                        xor = bytes(a ^ b for a, b in zip(prev, data_frame))
                        for idx, byte in enumerate(xor):
                            if byte == 0:
                                continue
                            for bit in range(8):
                                mask = 1 << bit
                                if (prev[idx] & mask) == 0 and (data_frame[idx] & mask) != 0:
                                    bit_hits[(can_id, idx, bit)] += 1
                    for can_id in seen_ids:
                        id_hits[can_id] += 1

                    self._log("")
                    self._log(f"Ereignis @ {t_event:.3f}s  – Top IDs:")
                    for cid, cnt in id_hits.most_common(5):
                        self._log(f"  ID 0x{cid:03X}: {cnt}")
                    self._log("Top Bits (ID,Byte,Bit):")
                    for (cid, byte_idx, bit), cnt in bit_hits.most_common(5):
                        self._log(f"  0x{cid:03X}, B{byte_idx}, bit{bit}: {cnt}")

                last_state = state
                time.sleep(0.01)
        finally:
            try:
                api.Uninitialize(CHANNEL)
            except Exception:  # pragma: no cover - hardware dependent
                pass
            self._running = False

        self._log("")
        self._log("=== Endgültiges Ranking ===")
        for cid, cnt in id_hits.most_common():
            self._log(f"ID 0x{cid:03X}: {cnt}")
        self._log("")
        self._log("Top 20 Byte/Bit-Kandidaten:")
        for (cid, byte_idx, bit), cnt in bit_hits.most_common(20):
            self._log(f"ID 0x{cid:03X}  Byte {byte_idx}  Bit {bit}  -> {cnt} Treffer")
        self._log("Trigger Finder beendet.")

