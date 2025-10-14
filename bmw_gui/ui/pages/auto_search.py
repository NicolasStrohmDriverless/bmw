from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import List, Tuple

import can  # type: ignore

from can_utils import open_bus, print_tx, print_rx


SA_ENTRIES: List[Tuple[str, str]] = [
    ("0230", "Zusatzumfang EU-spezifisch"),
    ("0249", "Multifunktion für Lenkrad"),
    ("02D6", "BMW i LM Rad Sternspeiche 427"),
    ("02PA", "Radschraubensicherung"),
    ("02VB", "Reifendruckanzeige"),
    ("0428", "Warndreieck und Verbandstasche"),
    ("0430", "Innen-/Aussensp. mit Abblendautomatik"),
    ("0442", "Getränkehalter"),
    ("0473", "Armlehne vorne"),
    ("0493", "Ablagenpaket"),
    ("04EX", "Interieuroberfläche andesitsilber matt"),
    ("04U6", "Schnellladen Wechselstrom mehrphasig"),
    ("04U7", "Schnellladen Gleichstrom"),
    ("0521", "Regensensor"),
    ("0534", "Klimaautomatik"),
    ("0544", "Geschwindigkeitsregelung mit Bremsfunkt."),
    ("0548", "Kilometertacho"),
    ("0570", "Stärkere Stromversorgung"),
    ("05DA", "Deaktivierung Airbag Beifahrer"),
    ("0609", "Navigationssystem Professional"),
    ("06AC", "Intelligenter Notruf"),
    ("06AE", "TELESERVICES"),
    ("06AK", "Connected Drive Services"),
    ("06AM", "Real-Time Traffic Information"),
    ("06AN", "Concierge Services"),
    ("06AU", "Connected eDrive services"),
    ("06NW", "Telefonie mit Wireless Charging"),
    ("06WD", "WLAN Hotspot"),
    ("07RS", "Paket Comfort"),
    ("0801", "DEUTSCHLAND-AUSFUEHRUNG"),
    ("0851", "Sprachversion deutsch"),
    ("0879", "Bordliteratur deutsch"),
    ("08R9", "Kältemittel R1234yf"),
    ("09BD", "Business Package"),
]


PROFILE_PRESETS = {
    "Links": dict(tx_id=0x06F1, rx_id=0x0643, ea_req=0x43, ea_rsp=0xF1),
    "Rechts": dict(tx_id=0x06F2, rx_id=0x0644, ea_req=0x44, ea_rsp=0xF1),
}


class AutoSearchPage(ttk.Frame):
    def __init__(self, parent, app):  # app: THNApp
        super().__init__(parent, style="Card.TFrame")
        self.app = app

        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._tree_items: List[str] = []
        self._results: List[dict] = []

        self._build_ui()
        self._populate_tree()
        self._process_queue()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=24, style="Card.TFrame")
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="Card.TFrame")
        header.pack(fill="x")

        self.head = ttk.Label(
            header,
            text="Automatische Suche",
            style="Card.TLabel",
            font=("Segoe UI", 16, "bold"),
        )
        self.head.pack(side="left")

        self.back_btn = ttk.Button(header, text="← Zurück", command=lambda: self.app.show("TestPage"))
        try:
            self.back_btn.configure(style="Red.TButton")
        except Exception:
            pass
        self.back_btn.pack(side="right")

        form = ttk.Frame(outer, padding=(0, 12), style="Card.TFrame")
        form.pack(fill="x")

        profile_row = ttk.Frame(form, style="Card.TFrame")
        profile_row.pack(fill="x", pady=4)
        ttk.Label(profile_row, text="Profil:", style="Card.TLabel").pack(side="left")
        self.profile_var = tk.StringVar(value="Links")
        self.profile_combo = ttk.Combobox(
            profile_row,
            textvariable=self.profile_var,
            values=list(PROFILE_PRESETS.keys()),
            state="readonly",
            width=12,
        )
        self.profile_combo.pack(side="left", padx=(8, 0))
        self.profile_combo.bind("<<ComboboxSelected>>", lambda *_: self._apply_profile())

        grid = ttk.Frame(form, style="Card.TFrame")
        grid.pack(fill="x", pady=4)

        ttk.Label(grid, text="TX-ID (hex):", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.tx_entry = ttk.Entry(grid, width=10)
        self.tx_entry.grid(row=0, column=1, padx=6, sticky="w")

        ttk.Label(grid, text="RX-ID (hex):", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        self.rx_entry = ttk.Entry(grid, width=10)
        self.rx_entry.grid(row=0, column=3, padx=6, sticky="w")

        ttk.Label(grid, text="EA Anfrage:", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.ea_req_entry = ttk.Entry(grid, width=10)
        self.ea_req_entry.grid(row=1, column=1, padx=6, sticky="w", pady=(6, 0))

        ttk.Label(grid, text="EA Antwort:", style="Card.TLabel").grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.ea_rsp_entry = ttk.Entry(grid, width=10)
        self.ea_rsp_entry.grid(row=1, column=3, padx=6, sticky="w", pady=(6, 0))

        ttk.Label(grid, text="Timeout (s):", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.timeout_entry = ttk.Entry(grid, width=10)
        self.timeout_entry.insert(0, "1.0")
        self.timeout_entry.grid(row=2, column=1, padx=6, sticky="w", pady=(6, 0))

        btn_row = ttk.Frame(form, style="Card.TFrame")
        btn_row.pack(fill="x", pady=(8, 0))

        self.start_btn = ttk.Button(btn_row, text="Start", command=self._start_search)
        self.stop_btn = ttk.Button(btn_row, text="Stopp", command=self._stop_search, state="disabled")
        self.save_btn = ttk.Button(btn_row, text="Speichern…", command=self._save_results)
        try:
            self.start_btn.configure(style="Red.TButton")
            self.stop_btn.configure(style="Red.TButton")
            self.save_btn.configure(style="Red.TButton")
        except Exception:
            pass
        self.start_btn.pack(side="left", padx=(0, 8), ipadx=12, ipady=6)
        self.stop_btn.pack(side="left", padx=(0, 8), ipadx=12, ipady=6)
        self.save_btn.pack(side="left", padx=(0, 8), ipadx=12, ipady=6)

        self.status = ttk.Label(form, text="Bereit", style="Card.TLabel")
        self.status.pack(fill="x", pady=(12, 0))

        table_frame = ttk.Frame(outer, style="Card.TFrame")
        table_frame.pack(fill="both", expand=True, pady=(12, 0))

        columns = ("sa", "desc", "status", "response")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
        self.tree.heading("sa", text="SA")
        self.tree.heading("desc", text="Bezeichnung")
        self.tree.heading("status", text="Status")
        self.tree.heading("response", text="Antwort(en)")
        self.tree.column("sa", width=70, anchor="center")
        self.tree.column("desc", width=240, anchor="w")
        self.tree.column("status", width=110, anchor="center")
        self.tree.column("response", width=420, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        vsb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=vsb.set)

        self._apply_profile()

    def _populate_tree(self) -> None:
        for item in self.tree.get_children(""):
            self.tree.delete(item)
        self._tree_items.clear()
        self._results = []
        for sa, desc in SA_ENTRIES:
            iid = self.tree.insert("", "end", values=(sa, desc, "Bereit", ""))
            self._tree_items.append(iid)
            self._results.append(dict(sa=sa, desc=desc, status="Bereit", responses=[]))

    # --------------------------------------------------------------- Actions

    def _set_running_state(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for entry in (self.tx_entry, self.rx_entry, self.ea_req_entry, self.ea_rsp_entry, self.timeout_entry, self.profile_combo):
            entry.configure(state=state)
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def _start_search(self) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("Automatische Suche", "Die Suche läuft bereits.")
            return

        try:
            tx_id = self._parse_int(self.tx_entry.get(), "TX-ID")
            rx_id = self._parse_int(self.rx_entry.get(), "RX-ID")
            ea_req = self._parse_int(self.ea_req_entry.get(), "EA Anfrage")
            ea_rsp = self._parse_int(self.ea_rsp_entry.get(), "EA Antwort")
            timeout = float(self.timeout_entry.get())
        except ValueError as exc:
            messagebox.showerror("Automatische Suche", str(exc))
            return

        if timeout <= 0:
            messagebox.showerror("Automatische Suche", "Timeout muss größer als 0 sein.")
            return

        self._populate_tree()
        self._stop_event.clear()
        self._set_running_state(True)
        self.status.configure(text="Suche gestartet …")

        self._worker = threading.Thread(
            target=self._worker_run,
            args=(tx_id, rx_id, ea_req, ea_rsp, timeout),
            daemon=True,
        )
        self._worker.start()

    def _stop_search(self) -> None:
        if self._worker and self._worker.is_alive():
            self._stop_event.set()
            self.status.configure(text="Stop angefordert …")

    # --------------------------------------------------------------- Worker

    def _worker_run(self, tx_id: int, rx_id: int, ea_req: int, ea_rsp: int, timeout: float) -> None:
        bus = None
        try:
            bus = open_bus()
        except Exception as exc:
            self._queue.put(("error", f"Bus konnte nicht geöffnet werden: {exc}"))
            self._queue.put(("done", False))
            return

        try:
            for idx, (sa, _desc) in enumerate(SA_ENTRIES):
                if self._stop_event.is_set():
                    break

                self._queue.put(("status", f"Prüfe SA {sa} …"))

                try:
                    did = self._parse_int(sa, "SA")
                except ValueError:
                    self._queue.put(("item_error", idx, "Ungültige SA"))
                    continue

                payload = bytes([
                    ea_req & 0xFF,
                    0x03,
                    0x22,
                    (did >> 8) & 0xFF,
                    did & 0xFF,
                    0x00,
                    0x00,
                    0x00,
                ])

                try:
                    msg = can.Message(arbitration_id=tx_id, is_extended_id=False, data=payload)
                    bus.send(msg)
                    try:
                        print_tx(msg)
                    except Exception:
                        pass
                except Exception as exc:
                    self._queue.put(("item_error", idx, f"Senden fehlgeschlagen: {exc}"))
                    continue

                responses: List[str] = []
                end_t = time.time() + timeout
                while not self._stop_event.is_set() and time.time() < end_t:
                    try:
                        resp = bus.recv(timeout=0.05)
                    except Exception as exc:
                        self._queue.put(("item_error", idx, f"Empfang fehlgeschlagen: {exc}"))
                        break
                    if resp is None:
                        continue
                    try:
                        print_rx(resp)
                    except Exception:
                        pass
                    resp_text = (
                        f"ID=0x{resp.arbitration_id:03X} DLC={resp.dlc} "
                        f"Data={' '.join(f'{b:02X}' for b in resp.data)}"
                    )
                    responses.append(resp_text)
                    if resp.arbitration_id == rx_id:
                        if len(resp.data) == 0 or resp.data[0] == (ea_rsp & 0xFF):
                            break

                status = "Antwort" if responses else "Timeout"
                self._queue.put(("item_result", idx, status, responses))

                if self._stop_event.is_set():
                    break

        except Exception as exc:  # pragma: no cover - defensive
            self._queue.put(("error", f"Unerwarteter Fehler: {exc}"))
        finally:
            if bus is not None:
                try:
                    bus.shutdown()
                except Exception:
                    pass
            self._queue.put(("done", not self._stop_event.is_set()))

    # ---------------------------------------------------------- Queue/State

    def _process_queue(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "status":
                    self.status.configure(text=item[1])
                elif kind == "item_result":
                    _, idx, status, responses = item
                    self._update_result(idx, status, responses)
                elif kind == "item_error":
                    _, idx, message = item
                    self._update_result(idx, "Fehler", [message])
                elif kind == "error":
                    _, msg = item
                    self.status.configure(text="Fehler – Details siehe Meldung")
                    messagebox.showerror("Automatische Suche", msg)
                elif kind == "done":
                    _, completed = item
                    if completed:
                        self.status.configure(text="Suche abgeschlossen.")
                    else:
                        self.status.configure(text="Beendet.")
                    self._set_running_state(False)
        except queue.Empty:
            pass
        finally:
            self.after(120, self._process_queue)

    def _update_result(self, idx: int, status: str, responses: List[str]) -> None:
        if 0 <= idx < len(self._tree_items):
            iid = self._tree_items[idx]
            response_text = " | ".join(responses)
            values = list(self.tree.item(iid, "values"))
            if len(values) >= 4:
                values[2] = status
                values[3] = response_text
            self.tree.item(iid, values=values)
            self._results[idx]["status"] = status
            self._results[idx]["responses"] = responses

    # --------------------------------------------------------------- Helpers

    def _parse_int(self, value: str, label: str) -> int:
        s = (value or "").strip()
        if not s:
            raise ValueError(f"{label} darf nicht leer sein.")
        try:
            return int(s, 16)
        except ValueError as exc:
            raise ValueError(f"{label} muss eine Hex-Zahl sein.") from exc

    def _apply_profile(self) -> None:
        preset = PROFILE_PRESETS.get(self.profile_var.get())
        if not preset:
            return
        self.tx_entry.delete(0, tk.END)
        self.tx_entry.insert(0, f"{preset['tx_id']:03X}")
        self.rx_entry.delete(0, tk.END)
        self.rx_entry.insert(0, f"{preset['rx_id']:03X}")
        self.ea_req_entry.delete(0, tk.END)
        self.ea_req_entry.insert(0, f"{preset['ea_req']:02X}")
        self.ea_rsp_entry.delete(0, tk.END)
        self.ea_rsp_entry.insert(0, f"{preset['ea_rsp']:02X}")

    def _save_results(self) -> None:
        if not self._results:
            messagebox.showinfo("Automatische Suche", "Keine Ergebnisse zum Speichern.")
            return
        path = filedialog.asksaveasfilename(
            title="Ergebnisse speichern",
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"), ("Textdatei", "*.txt")),
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("SA;Bezeichnung;Status;Antwort\n")
                for entry in self._results:
                    response = " | ".join(entry.get("responses", []))
                    sa = entry.get("sa", "")
                    desc = entry.get("desc", "")
                    status = entry.get("status", "")
                    sa_q = '"' + str(sa).replace('"', '""') + '"'
                    desc_q = '"' + str(desc).replace('"', '""') + '"'
                    status_q = '"' + str(status).replace('"', '""') + '"'
                    resp_q = '"' + response.replace('"', '""') + '"'
                    f.write(f"{sa_q};{desc_q};{status_q};{resp_q}\n")
            messagebox.showinfo("Automatische Suche", "Ergebnisse gespeichert.")
        except Exception as exc:
            messagebox.showerror("Automatische Suche", f"Speichern fehlgeschlagen: {exc}")

    # -------------------------------------------------------------- Lifecycle

    def destroy(self) -> None:  # type: ignore[override]
        self._stop_event.set()
        super().destroy()

    def apply_theme(self, bg, fg, card, paint_button):
        self.configure(style="Card.TFrame")
        for child in self.winfo_children():
            if isinstance(child, ttk.Frame):
                child.configure(style="Card.TFrame")
        self.head.configure(style="Card.TLabel")
        self.status.configure(style="Card.TLabel")
        try:
            self.back_btn.configure(style="Red.TButton")
            self.start_btn.configure(style="Red.TButton")
            self.stop_btn.configure(style="Red.TButton")
            self.save_btn.configure(style="Red.TButton")
        except Exception:
            pass
