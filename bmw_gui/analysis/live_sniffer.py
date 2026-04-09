from __future__ import annotations

import queue
import threading
import time
from typing import Optional

from .models import RawCanFrame


class LiveSniffer:
    """Background, read-only CAN frame reader.

    The worker only calls ``recv`` on the CAN bus and never transmits frames.
    """

    def __init__(self, bus_factory):
        self._bus_factory = bus_factory
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self, out_queue: "queue.Queue[tuple]") -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, args=(out_queue,), daemon=True, name="LiveSniffer")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self, out_queue: "queue.Queue[tuple]") -> None:
        bus = None
        try:
            bus = self._bus_factory()
            out_queue.put(("sniffer_status", "Live-Sniffing aktiv (read-only)"))
            while not self._stop_event.is_set():
                msg = bus.recv(timeout=0.1)
                if msg is None:
                    continue

                timestamp = getattr(msg, "timestamp", None)
                if timestamp is None:
                    timestamp = time.time()

                try:
                    payload = bytes(msg.data[: msg.dlc])
                except Exception:
                    payload = bytes(msg.data)

                frame = RawCanFrame(
                    timestamp=float(timestamp),
                    can_id=int(msg.arbitration_id),
                    dlc=int(msg.dlc),
                    data=payload,
                    source="live",
                    channel=str(getattr(msg, "channel", "")) if getattr(msg, "channel", None) is not None else "",
                )
                out_queue.put(("frame", frame))
        except Exception as exc:
            out_queue.put(("sniffer_error", str(exc)))
        finally:
            if bus is not None:
                try:
                    bus.shutdown()
                except Exception:
                    pass
            out_queue.put(("sniffer_stopped", None))
