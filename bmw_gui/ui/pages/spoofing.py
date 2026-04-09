from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional, Set, Tuple

from can_utils import make_msg, open_bus, print_rx, print_tx

SequenceItem = Tuple[str, str, Optional[float]]


class SpoofingPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, style="Card.TFrame")
        self.app = app

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._worker_stop = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        top = ttk.Frame(self, padding=16, style="Card.TFrame")
        top.pack(fill="x")

        self.head = ttk.Label(top, text="Spoofing", style="Card.TLabel", font=("Segoe UI", 16, "bold"))
        self.head.pack(side="left")

        self.back_btn = ttk.Button(top, text="← Zurück", command=lambda: app.show("AutoSearchPage"))
        try:
            self.back_btn.configure(style="Red.TButton")
        except Exception:
            pass
        self.back_btn.pack(side="right")

        body = ttk.Frame(self, padding=24, style="Card.TFrame")
        body.pack(expand=True, fill="both")

        intro = ttk.Label(
            body,
            text=(
                "CAN-Frames als Sequenz senden, RX-Reaktionen mit Zeitstempeln aufzeichnen "
                "und den Lauf per Stop abbrechen."
            ),
            style="Card.TLabel",
        )
        intro.pack(anchor="w", pady=(0, 12))

        dbc_row = ttk.Frame(body, style="Card.TFrame")
        dbc_row.pack(fill="x", pady=6)
        self.use_dbc_ids_var = tk.BooleanVar(value=True)
        self.use_dbc_ids_cb = ttk.Checkbutton(
            dbc_row,
            text="Alle IDs aus DBC verwenden (wenn Sequenz leer)",
            variable=self.use_dbc_ids_var,
        )
        self.use_dbc_ids_cb.pack(side="left")

        dbc_path_row = ttk.Frame(body, style="Card.TFrame")
        dbc_path_row.pack(fill="x", pady=6)
        ttk.Label(dbc_path_row, text="DBC-Datei:", style="Card.TLabel").pack(side="left")
        self.entry_dbc_path = ttk.Entry(dbc_path_row, width=64)
        self.entry_dbc_path.insert(0, str(self._default_dbc_path()))
        self.entry_dbc_path.pack(side="left", padx=8, fill="x", expand=True)
        self.browse_dbc_btn = ttk.Button(dbc_path_row, text="…", width=4, command=self._browse_dbc_path)
        self.browse_dbc_btn.pack(side="left")

        id_row = ttk.Frame(body, style="Card.TFrame")
        id_row.pack(fill="x", pady=6)
        ttk.Label(id_row, text="CAN-ID (hex):", style="Card.TLabel").pack(side="left")
        self.entry_id = ttk.Entry(id_row, width=18)
        self.entry_id.insert(0, "65E")
        self.entry_id.pack(side="left", padx=8)

        data_row = ttk.Frame(body, style="Card.TFrame")
        data_row.pack(fill="x", pady=6)
        ttk.Label(data_row, text="Daten (hex, ohne Leerzeichen):", style="Card.TLabel").pack(side="left")
        self.entry_data = ttk.Entry(data_row, width=48)
        self.entry_data.insert(0, "F1210001FFFFFFFF")
        self.entry_data.pack(side="left", padx=8)

        seq_label = ttk.Label(
            body,
            text="Sequenz (optional, eine Zeile pro Frame: ID DATA [Pause_ms])",
            style="Card.TLabel",
        )
        seq_label.pack(anchor="w", pady=(8, 4))

        self.seq_text = tk.Text(body, height=7, wrap="none")
        self.seq_text.insert(
            "1.0",
            "# Leer lassen = DBC-IDs (falls aktiviert) oder Einzel-Frame aus Feldern oben\n"
            "# Beispiele:\n"
            "# 65E F1210001FFFFFFFF\n"
            "# 6F1 2902100300000000 50\n",
        )
        self.seq_text.pack(fill="x", pady=(0, 8))

        hint = ttk.Label(
            body,
            text=(
                "0 Wiederholungen = Dauerschleife bis Stop. Die Pause pro Zeile "
                "überschreibt das globale Intervall."
            ),
            style="Card.TLabel",
        )
        hint.pack(anchor="w", pady=(0, 10))

        param_row = ttk.Frame(body, style="Card.TFrame")
        param_row.pack(fill="x", pady=6)
        ttk.Label(param_row, text="Wiederholungen:", style="Card.TLabel").pack(side="left")
        self.entry_repeat = ttk.Entry(param_row, width=8)
        self.entry_repeat.insert(0, "0")
        self.entry_repeat.pack(side="left", padx=8)

        ttk.Label(param_row, text="Intervall zwischen Frames (ms):", style="Card.TLabel").pack(side="left")
        self.entry_delay = ttk.Entry(param_row, width=8)
        self.entry_delay.insert(0, "20")
        self.entry_delay.pack(side="left", padx=8)

        ttk.Label(param_row, text="RX-Fenster je Frame (ms):", style="Card.TLabel").pack(side="left")
        self.entry_rx = ttk.Entry(param_row, width=8)
        self.entry_rx.insert(0, "250")
        self.entry_rx.pack(side="left", padx=8)

        status_row = ttk.Frame(body, style="Card.TFrame")
        status_row.pack(fill="x", pady=6)
        ttk.Label(status_row, text="Status-Text:", style="Card.TLabel").pack(side="left")
        self.entry_status = ttk.Entry(status_row, width=36)
        self.entry_status.insert(0, "Mehrfachsendung mit RX-Mitschnitt")
        self.entry_status.pack(side="left", padx=8)

        btn_row = ttk.Frame(body, style="Card.TFrame")
        btn_row.pack(fill="x", pady=(14, 10))

        self.send_btn = ttk.Button(btn_row, text="Dauerlauf starten", command=self._start_run)
        self.stop_btn = ttk.Button(btn_row, text="Stop", command=self._stop_run)
        self.clear_btn = ttk.Button(btn_row, text="Log leeren", command=self._clear_log)
        try:
            self.send_btn.configure(style="Red.TButton")
            self.stop_btn.configure(style="Red.TButton")
            self.clear_btn.configure(style="Red.TButton")
            self.browse_dbc_btn.configure(style="Red.TButton")
        except Exception:
            pass
        self.send_btn.pack(side="left", padx=(0, 8), ipadx=16, ipady=8)
        self.stop_btn.pack(side="left", padx=(0, 8), ipadx=16, ipady=8)
        self.clear_btn.pack(side="left", ipadx=16, ipady=8)
        self.stop_btn.configure(state="disabled")

        self.status = ttk.Label(body, text="Bereit.", style="Card.TLabel")
        self.status.pack(fill="x", pady=(0, 8))

        log_container = ttk.Frame(body, style="Card.TFrame")
        log_container.pack(fill="both", expand=True)

        self.log_text = tk.Text(log_container, height=16, wrap="word", state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(log_container, orient="vertical", command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)

        self.after(100, self._drain_log_queue)

    @staticmethod
    def _default_dbc_path() -> Path:
        return Path(__file__).resolve().parents[3] / "bmw_e9x_e8x.dbc"

    def _browse_dbc_path(self) -> None:
        selected = filedialog.askopenfilename(
            title="DBC-Datei auswählen",
            filetypes=[("DBC-Datei", "*.dbc"), ("Alle Dateien", "*.*")],
        )
        if selected:
            self.entry_dbc_path.delete(0, tk.END)
            self.entry_dbc_path.insert(0, selected)

    def apply_theme(self, bg, fg, card, paint_button):
        self.configure(style="Card.TFrame")
        for child in self.winfo_children():
            if isinstance(child, ttk.Frame):
                child.configure(style="Card.TFrame")
        self.head.configure(style="Card.TLabel")
        self.status.configure(style="Card.TLabel")
        for widget in (self.seq_text, self.log_text):
            try:
                widget.configure(background=card, foreground=fg, insertbackground=fg)
            except Exception:
                pass
        for btn in (self.send_btn, self.stop_btn, self.clear_btn, self.back_btn, self.browse_dbc_btn):
            try:
                paint_button(btn)
            except Exception:
                try:
                    btn.configure(style="Red.TButton")
                except Exception:
                    pass

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _queue_log(self, text: str) -> None:
        self._log_queue.put(text)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                line = self._log_queue.get_nowait()
                self._append_log(line)
        except queue.Empty:
            pass
        except tk.TclError:
            return

        try:
            self.after(100, self._drain_log_queue)
        except tk.TclError:
            pass

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _parse_float_ms(self, value: str, label: str) -> float:
        try:
            parsed = float(value.strip().replace(",", "."))
        except ValueError as exc:
            raise ValueError(f"{label} muss eine Zahl in Millisekunden sein.") from exc
        if parsed < 0:
            raise ValueError(f"{label} darf nicht negativ sein.")
        return parsed / 1000.0

    @staticmethod
    def _normalize_can_id_token(value: str) -> str:
        token = value.strip().upper().replace("0X", "")
        if not token:
            raise ValueError("Leerer Hex-Wert.")
        int(token, 16)
        return token

    @staticmethod
    def _normalize_data_token(value: str) -> str:
        token = value.strip().upper().replace("0X", "")
        if not token:
            raise ValueError("Leerer Hex-Wert.")
        if len(token) % 2 != 0:
            raise ValueError("Hex-Werte muessen eine gerade Anzahl Zeichen haben.")
        int(token, 16)
        return token

    def _parse_dbc_ids(self, dbc_path: Path) -> List[str]:
        if not dbc_path.exists():
            raise ValueError(f"DBC-Datei nicht gefunden: {dbc_path}")

        ids: Set[int] = set()
        try:
            content = dbc_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ValueError(f"DBC-Datei kann nicht gelesen werden: {dbc_path}") from exc

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line.startswith("BO_"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                dec_id = int(parts[1])
            except ValueError:
                continue

            # Keep standard 11-bit IDs in this tool because messages are sent as standard CAN frames.
            if 0 <= dec_id <= 0x7FF:
                ids.add(dec_id)

        if not ids:
            raise ValueError("Keine standard 11-bit IDs in der DBC gefunden.")

        return [f"{can_id:03X}" for can_id in sorted(ids)]

    def _parse_sequence(self) -> Tuple[List[SequenceItem], Set[int], str]:
        raw_text = self.seq_text.get("1.0", tk.END)
        sequence: List[SequenceItem] = []

        for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue

            normalized = line.replace(";", " ").replace(",", " ")
            parts = [part for part in normalized.split() if part]
            if len(parts) < 2:
                raise ValueError(f"Zeile {line_number}: erwartet mindestens CAN-ID und Daten.")
            if len(parts) > 3:
                raise ValueError(f"Zeile {line_number}: Format ist ID DATA [Pause_ms].")

            can_id_text = self._normalize_can_id_token(parts[0])
            data_text = self._normalize_data_token(parts[1])
            data = bytes.fromhex(data_text)
            if len(data) > 8:
                raise ValueError(f"Zeile {line_number}: CAN Classic erlaubt maximal 8 Datenbytes.")

            pause_s: Optional[float] = None
            if len(parts) == 3:
                pause_s = self._parse_float_ms(parts[2], f"Pause in Zeile {line_number}")

            sequence.append((can_id_text, data_text, pause_s))

        if sequence:
            seq_ids = {int(can_id_text, 16) for can_id_text, _, _ in sequence}
            return sequence, seq_ids, "manuelle Sequenz"

        data_text = self._normalize_data_token(self.entry_data.get())
        if len(bytes.fromhex(data_text)) > 8:
            raise ValueError("CAN Classic erlaubt maximal 8 Datenbytes.")

        if self.use_dbc_ids_var.get():
            dbc_path = Path(self.entry_dbc_path.get().strip())
            dbc_ids = self._parse_dbc_ids(dbc_path)
            for can_id_text in dbc_ids:
                sequence.append((can_id_text, data_text, None))
            return sequence, {int(can_id_text, 16) for can_id_text in dbc_ids}, f"DBC: {dbc_path.name}"

        can_id_text = self._normalize_can_id_token(self.entry_id.get())
        sequence.append((can_id_text, data_text, None))
        can_id = int(can_id_text, 16)
        return sequence, {can_id}, "Einzel-ID"

    def _parse_repeat_count(self) -> int:
        try:
            repeat_count = int(self.entry_repeat.get().strip())
        except ValueError as exc:
            raise ValueError("Wiederholungen muss eine ganze Zahl sein.") from exc
        if repeat_count < 0:
            raise ValueError("Wiederholungen darf nicht negativ sein.")
        return repeat_count

    def _set_running_state(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for widget in (
            self.entry_dbc_path,
            self.browse_dbc_btn,
            self.use_dbc_ids_cb,
            self.entry_id,
            self.entry_data,
            self.seq_text,
            self.entry_repeat,
            self.entry_delay,
            self.entry_rx,
            self.entry_status,
        ):
            try:
                widget.configure(state=state)
            except Exception:
                pass

        self.send_btn.configure(state=("disabled" if running else "normal"))
        self.stop_btn.configure(state=("normal" if running else "disabled"))

    def _start_run(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showinfo("Spoofing", "Der Sende-Lauf laeuft bereits.")
            return

        try:
            sequence, known_ids, mode_label = self._parse_sequence()
            repeat_count = self._parse_repeat_count()
            interval_s = self._parse_float_ms(self.entry_delay.get(), "Intervall zwischen Frames")
            rx_window_s = self._parse_float_ms(self.entry_rx.get(), "RX-Fenster")
        except ValueError as exc:
            messagebox.showerror("Spoofing", str(exc))
            return

        self._worker_stop.clear()
        self._set_running_state(True)
        self.status.configure(text=self.entry_status.get().strip() or "Mehrfachsendung startet …")
        self._append_log(
            f"--- Start: {len(sequence)} Frame(s), Modus={mode_label}, "
            f"Wiederholungen={repeat_count if repeat_count else 'unbegrenzt'}, "
            f"Intervall={interval_s * 1000:.0f} ms, RX-Fenster={rx_window_s * 1000:.0f} ms ---"
        )

        self._worker_thread = threading.Thread(
            target=self._run_sequence,
            args=(sequence, repeat_count, interval_s, rx_window_s, known_ids),
            name="SpoofingBurstWorker",
            daemon=True,
        )
        self._worker_thread.start()

    def _stop_run(self) -> None:
        if not self._worker_thread or not self._worker_thread.is_alive():
            self.status.configure(text="Kein aktiver Sende-Lauf.")
            return

        self._worker_stop.set()
        self.status.configure(text="Stop angefordert …")
        self._queue_log("--- Stop angefordert ---")

    def _sleep_until_stop(self, duration_s: float) -> None:
        deadline = time.time() + duration_s
        while not self._worker_stop.is_set():
            remaining = deadline - time.time()
            if remaining <= 0:
                return
            self._worker_stop.wait(timeout=min(0.05, remaining))

    @staticmethod
    def _format_data(data: bytes) -> str:
        return " ".join(f"{byte:02X}" for byte in data)

    @staticmethod
    def _format_ts(ts: float) -> str:
        return time.strftime("%H:%M:%S", time.localtime(ts)) + f".{int((ts % 1) * 1000):03d}"

    def _run_sequence(
        self,
        sequence: List[SequenceItem],
        repeat_count: int,
        interval_s: float,
        rx_window_s: float,
        known_ids: Set[int],
    ) -> None:
        bus = None
        tx_total = 0
        rx_total = 0
        rx_seen_ids: Set[int] = set()
        rx_outside_dbc_ids: Set[int] = set()
        started_at = time.time()

        try:
            bus = open_bus()
            self._queue_log(f"[{self._format_ts(started_at)}] Bus geoeffnet, Sende-Lauf aktiv.")

            cycle = 0
            while not self._worker_stop.is_set():
                cycle += 1
                if repeat_count > 0 and cycle > repeat_count:
                    break

                self._queue_log(f"[{self._format_ts(time.time())}] Zyklus {cycle} gestartet.")
                for frame_index, (can_id_text, data_text, per_frame_pause_s) in enumerate(sequence, start=1):
                    if self._worker_stop.is_set():
                        break

                    try:
                        msg = make_msg(can_id_text, data_text)
                        tx_ts = time.time()
                        bus.send(msg)
                        tx_total += 1
                        try:
                            print_tx(msg)
                        except Exception:
                            pass

                        self._queue_log(
                            f"[{self._format_ts(tx_ts)}] TX cycle={cycle} frame={frame_index} "
                            f"ID=0x{int(can_id_text, 16):03X} DLC={len(msg.data)} Data={self._format_data(bytes(msg.data))}"
                        )

                        rx_seen = 0
                        rx_deadline = time.time() + rx_window_s
                        while not self._worker_stop.is_set() and time.time() < rx_deadline:
                            try:
                                rx_msg = bus.recv(timeout=0.01)
                            except Exception as exc:
                                self._queue_log(f"[{self._format_ts(time.time())}] RX Fehler: {exc}")
                                break

                            if rx_msg is None:
                                continue

                            rx_seen += 1
                            rx_total += 1
                            try:
                                rx_ts = float(getattr(rx_msg, "timestamp", time.time()))
                            except Exception:
                                rx_ts = time.time()

                            rx_id = int(getattr(rx_msg, "arbitration_id", 0))
                            rx_seen_ids.add(rx_id)
                            in_dbc = rx_id in known_ids
                            if not in_dbc:
                                rx_outside_dbc_ids.add(rx_id)

                            delta_ms = (rx_ts - tx_ts) * 1000.0
                            data_repr = self._format_data(bytes(rx_msg.data))
                            dbc_tag = "[DBC]" if in_dbc else "[nicht in DBC]"
                            self._queue_log(
                                f"[{self._format_ts(rx_ts)}] RX +{delta_ms:.1f}ms ID=0x{rx_id:03X} "
                                f"DLC={rx_msg.dlc} Data={data_repr} {dbc_tag}"
                            )
                            try:
                                print_rx(rx_msg)
                            except Exception:
                                pass

                        if rx_seen == 0:
                            self._queue_log(
                                f"[{self._format_ts(time.time())}] RX kein Frame im Fenster fuer cycle={cycle} frame={frame_index}."
                            )

                    except Exception as exc:
                        self._queue_log(
                            f"[{self._format_ts(time.time())}] Fehler bei cycle={cycle} frame={frame_index}: {exc}"
                        )
                        raise

                    pause_s = per_frame_pause_s if per_frame_pause_s is not None else interval_s
                    if pause_s > 0 and not self._worker_stop.is_set():
                        self._sleep_until_stop(pause_s)

                if repeat_count > 0 and cycle >= repeat_count:
                    break

            outside_text = ", ".join(f"0x{can_id:03X}" for can_id in sorted(rx_outside_dbc_ids)) or "keine"
            self._queue_log(
                f"[{self._format_ts(time.time())}] RX Summary: unique={len(rx_seen_ids)}, ausserhalb DBC={outside_text}."
            )

            if self._worker_stop.is_set():
                self._queue_log(
                    f"[{self._format_ts(time.time())}] Sende-Lauf gestoppt nach {tx_total} TX und {rx_total} RX."
                )
                self.after(0, lambda: self.status.configure(text="Sende-Lauf gestoppt."))
            else:
                self._queue_log(
                    f"[{self._format_ts(time.time())}] Sende-Lauf beendet: {tx_total} TX, {rx_total} RX."
                )
                self.after(0, lambda: self.status.configure(text=f"Fertig: {tx_total} TX, {rx_total} RX."))

        except Exception as exc:
            self._queue_log(f"[{self._format_ts(time.time())}] Sende-Lauf fehlgeschlagen: {exc}")
            self.after(0, lambda: self.status.configure(text="Fehler beim Sende-Lauf."))
            self.after(0, lambda: messagebox.showerror("CAN Fehler", f"Senden fehlgeschlagen:\n{exc}"))
        finally:
            if bus is not None:
                try:
                    bus.shutdown()
                except Exception:
                    pass
            try:
                self.after(0, self._on_worker_finished)
            except Exception:
                pass

    def _on_worker_finished(self) -> None:
        self._worker_thread = None
        self._worker_stop.clear()
        self._set_running_state(False)

    def destroy(self) -> None:
        try:
            self._worker_stop.set()
            if self._worker_thread and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=0.5)
        except Exception:
            pass
        super().destroy()