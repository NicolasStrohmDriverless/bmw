from __future__ import annotations
import time
import threading
from tkinter import ttk, messagebox
from typing import Dict, List, Optional, Tuple

from sequences import GEAR_LEVER_STATES
from can_utils import open_bus, make_msg, print_tx, print_rx


class GearLeverPage(ttk.Frame):
    def __init__(self, parent, app):  # app: THNApp
        super().__init__(parent, style="Card.TFrame")
        self.app = app

        self._rows: List[ttk.Frame] = []
        self._buttons: List[ttk.Button] = []

        top = ttk.Frame(self, padding=16, style="Card.TFrame")
        top.pack(fill="x")
        self._rows.append(top)

        self.head = ttk.Label(top, text="Ganghebel - Simulation", style="Card.TLabel", font=("Segoe UI", 16, "bold"))
        self.head.pack(side="left")

        self.close_btn = ttk.Button(
            top,
            text="<< Zurueck",
            command=lambda: app.show("MainMenu"),
            style="Red.TButton",
        )
        self.close_btn.pack(side="right")
        self._buttons.append(self.close_btn)

        body = ttk.Frame(self, padding=24, style="Card.TFrame")
        body.pack(expand=True, fill="both")
        self._rows.append(body)

        desc = ttk.Label(
            body,
            text="Ein Klick sendet den jeweiligen Zustand als Einzel-Frame.",
            style="Card.TLabel",
        )
        desc.pack(anchor="w", pady=(0, 12))

        for name, can_id, data_hex in GEAR_LEVER_STATES:
            row = ttk.Frame(body, style="Card.TFrame")
            row.pack(fill="x", pady=6)
            self._rows.append(row)

            dlc = len(data_hex) // 2
            spaced = " ".join(data_hex[i : i + 2] for i in range(0, len(data_hex), 2))
            label_text = f"{name}\nID 0x{can_id.upper()}  DLC {dlc}  Data {spaced}"
            lbl = ttk.Label(row, text=label_text, style="Card.TLabel", justify="left")
            lbl.pack(side="left", expand=True, fill="x")

            btn = ttk.Button(
                row,
                text="Senden",
                command=lambda args=(name, can_id, data_hex): self._send_state(*args),
                style="Red.TButton",
            )
            btn.pack(side="right", padx=(16, 0))
            self._buttons.append(btn)

        self.status = ttk.Label(self, text="", style="Card.TLabel")
        self.status.pack(pady=(0, 16))

        # Prepare lookup for received CAN frames -> state names
        self._state_lookup: Dict[Tuple[int, str], str] = {}
        for name, can_id, data_hex in GEAR_LEVER_STATES:
            try:
                arb_id = int(can_id, 16)
            except ValueError:
                continue
            self._state_lookup[(arb_id, data_hex.upper())] = name

        # Background listener for incoming CAN messages
        self._listener_stop = threading.Event()
        self._listener_thread: Optional[threading.Thread] = None
        self.after(0, self._ensure_listener_running)

    def apply_theme(self, bg, fg, card, paint_button):
        self.configure(style="Card.TFrame")
        for row in self._rows:
            row.configure(style="Card.TFrame")
        self.head.configure(style="Card.TLabel")
        self.status.configure(style="Card.TLabel")
        for btn in self._buttons:
            try:
                paint_button(btn)
            except Exception:
                try:
                    btn.configure(style="Red.TButton")
                except Exception:
                    pass

    def _send_state(self, name: str, can_id_hex: str, data_hex: str):
        self.status.configure(text=f"{name}: sende ...")
        self.update_idletasks()
        try:
            bus = open_bus()
        except Exception as e:
            self.status.configure(text=f"{name}: Bus nicht verfuegbar.")
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

            suffix = "Antwort empfangen." if recv_found else "gesendet (keine Antwort)."
            self.status.configure(text=f"{name}: {suffix}")
        except Exception as e:
            self.status.configure(text=f"{name}: Fehler beim Senden.")
            messagebox.showerror("CAN Fehler", f"Senden fehlgeschlagen:\n{e}")
        finally:
            try:
                bus.shutdown()
            except Exception:
                pass

    # ---- CAN Receive Listener -------------------------------------------------

    def _ensure_listener_running(self) -> None:
        if self._listener_thread and self._listener_thread.is_alive():
            return
        self._listener_stop.clear()
        t = threading.Thread(target=self._listen_for_states, name="GearCANListener", daemon=True)
        self._listener_thread = t
        t.start()

    def _listen_for_states(self) -> None:
        bus = None
        try:
            while not self._listener_stop.is_set():
                if bus is None:
                    try:
                        bus = open_bus()
                    except Exception as e:
                        self._post_status(f"CAN Listener: Bus nicht verfuegbar ({e})")
                        if self._listener_stop.wait(2.0):
                            break
                        continue

                try:
                    msg = bus.recv(timeout=0.25)
                except Exception as e:
                    self._post_status(f"CAN Listener: Fehler ({e})")
                    try:
                        bus.shutdown()
                    except Exception:
                        pass
                    bus = None
                    if self._listener_stop.wait(1.0):
                        break
                    continue

                if msg is None:
                    continue

                try:
                    data = bytes(msg.data[: msg.dlc])  # type: ignore[index]
                except Exception:
                    try:
                        data = bytes(msg.data)
                    except Exception:
                        continue

                data_hex = data.hex().upper()
                state_name = self._state_lookup.get((int(getattr(msg, "arbitration_id", 0)), data_hex))
                if state_name:
                    self._post_status(f"{state_name}: Nachricht empfangen.")
        finally:
            if bus is not None:
                try:
                    bus.shutdown()
                except Exception:
                    pass

    def _post_status(self, text: str) -> None:
        try:
            self.after(0, lambda: self.status.configure(text=text))
        except Exception:
            pass

    def destroy(self) -> None:
        try:
            self._listener_stop.set()
            if self._listener_thread and self._listener_thread.is_alive():
                self._listener_thread.join(timeout=0.5)
        except Exception:
            pass
        super().destroy()
