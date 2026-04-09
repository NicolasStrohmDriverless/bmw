from __future__ import annotations

import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Set, Tuple

from can_utils import make_msg, open_bus, print_rx, print_tx

# ID=<num>[x],Type=<D|R|RX>,Length=<0..8>,Data=<hex>
_TESTING_LINE_RE = re.compile(
    r"^\s*ID=(?P<id>[^,]+),Type=(?P<type>RX|[DRdrx]),Length=(?P<length>\d+)(?:,Data=(?P<data>[0-9A-Fa-f]*))?\s*$"
)

HANDBRAKE_EXAMPLE = {
    "label": "Handbremse aktiv",
    "delay_ms": "100",
    "rx_ms": "200",
}

HANDBRAKE_EXAMPLE_SEQUENCE = [
    ("6F1", "2902100300000000"),
    ("6F1", "29053101A8030200"),
]


class SpoofingPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, style="Card.TFrame")
        self.app = app

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._worker_stop = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._capture_entries: List[dict] = []

        top = ttk.Frame(self, padding=16, style="Card.TFrame")
        top.pack(fill="x")

        self.head = ttk.Label(top, text="Spoofing", style="Card.TLabel", font=("Segoe UI", 16, "bold"))
        self.head.pack(side="left")

        self.back_btn = ttk.Button(top, text="<- Zurueck", command=lambda: app.show("AutoSearchPage"))
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
                "Sendet systematisch IDs/Frames aus Capture-Quelle und zeichnet RX-Reaktionen auf. "
                "Fuer jede ID werden beobachtete und generische Payload-Varianten getestet."
            ),
            style="Card.TLabel",
        )
        intro.pack(anchor="w", pady=(0, 12))

        source_row = ttk.Frame(body, style="Card.TFrame")
        source_row.pack(fill="x", pady=6)
        ttk.Label(source_row, text="Capture-Datei (ID=...,Type=...,Length=...,Data=...):", style="Card.TLabel").pack(side="left")
        self.entry_source_path = ttk.Entry(source_row, width=60)
        self.entry_source_path.pack(side="left", padx=8, fill="x", expand=True)
        self.browse_source_btn = ttk.Button(source_row, text="...", width=4, command=self._browse_capture_file)
        self.browse_source_btn.pack(side="left", padx=(0, 8))
        self.load_source_btn = ttk.Button(source_row, text="Laden", command=self._load_capture_file)
        self.load_source_btn.pack(side="left")
        self.example_btn = ttk.Button(source_row, text="Feststellbremse-Beispiel laden", command=self._load_handbrake_example)
        self.example_btn.pack(side="left", padx=(8, 0))

        options_row = ttk.Frame(body, style="Card.TFrame")
        options_row.pack(fill="x", pady=6)
        self.include_remote_var = tk.BooleanVar(value=True)
        self.include_patterns_var = tk.BooleanVar(value=True)
        self.only_observed_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options_row,
            text="Remote-Frames (Type=R) senden",
            variable=self.include_remote_var,
        ).pack(side="left")
        ttk.Checkbutton(
            options_row,
            text="Generische Payload-Muster je ID",
            variable=self.include_patterns_var,
        ).pack(side="left", padx=(16, 0))
        ttk.Checkbutton(
            options_row,
            text="Nur beobachtete Daten senden",
            variable=self.only_observed_var,
        ).pack(side="left", padx=(16, 0))

        limits_row = ttk.Frame(body, style="Card.TFrame")
        limits_row.pack(fill="x", pady=6)
        ttk.Label(limits_row, text="Max Varianten pro ID (-1 = alle):", style="Card.TLabel").pack(side="left")
        self.entry_max_variants = ttk.Entry(limits_row, width=8)
        self.entry_max_variants.insert(0, "24")
        self.entry_max_variants.pack(side="left", padx=8)

        ttk.Label(limits_row, text="Max IDs (0 = alle):", style="Card.TLabel").pack(side="left")
        self.entry_max_ids = ttk.Entry(limits_row, width=8)
        self.entry_max_ids.insert(0, "0")
        self.entry_max_ids.pack(side="left", padx=8)

        ttk.Label(limits_row, text="Wiederholungen:", style="Card.TLabel").pack(side="left")
        self.entry_repeat = ttk.Entry(limits_row, width=8)
        self.entry_repeat.insert(0, "1")
        self.entry_repeat.pack(side="left", padx=8)

        timing_row = ttk.Frame(body, style="Card.TFrame")
        timing_row.pack(fill="x", pady=6)
        ttk.Label(timing_row, text="Intervall zwischen TX (ms):", style="Card.TLabel").pack(side="left")
        self.entry_delay = ttk.Entry(timing_row, width=8)
        self.entry_delay.insert(0, "20")
        self.entry_delay.pack(side="left", padx=8)

        ttk.Label(timing_row, text="RX-Fenster je TX (ms):", style="Card.TLabel").pack(side="left")
        self.entry_rx = ttk.Entry(timing_row, width=8)
        self.entry_rx.insert(0, "200")
        self.entry_rx.pack(side="left", padx=8)

        btn_row = ttk.Frame(body, style="Card.TFrame")
        btn_row.pack(fill="x", pady=(14, 10))

        self.send_btn = ttk.Button(btn_row, text="Massensendung starten", command=self._start_run)
        self.stop_btn = ttk.Button(btn_row, text="Stop", command=self._stop_run)
        self.clear_btn = ttk.Button(btn_row, text="Log leeren", command=self._clear_log)
        try:
            self.send_btn.configure(style="Red.TButton")
            self.stop_btn.configure(style="Red.TButton")
            self.clear_btn.configure(style="Red.TButton")
            self.browse_source_btn.configure(style="Red.TButton")
            self.load_source_btn.configure(style="Red.TButton")
        except Exception:
            pass

        self.send_btn.pack(side="left", padx=(0, 8), ipadx=12, ipady=8)
        self.stop_btn.pack(side="left", padx=(0, 8), ipadx=12, ipady=8)
        self.clear_btn.pack(side="left", ipadx=12, ipady=8)
        self.stop_btn.configure(state="disabled")

        self.status = ttk.Label(body, text="Bereit.", style="Card.TLabel")
        self.status.pack(fill="x", pady=(0, 8))

        self.log_text = tk.Text(body, height=16, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True)

        self.after(100, self._drain_log_queue)

    def apply_theme(self, bg, fg, card, paint_button):
        self.configure(style="Card.TFrame")
        for child in self.winfo_children():
            if isinstance(child, ttk.Frame):
                child.configure(style="Card.TFrame")
        self.head.configure(style="Card.TLabel")
        self.status.configure(style="Card.TLabel")
        for widget in (self.log_text,):
            try:
                widget.configure(background=card, foreground=fg, insertbackground=fg)
            except Exception:
                pass
        for btn in (self.send_btn, self.stop_btn, self.clear_btn, self.back_btn, self.browse_source_btn, self.load_source_btn, self.example_btn):
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

    def _browse_capture_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Capture-Datei auswaehlen",
            filetypes=[("Text", "*.txt"), ("Alle Dateien", "*.*")],
        )
        if selected:
            self.entry_source_path.delete(0, tk.END)
            self.entry_source_path.insert(0, selected)

    def _generate_handbrake_example_file(self) -> Path:
        root_dir = Path(__file__).resolve().parents[3]
        out_dir = root_dir / "generated_captures" / "beispiele"
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / "capture_feststellbremse_beispiel.txt"
        out_lines = [
            f"ID={can_id},Type=D,Length=8,Data={data_hex}"
            for can_id, data_hex in HANDBRAKE_EXAMPLE_SEQUENCE
        ]
        out_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        return out_path

    def _load_handbrake_example(self) -> None:
        try:
            generated = self._generate_handbrake_example_file()
        except OSError as exc:
            messagebox.showerror("Spoofing", f"Feststellbremse-Beispiel kann nicht erstellt werden:\n{exc}")
            return

        self.entry_source_path.delete(0, tk.END)
        self.entry_source_path.insert(0, str(generated))

        self.include_remote_var.set(False)
        self.include_patterns_var.set(False)
        self.only_observed_var.set(True)

        self.entry_max_variants.delete(0, tk.END)
        self.entry_max_variants.insert(0, str(len(HANDBRAKE_EXAMPLE_SEQUENCE)))
        self.entry_max_ids.delete(0, tk.END)
        self.entry_max_ids.insert(0, "1")
        self.entry_repeat.delete(0, tk.END)
        self.entry_repeat.insert(0, "1")
        self.entry_delay.delete(0, tk.END)
        self.entry_delay.insert(0, HANDBRAKE_EXAMPLE["delay_ms"])
        self.entry_rx.delete(0, tk.END)
        self.entry_rx.insert(0, HANDBRAKE_EXAMPLE["rx_ms"])

        self._capture_entries = []
        self._load_capture_file()
        self.status.configure(text="Feststellbremse-Beispiel geladen: 2 Frames im Workshop-Stil, ein Verifikationslauf.")
        self._append_log(
            f"--- Feststellbremse-Beispiel geladen: {HANDBRAKE_EXAMPLE['label']} | Frames={len(HANDBRAKE_EXAMPLE_SEQUENCE)} | Workshop-Stil | Delay={HANDBRAKE_EXAMPLE['delay_ms']} ms ---"
        )

    @staticmethod
    def _normalize_payload(raw: str, dlc: int) -> str:
        payload = (raw or "").strip().upper().replace("0X", "")
        if payload and len(payload) % 2 != 0:
            payload = "0" + payload
        if payload and not all(ch in "0123456789ABCDEF" for ch in payload):
            raise ValueError("Ungueltiges Hex in Data-Feld.")

        target_chars = max(0, dlc * 2)
        if target_chars == 0:
            return ""
        payload = payload[:target_chars]
        if len(payload) < target_chars:
            payload = payload.ljust(target_chars, "0")
        return payload

    @staticmethod
    def _parse_capture_id(raw_id: str) -> Tuple[int, bool]:
        cleaned = raw_id.strip()
        is_extended = cleaned.lower().endswith("x")
        if is_extended:
            cleaned = cleaned[:-1].strip()

        if cleaned.lower().startswith("0x"):
            cleaned = cleaned[2:]
            return int(cleaned, 16), is_extended

        has_hex_letters = any(ch in "ABCDEFabcdef" for ch in cleaned)
        if has_hex_letters:
            return int(cleaned, 16), is_extended

        try:
            value = int(cleaned, 10)
        except ValueError:
            return int(cleaned, 16), is_extended

        if value > 0x7FF:
            hex_value = int(cleaned, 16)
            if hex_value <= 0x7FF:
                return hex_value, is_extended

        return value, is_extended

    def _load_capture_file(self) -> None:
        raw_path = self.entry_source_path.get().strip()
        if not raw_path:
            messagebox.showerror("Spoofing", "Bitte eine Capture-Datei auswaehlen.")
            return

        source_path = Path(raw_path)
        if not source_path.exists() or not source_path.is_file():
            messagebox.showerror("Spoofing", "Capture-Datei nicht gefunden oder kein Dateipfad.")
            return

        try:
            file_lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            messagebox.showerror("Spoofing", f"Capture-Datei kann nicht gelesen werden:\n{exc}")
            return

        entries: List[dict] = []
        warnings = 0

        for line_number, raw_line in enumerate(file_lines, start=1):
            line = raw_line.strip()
            if not line:
                continue
            match = _TESTING_LINE_RE.match(line)
            if not match:
                warnings += 1
                continue

            raw_id = match.group("id").strip()
            frame_type = match.group("type").upper()

            try:
                can_id, is_extended = self._parse_capture_id(raw_id)
                dlc = int(match.group("length"))
            except ValueError:
                warnings += 1
                continue

            if dlc < 0 or dlc > 8:
                warnings += 1
                continue

            if is_extended and can_id > 0x1FFFFFFF:
                warnings += 1
                continue
            if (not is_extended) and can_id > 0x7FF:
                # some captures provide decimal id with x for extended; keep strict typing
                warnings += 1
                continue

            data_hex = self._normalize_payload(match.group("data") or "", dlc)

            entries.append(
                {
                    "line": line_number,
                    "can_id": can_id,
                    "can_id_hex": f"{can_id:X}",
                    "is_extended": is_extended,
                    "frame_type": frame_type,
                    "dlc": dlc,
                    "data_hex": data_hex,
                }
            )

        if not entries:
            messagebox.showerror("Spoofing", "Keine gueltigen Eintraege in der Capture-Datei gefunden.")
            return

        self._capture_entries = entries
        unique_ids = {(entry["can_id"], entry["is_extended"]) for entry in entries}
        self.status.configure(text=f"Quelle geladen: {len(entries)} Zeilen, {len(unique_ids)} IDs.")
        self._append_log(
            f"--- Quelle geladen: {source_path.name} | Zeilen={len(entries)} | IDs={len(unique_ids)} | Warnungen={warnings} ---"
        )

    def _generate_capture_file_now(self) -> Path:
        root_dir = Path(__file__).resolve().parents[3]
        out_dir = root_dir / "generated_captures"
        out_dir.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        out_path = out_dir / f"capture_{timestamp}.txt"

        # Prefer DBC message IDs for relevant coverage; fallback to all 11-bit IDs.
        dbc_path = root_dir / "bmw_e9x_e8x.dbc"
        ids: List[int] = []
        if dbc_path.exists():
            bo_re = re.compile(r"^\s*BO_\s+(\d+)\s+")
            seen_ids: Set[int] = set()
            for raw_line in dbc_path.read_text(encoding="utf-8", errors="replace").splitlines():
                match = bo_re.match(raw_line)
                if not match:
                    continue
                raw_id = int(match.group(1))
                if raw_id & 0x80000000:
                    continue
                if 0 <= raw_id <= 0x7FF and raw_id not in seen_ids:
                    seen_ids.add(raw_id)
                    ids.append(raw_id)

        if not ids:
            ids = list(range(0x000, 0x800))

        lines: List[str] = []
        for can_id in ids:
            b0 = can_id & 0xFF
            b1 = (can_id >> 3) & 0xFF
            b2 = (0xFF - b0) & 0xFF
            b3 = (0xA5 ^ b1) & 0xFF

            # Build multiple payload variants so reaction logging has useful signal.
            lines.append(f"ID={can_id},Type=D,Length=0")
            lines.append(f"ID={can_id},Type=D,Length=1,Data={b0:02X}")
            lines.append(f"ID={can_id},Type=D,Length=2,Data={b0:02X}{b2:02X}")
            lines.append(f"ID={can_id},Type=D,Length=8,Data={b0:02X}{b1:02X}{b2:02X}{b3:02X}00000000")

            if self.include_remote_var.get():
                lines.append(f"ID={can_id},Type=R,Length=8")

        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out_path

    @staticmethod
    def _pattern_payloads(dlc: int) -> List[str]:
        if dlc <= 0:
            return [""]
        return [
            ("00" * dlc),
            ("FF" * dlc),
            ("AA" * dlc),
            ("55" * dlc),
            ("00" * (dlc - 1)) + "01",
            ("00" * (dlc - 1)) + "80",
            "".join(f"{idx & 0xFF:02X}" for idx in range(dlc)),
            "".join(f"{(0xFF - idx) & 0xFF:02X}" for idx in range(dlc)),
        ]

    def _build_tx_plan(self, max_variants_per_id: int, max_ids: int) -> List[dict]:
        by_id: Dict[Tuple[int, bool], List[dict]] = {}
        for entry in self._capture_entries:
            key = (entry["can_id"], entry["is_extended"])
            by_id.setdefault(key, []).append(entry)

        sorted_keys = sorted(by_id.keys(), key=lambda item: (item[1], item[0]))
        if max_ids > 0:
            sorted_keys = sorted_keys[:max_ids]

        include_patterns = self.include_patterns_var.get() and not self.only_observed_var.get()
        include_remote = self.include_remote_var.get()

        plan: List[dict] = []
        for key in sorted_keys:
            entries = by_id[key]
            can_id, is_extended = key
            seen: Set[Tuple[str, int, str]] = set()
            id_plan: List[dict] = []

            for entry in entries:
                signature = (entry["frame_type"], entry["dlc"], entry["data_hex"])
                if signature in seen:
                    continue
                seen.add(signature)
                if entry["frame_type"] == "D":
                    id_plan.append(
                        {
                            "can_id": can_id,
                            "can_id_hex": f"{can_id:X}",
                            "is_extended": is_extended,
                            "is_remote": False,
                            "dlc": entry["dlc"],
                            "data_hex": entry["data_hex"],
                            "source": "observed",
                        }
                    )
                elif include_remote and entry["frame_type"] == "R":
                    id_plan.append(
                        {
                            "can_id": can_id,
                            "can_id_hex": f"{can_id:X}",
                            "is_extended": is_extended,
                            "is_remote": True,
                            "dlc": entry["dlc"],
                            "data_hex": "",
                            "source": "remote",
                        }
                    )

            if include_patterns:
                # Use dominant DLC for this ID to generate additional message variants.
                dlc_counts: Dict[int, int] = {}
                for entry in entries:
                    dlc_counts[entry["dlc"]] = dlc_counts.get(entry["dlc"], 0) + 1
                dominant_dlc = max(dlc_counts.items(), key=lambda item: item[1])[0]
                for payload in self._pattern_payloads(dominant_dlc):
                    signature = ("D", dominant_dlc, payload)
                    if signature in seen:
                        continue
                    seen.add(signature)
                    id_plan.append(
                        {
                            "can_id": can_id,
                            "can_id_hex": f"{can_id:X}",
                            "is_extended": is_extended,
                            "is_remote": False,
                            "dlc": dominant_dlc,
                            "data_hex": payload,
                            "source": "pattern",
                        }
                    )

            if max_variants_per_id < 0:
                plan.extend(id_plan)
            else:
                plan.extend(id_plan[:max_variants_per_id])

        return plan

    @staticmethod
    def _parse_nonnegative_int(raw: str, label: str) -> int:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise ValueError(f"{label} muss eine ganze Zahl sein.") from exc
        if value < 0:
            raise ValueError(f"{label} darf nicht negativ sein.")
        return value

    @staticmethod
    def _parse_int_allowing_minus_one(raw: str, label: str) -> int:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise ValueError(f"{label} muss eine ganze Zahl sein.") from exc
        if value < -1:
            raise ValueError(f"{label} darf nur -1 oder eine positive Zahl sein.")
        return value

    @staticmethod
    def _parse_float_ms(raw: str, label: str) -> float:
        try:
            value = float(raw.strip().replace(",", "."))
        except ValueError as exc:
            raise ValueError(f"{label} muss eine Zahl sein.") from exc
        if value < 0:
            raise ValueError(f"{label} darf nicht negativ sein.")
        return value / 1000.0

    def _set_running_state(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for widget in (
            self.entry_source_path,
            self.browse_source_btn,
            self.load_source_btn,
            self.entry_max_variants,
            self.entry_max_ids,
            self.entry_repeat,
            self.entry_delay,
            self.entry_rx,
        ):
            try:
                widget.configure(state=state)
            except Exception:
                pass
        self.send_btn.configure(state=("disabled" if running else "normal"))
        self.stop_btn.configure(state=("normal" if running else "disabled"))

    def _start_run(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showinfo("Spoofing", "Massensendung laeuft bereits.")
            return

        if not self._capture_entries:
            raw_path = self.entry_source_path.get().strip()
            if raw_path:
                self._load_capture_file()

            if not self._capture_entries:
                try:
                    generated = self._generate_capture_file_now()
                except OSError as exc:
                    messagebox.showerror("Spoofing", f"Autogenerierung fehlgeschlagen:\n{exc}")
                    return

                self.entry_source_path.delete(0, tk.END)
                self.entry_source_path.insert(0, str(generated))
                self._append_log(f"--- Keine Quelle vorhanden: Autogeneriert {generated.name} ---")
                self._load_capture_file()

            if not self._capture_entries:
                messagebox.showerror("Spoofing", "Bitte zuerst eine Capture-Datei laden.")
                return

        try:
            max_variants = self._parse_int_allowing_minus_one(self.entry_max_variants.get(), "Max Varianten pro ID")
            max_ids = self._parse_nonnegative_int(self.entry_max_ids.get(), "Max IDs")
            repeat_count = self._parse_nonnegative_int(self.entry_repeat.get(), "Wiederholungen")
            delay_s = self._parse_float_ms(self.entry_delay.get(), "Intervall")
            rx_window_s = self._parse_float_ms(self.entry_rx.get(), "RX-Fenster")
        except ValueError as exc:
            messagebox.showerror("Spoofing", str(exc))
            return

        if max_variants == 0:
            messagebox.showerror("Spoofing", "Max Varianten pro ID muss groesser 0 oder -1 fuer alle sein.")
            return

        tx_plan = self._build_tx_plan(max_variants, max_ids)
        if not tx_plan:
            messagebox.showerror("Spoofing", "Kein TX-Plan erzeugt. Optionen pruefen.")
            return

        repeats = repeat_count if repeat_count > 0 else 1
        self._worker_stop.clear()
        self._set_running_state(True)
        self.status.configure(text="Massensendung gestartet ...")
        self._append_log(
            f"--- Start: TX-Plan={len(tx_plan)} Frames, Wiederholungen={repeats}, Delay={delay_s * 1000:.0f} ms, RX={rx_window_s * 1000:.0f} ms ---"
        )

        self._worker_thread = threading.Thread(
            target=self._run_mass_send,
            args=(tx_plan, repeats, delay_s, rx_window_s),
            name="SpoofingMassWorker",
            daemon=True,
        )
        self._worker_thread.start()

    def _stop_run(self) -> None:
        if not self._worker_thread or not self._worker_thread.is_alive():
            self.status.configure(text="Kein aktiver Lauf.")
            return
        self._worker_stop.set()
        self.status.configure(text="Stop angefordert ...")
        self._queue_log("--- Stop angefordert ---")

    @staticmethod
    def _fmt_ts(ts: float) -> str:
        return time.strftime("%H:%M:%S", time.localtime(ts)) + f".{int((ts % 1) * 1000):03d}"

    @staticmethod
    def _fmt_data(data_hex: str) -> str:
        return " ".join(data_hex[i : i + 2] for i in range(0, len(data_hex), 2))

    @staticmethod
    def _fmt_id(can_id: int, is_extended: bool) -> str:
        width = 8 if is_extended else 3
        return f"0x{can_id:0{width}X}"

    def _capture_baseline(self, bus, duration_s: float) -> Tuple[Dict[Tuple[int, bool, int, str], int], Set[Tuple[int, bool]]]:
        baseline_signatures: Dict[Tuple[int, bool, int, str], int] = {}
        baseline_id_counts: Dict[Tuple[int, bool], int] = {}

        if duration_s <= 0:
            return baseline_signatures, set()

        deadline = time.time() + duration_s
        while not self._worker_stop.is_set() and time.time() < deadline:
            rx_msg = bus.recv(timeout=0.01)
            if rx_msg is None:
                continue

            rx_id = int(getattr(rx_msg, "arbitration_id", 0))
            rx_ext = bool(getattr(rx_msg, "is_extended_id", False))
            rx_dlc = int(getattr(rx_msg, "dlc", len(getattr(rx_msg, "data", b""))))
            rx_data_hex = bytes(getattr(rx_msg, "data", b"")).hex().upper()

            signature = (rx_id, rx_ext, rx_dlc, rx_data_hex)
            pair = (rx_id, rx_ext)
            baseline_signatures[signature] = baseline_signatures.get(signature, 0) + 1
            baseline_id_counts[pair] = baseline_id_counts.get(pair, 0) + 1

        periodic_ids = {pair for pair, count in baseline_id_counts.items() if count >= 2}
        return baseline_signatures, periodic_ids

    def _run_mass_send(self, tx_plan: List[dict], repeats: int, delay_s: float, rx_window_s: float) -> None:
        bus = None
        tx_total = 0
        rx_total = 0
        reaction_by_tx: Dict[Tuple[int, bool], int] = {}
        background_by_tx: Dict[Tuple[int, bool], int] = {}
        new_rx_ids: Set[Tuple[int, bool]] = set()

        known_tx_ids = {(item["can_id"], item["is_extended"]) for item in tx_plan}

        # === ADDED: Create capture output file for RX data ===
        root_dir = Path(__file__).resolve().parents[3]
        out_dir = root_dir / "generated_captures"
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        capture_file = out_dir / f"capture_RX_results_{timestamp}.txt"
        capture_lines: List[str] = []
        # === END ADDED ===

        try:
            bus = open_bus()
            self._queue_log(f"[{self._fmt_ts(time.time())}] Bus geoeffnet.")

            baseline_duration_s = min(1.0, max(0.2, rx_window_s))
            self._queue_log(
                f"[{self._fmt_ts(time.time())}] Baseline-Lernen gestartet ({baseline_duration_s * 1000:.0f} ms) ..."
            )
            baseline_signatures, periodic_ids = self._capture_baseline(bus, baseline_duration_s)
            self._queue_log(
                f"[{self._fmt_ts(time.time())}] Baseline gelernt: signatures={len(baseline_signatures)}, periodic_ids={len(periodic_ids)}"
            )

            for cycle in range(1, repeats + 1):
                if self._worker_stop.is_set():
                    break
                self._queue_log(f"[{self._fmt_ts(time.time())}] Zyklus {cycle} gestartet.")

                for index, item in enumerate(tx_plan, start=1):
                    if self._worker_stop.is_set():
                        break

                    msg = make_msg(
                        item["can_id_hex"],
                        item["data_hex"],
                        is_extended_id=item["is_extended"],
                        is_remote_frame=item["is_remote"],
                        dlc=item["dlc"],
                    )

                    tx_ts = time.time()
                    bus.send(msg)
                    tx_total += 1
                    tx_key = (item["can_id"], item["is_extended"])
                    try:
                        print_tx(msg)
                    except Exception:
                        pass

                    # === ADDED: Log TX to capture file ===
                    capture_lines.append(
                        f"ID={item['can_id']},Type=D,Length={item['dlc']},Data={item['data_hex']}"
                    )
                    # === END ADDED ===

                    source = item["source"]
                    frame_kind = "RTR" if item["is_remote"] else "DATA"
                    self._queue_log(
                        f"[{self._fmt_ts(tx_ts)}] TX cycle={cycle} idx={index} ID={self._fmt_id(item['can_id'], item['is_extended'])} "
                        f"kind={frame_kind} dlc={item['dlc']} src={source} data={self._fmt_data(item['data_hex'])}"
                    )

                    rx_seen = 0
                    rx_candidate = 0
                    rx_background = 0
                    deadline = time.time() + rx_window_s
                    first_delta_ms: Optional[float] = None
                    first_candidate_delta_ms: Optional[float] = None

                    while not self._worker_stop.is_set() and time.time() < deadline:
                        rx_msg = bus.recv(timeout=0.01)
                        if rx_msg is None:
                            continue

                        rx_seen += 1
                        rx_total += 1
                        rx_wall_ts = time.time()
                        rx_id = int(getattr(rx_msg, "arbitration_id", 0))
                        rx_ext = bool(getattr(rx_msg, "is_extended_id", False))
                        rx_dlc = int(getattr(rx_msg, "dlc", len(getattr(rx_msg, "data", b""))))
                        rx_pair = (rx_id, rx_ext)
                        rx_data_hex = bytes(rx_msg.data).hex().upper()
                        rx_signature = (rx_id, rx_ext, rx_dlc, rx_data_hex)
                        delta_ms = (rx_wall_ts - tx_ts) * 1000.0

                        if first_delta_ms is None:
                            first_delta_ms = delta_ms

                        if rx_pair not in known_tx_ids:
                            new_rx_ids.add(rx_pair)

                        is_background = (rx_signature in baseline_signatures) or (rx_pair in periodic_ids)
                        if is_background:
                            rx_background += 1
                            background_by_tx[tx_key] = background_by_tx.get(tx_key, 0) + 1
                        else:
                            rx_candidate += 1
                            reaction_by_tx[tx_key] = reaction_by_tx.get(tx_key, 0) + 1
                            if first_candidate_delta_ms is None:
                                first_candidate_delta_ms = delta_ms
                        
                        # === ADDED: Log RX to capture file ===
                        capture_lines.append(
                            f"ID={rx_id},Type=RX,Length={rx_dlc},Data={rx_data_hex}"
                        )
                        # === END ADDED ===

                        tag = "BG" if is_background else "CAND"
                        self._queue_log(
                            f"[{self._fmt_ts(rx_wall_ts)}] RX[{tag}] +{delta_ms:.1f}ms ID={self._fmt_id(rx_id, rx_ext)} "
                            f"dlc={rx_dlc} data={self._fmt_data(rx_data_hex)}"
                        )
                        try:
                            print_rx(rx_msg)
                        except Exception:
                            pass

                    if rx_seen == 0:
                        self._queue_log(
                            f"[{self._fmt_ts(time.time())}] RX none for ID={self._fmt_id(item['can_id'], item['is_extended'])}."
                        )
                    else:
                        candidate_text = "n/a" if first_candidate_delta_ms is None else f"{first_candidate_delta_ms:.1f}ms"
                        self._queue_log(
                            f"[{self._fmt_ts(time.time())}] RX summary for ID={self._fmt_id(item['can_id'], item['is_extended'])}: "
                            f"all={rx_seen}, candidate={rx_candidate}, background={rx_background}, "
                            f"first_delta={first_delta_ms:.1f}ms, first_candidate={candidate_text}"
                        )

                    if delay_s > 0 and not self._worker_stop.is_set():
                        self._worker_stop.wait(timeout=delay_s)

            self._queue_log("--- Reaktions-Summary pro gesendeter ID ---")
            all_summary_keys = set(reaction_by_tx.keys()) | set(background_by_tx.keys())
            for can_id, is_extended in sorted(all_summary_keys, key=lambda item: (item[1], item[0])):
                self._queue_log(
                    f"ID={self._fmt_id(can_id, is_extended)} reactions={reaction_by_tx.get((can_id, is_extended), 0)} "
                    f"background={background_by_tx.get((can_id, is_extended), 0)}"
                )

            new_id_text = ", ".join(self._fmt_id(cid, ext) for cid, ext in sorted(new_rx_ids, key=lambda item: (item[1], item[0])))
            self._queue_log(f"Neue RX-IDs (nicht im TX-Plan): {new_id_text or 'keine'}")
            self._queue_log(f"Lauf beendet: TX={tx_total}, RX={rx_total}")

            if self._worker_stop.is_set():
                self.after(0, lambda: self.status.configure(text=f"Gestoppt: TX={tx_total}, RX={rx_total}"))
            else:
                self.after(0, lambda: self.status.configure(text=f"Fertig: TX={tx_total}, RX={rx_total}"))

        except Exception as exc:
            self._queue_log(f"Fehler im Lauf: {exc}")
            self.after(0, lambda: self.status.configure(text="Fehler bei Massensendung."))
            self.after(0, lambda: messagebox.showerror("CAN Fehler", f"Massensendung fehlgeschlagen:\n{exc}"))
        finally:
            # === ADDED: Write capture file with RX data ===
            try:
                capture_file.write_text("\n".join(capture_lines) + "\n", encoding="utf-8")
                self._queue_log(f"Capture-Datei mit RX-Daten gespeichert: {capture_file.name}")
            except Exception as exc:
                self._queue_log(f"Fehler beim Speichern der Capture-Datei: {exc}")
            # === END ADDED ===
            
            if bus is not None:
                try:
                    bus.shutdown()
                except Exception:
                    pass
            self.after(0, self._on_worker_finished)

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
