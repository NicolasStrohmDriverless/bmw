from __future__ import annotations

import csv
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import List, Optional

from analysis.live_sniffer import LiveSniffer
from analysis.models import FrameFilter, FrameStore, RawCanFrame, compare_traces
from analysis.trace_parser import parse_pcan_trc
from can_utils import open_sniffer_bus
from config import THN_RED, THN_WHITE


HANDBRAKE_PRESET = {
    "id_exact": "65E",
    "payload_contains": "F1210001FFFFFFFF",
    "min_count": "1",
}


class AutoSearchPage(ttk.Frame):
    """Read-only CAN sniffer and trace analyzer.

    This page is intentionally passive. It never transmits CAN traffic and only
    consumes frames from live receive paths or offline traces.
    """

    def __init__(self, parent, app):
        super().__init__(parent, style="Card.TFrame")
        self.app = app

        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._store = FrameStore(max_frames=5000)
        self._sniffer = LiveSniffer(open_sniffer_bus)
        self._refresh_lock = threading.Lock()

        self._primary_buttons: list[ttk.Button] = []
        self._secondary_buttons: list[ttk.Button] = []

        self._frozen = False
        self._trace_a: List[RawCanFrame] = []
        self._trace_b: List[RawCanFrame] = []

        self._build_ui()
        self._process_queue()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=16, style="Card.TFrame")
        outer.pack(fill="both", expand=True)

        hero = ttk.Frame(outer, style="Card.TFrame", padding=(20, 18))
        hero.pack(fill="x")

        self.hero_accent = tk.Frame(hero, height=4, bd=0, highlightthickness=0)
        self.hero_accent.pack(fill="x", pady=(0, 14))

        hero_top = ttk.Frame(hero, style="Card.TFrame")
        hero_top.pack(fill="x")

        self.badge_lbl = ttk.Label(hero_top, text="READ ONLY", style="Card.TLabel")
        self.badge_lbl.pack(side="left")

        self.title_lbl = ttk.Label(
            hero_top,
            text="Read-only CAN Sniffer / Trace Analyzer",
            style="Card.TLabel",
            font=("Segoe UI", 18, "bold"),
        )
        self.title_lbl.pack(side="left", padx=(12, 0))

        self.back_btn = ttk.Button(hero_top, text="← Zurück", command=lambda: self.app.show("TestPage"))
        self._secondary_buttons.append(self.back_btn)
        self.back_btn.pack(side="right")

        self.subtitle_lbl = ttk.Label(
            hero,
            text="Live-Sniffing und Trace-Analyse ohne Senden. Presets, Filter und Kandidaten laufen jetzt in einer ruhigeren, klareren Oberfläche.",
            style="Card.TLabel",
            wraplength=900,
            justify="left",
        )
        self.subtitle_lbl.pack(anchor="w", pady=(10, 0))

        hero_actions = ttk.Frame(hero, style="Card.TFrame")
        hero_actions.pack(fill="x", pady=(14, 0))

        self.example_btn = ttk.Button(hero_actions, text="Handbremse-Beispiel laden", command=self._load_handbrake_preset)
        self.spoofing_btn = ttk.Button(hero_actions, text="Spoofing", command=lambda: self.app.show("SpoofingPage"))
        self.reset_btn = ttk.Button(hero_actions, text="Filter zurücksetzen", command=self._reset_filters)
        self._primary_buttons.append(self.example_btn)
        self._secondary_buttons.append(self.spoofing_btn)
        self._secondary_buttons.append(self.reset_btn)
        self.example_btn.pack(side="left", padx=(0, 8))
        self.spoofing_btn.pack(side="left", padx=(0, 8))
        self.reset_btn.pack(side="left", padx=(0, 8))

        # Fixed stack layout to guarantee controls stay above tables
        controls_frame = ttk.Frame(outer, style="Card.TFrame")
        controls_frame.pack(fill="x", expand=False, pady=(12, 0))

        mode_row = ttk.Frame(controls_frame, style="Card.TFrame")
        mode_row.pack(fill="x", pady=(0, 0))

        mode_row.columnconfigure(0, weight=0)
        mode_row.columnconfigure(1, weight=0)
        mode_row.columnconfigure(2, weight=0)
        mode_row.columnconfigure(3, weight=1)

        ttk.Label(mode_row, text="Modus:", style="Card.TLabel").pack(side="left")
        self.mode_var = tk.StringVar(value="Live Sniff Mode")
        self.mode_combo = ttk.Combobox(
            mode_row,
            textvariable=self.mode_var,
            values=["Live Sniff Mode", "Offline Trace Mode"],
            state="readonly",
            width=24,
        )
        self.mode_combo.pack(side="left", padx=(6, 10))

        ttk.Label(mode_row, text="Rolling Buffer:", style="Card.TLabel").pack(side="left")
        self.max_frames_var = tk.StringVar(value="5000")
        ttk.Entry(mode_row, textvariable=self.max_frames_var, width=8).pack(side="left", padx=(6, 12))

        self.start_btn = ttk.Button(mode_row, text="Start Capture", command=self._start_capture)
        self.stop_btn = ttk.Button(mode_row, text="Stop", command=self._stop_capture, state="disabled")
        self.freeze_btn = ttk.Button(mode_row, text="Freeze View", command=self._toggle_freeze)
        self.clear_btn = ttk.Button(mode_row, text="Clear", command=self._clear_data)
        self._primary_buttons.append(self.start_btn)
        self._secondary_buttons.extend([self.stop_btn, self.freeze_btn, self.clear_btn])
        for btn in (self.start_btn, self.stop_btn, self.freeze_btn, self.clear_btn):
            btn.pack(side="left", padx=(0, 8))

        trace_row = ttk.Frame(controls_frame, style="Card.TFrame")
        trace_row.pack(fill="x", pady=(10, 0))

        self.load_trace_btn = ttk.Button(trace_row, text="Load .trc", command=self._load_trace)
        self.load_trace_a_btn = ttk.Button(trace_row, text="Load Trace A", command=lambda: self._load_trace_pair("A"))
        self.load_trace_b_btn = ttk.Button(trace_row, text="Load Trace B", command=lambda: self._load_trace_pair("B"))
        self.compare_btn = ttk.Button(trace_row, text="Compare A/B", command=self._compare_traces)
        self.export_btn = ttk.Button(trace_row, text="Export CSV", command=self._export_csv)
        self._primary_buttons.extend([self.load_trace_btn, self.load_trace_a_btn, self.load_trace_b_btn, self.compare_btn])
        self._secondary_buttons.append(self.export_btn)
        for btn in (self.load_trace_btn, self.load_trace_a_btn, self.load_trace_b_btn, self.compare_btn, self.export_btn):
            btn.pack(side="left", padx=(0, 8))

        filter_row = ttk.LabelFrame(controls_frame, text="Filter", padding=12, style="Modern.Section.TLabelframe")
        filter_row.pack(fill="x", pady=(10, 0))

        ttk.Label(filter_row, text="ID exakt:", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(filter_row, text="ID min:", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Label(filter_row, text="ID max:", style="Card.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Label(filter_row, text="Payload enthält:", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(filter_row, text="Min Count:", style="Card.TLabel").grid(row=1, column=2, sticky="w", pady=(6, 0))

        self.id_exact_var = tk.StringVar()
        self.id_min_var = tk.StringVar()
        self.id_max_var = tk.StringVar()
        self.payload_filter_var = tk.StringVar()
        self.min_count_var = tk.StringVar(value="1")
        self.hide_unchanged_var = tk.BooleanVar(value=False)
        self.bookmarks_only_var = tk.BooleanVar(value=False)

        ttk.Entry(filter_row, textvariable=self.id_exact_var, width=10).grid(row=0, column=1, padx=6, sticky="w")
        ttk.Entry(filter_row, textvariable=self.id_min_var, width=10).grid(row=0, column=3, padx=6, sticky="w")
        ttk.Entry(filter_row, textvariable=self.id_max_var, width=10).grid(row=0, column=5, padx=6, sticky="w")
        ttk.Entry(filter_row, textvariable=self.payload_filter_var, width=24).grid(row=1, column=1, padx=6, sticky="w", pady=(6, 0))
        ttk.Entry(filter_row, textvariable=self.min_count_var, width=10).grid(row=1, column=3, padx=6, sticky="w", pady=(6, 0))

        ttk.Checkbutton(filter_row, text="Hide unchanged periodic", variable=self.hide_unchanged_var).grid(
            row=0, column=6, padx=(12, 0), sticky="w"
        )
        ttk.Checkbutton(filter_row, text="Bookmarks only", variable=self.bookmarks_only_var).grid(
            row=1, column=6, padx=(12, 0), sticky="w", pady=(6, 0)
        )

        self.apply_filter_btn = ttk.Button(filter_row, text="Apply", command=self._refresh_views)
        self.bookmark_btn = ttk.Button(filter_row, text="Bookmark selected ID", command=self._bookmark_selected)
        self._primary_buttons.append(self.apply_filter_btn)
        self._secondary_buttons.append(self.bookmark_btn)
        self.apply_filter_btn.grid(row=0, column=7, padx=(12, 0), sticky="w")
        self.bookmark_btn.grid(row=1, column=7, padx=(12, 0), sticky="w", pady=(6, 0))

        analysis_row = ttk.LabelFrame(controls_frame, text="Analysis", padding=12, style="Modern.Section.TLabelframe")
        analysis_row.pack(fill="x", pady=(10, 0))

        ttk.Label(analysis_row, text="Window A (start,end s):", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.win_a_start = tk.StringVar(value="0")
        self.win_a_end = tk.StringVar(value="5")
        self.win_b_start = tk.StringVar(value="5")
        self.win_b_end = tk.StringVar(value="10")
        ttk.Entry(analysis_row, textvariable=self.win_a_start, width=8).grid(row=0, column=1, padx=(6, 2), sticky="w")
        ttk.Entry(analysis_row, textvariable=self.win_a_end, width=8).grid(row=0, column=2, padx=(2, 10), sticky="w")

        ttk.Label(analysis_row, text="Window B (start,end s):", style="Card.TLabel").grid(row=0, column=3, sticky="w")
        ttk.Entry(analysis_row, textvariable=self.win_b_start, width=8).grid(row=0, column=4, padx=(6, 2), sticky="w")
        ttk.Entry(analysis_row, textvariable=self.win_b_end, width=8).grid(row=0, column=5, padx=(2, 10), sticky="w")

        self.detect_btn = ttk.Button(analysis_row, text="Detect candidates", command=self._detect_candidates)
        self.diff_btn = ttk.Button(analysis_row, text="Diff selected ID", command=self._diff_selected_id)
        self._primary_buttons.extend([self.detect_btn, self.diff_btn])
        self.detect_btn.grid(row=0, column=6, padx=(8, 0), sticky="w")
        self.diff_btn.grid(row=0, column=7, padx=(8, 0), sticky="w")

        # Tabs for tables and guide
        tabs = ttk.Notebook(outer)
        tabs.pack(fill="both", expand=True, pady=(10, 0))

        # Tab 1: Tables and Analysis
        tables_tab = ttk.Frame(tabs, style="Card.TFrame")
        tabs.add(tables_tab, text="Analyse & Ergebnisse")

        split = ttk.Panedwindow(tables_tab, orient="vertical")
        split.pack(fill="both", expand=True)

        top_panel = ttk.Frame(split, style="Card.TFrame")
        bottom_panel = ttk.Frame(split, style="Card.TFrame")
        split.add(top_panel, weight=2)
        split.add(bottom_panel, weight=3)

        self.frame_tree = ttk.Treeview(
            top_panel,
            columns=("timestamp", "id", "dlc", "data", "count", "delta", "rate", "source", "channel", "tag"),
            show="headings",
            height=10,
        )
        for col, width in (
            ("timestamp", 140),
            ("id", 80),
            ("dlc", 55),
            ("data", 260),
            ("count", 70),
            ("delta", 90),
            ("rate", 90),
            ("source", 110),
            ("channel", 90),
            ("tag", 120),
        ):
            self.frame_tree.heading(col, text=col)
            self.frame_tree.column(col, width=width, anchor="w")
        self.frame_tree.pack(side="left", fill="both", expand=True)

        frame_scroll = ttk.Scrollbar(top_panel, orient="vertical", command=self.frame_tree.yview)
        frame_scroll.pack(side="right", fill="y")
        self.frame_tree.configure(yscrollcommand=frame_scroll.set)
        self._enable_tree_sorting(self.frame_tree)

        left_bottom = ttk.Frame(bottom_panel, style="Card.TFrame")
        right_bottom = ttk.Frame(bottom_panel, style="Card.TFrame")
        left_bottom.pack(side="left", fill="both", expand=True)
        right_bottom.pack(side="left", fill="both", expand=True, padx=(8, 0))

        self.group_tree = ttk.Treeview(
            left_bottom,
            columns=("id", "total", "distinct", "first", "last", "avg_period_ms"),
            show="headings",
            height=11,
        )
        for col, width in (
            ("id", 80),
            ("total", 70),
            ("distinct", 70),
            ("first", 120),
            ("last", 120),
            ("avg_period_ms", 120),
        ):
            self.group_tree.heading(col, text=col)
            self.group_tree.column(col, width=width, anchor="w")
        self.group_tree.pack(fill="both", expand=True)
        self._enable_tree_sorting(self.group_tree)

        self.report = tk.Text(right_bottom, height=8, wrap="word", state="disabled", bd=0, highlightthickness=1)
        self.report.pack(fill="both", expand=True)

        # Tab 2: Guide/Instructions
        guide_tab = ttk.Frame(tabs, style="Card.TFrame", padding=20)
        tabs.add(guide_tab, text="📖 Anleitung")
        
        guide_text = (
            "🔹 LIVE-SNIFFING\n"
            "Wähle einen Modus (Live Sniff oder Offline Trace), stelle den Rolling Buffer ein, und klicke 'Start Capture' um CAN-Frames Live zu empfangen. Frames werden in der Echtzeitansicht oben angezeigt.\n\n"
            "🔹 FILTER & PRESETS\n"
            "Verwende die Filter um Frames nach ID (exakt oder Min-Max), Payload-Inhalten oder Häufigkeit zu durchsuchen. Das 'Handbremse-Beispiel'-Preset lädt schnell vordefinierte Werte für Tests. 'Bookmarks only' zeigt nur markierte IDs an.\n\n"
            "🔹 ANALYSE\n"
            "Oben siehst du alle empfangenen Frames mit Timestamps, IDs, Payloads und Statistiken (count, rate). Unten links sind Frames gruppiert nach ID mit Statistiken (total, distinct values, Durchschnittszeitraum). Rechts: Generated Reports.\n\n"
            "🔹 AKTIONEN\n"
            "• Load .trc: Lade Trace-Dateien von der Festplatte\n"
            "• Load Trace A/B: Lade zwei Traces zum Vergleichen\n"
            "• Compare A/B: Zeigt Unterschiede zwischen den Traces\n"
            "• Detect candidates: Findet verdächtige/interessante CAN-Messages\n"
            "• Diff selected ID: Vergleicht einzelne IDs detailliert\n"
            "• Export CSV: Exportiert Daten als CSV-Datei\n\n"
            "⚠️  READ-ONLY MODUS\n"
            "Diese Seite empfängt nur CAN-Frames. Der CAN-Bus wird niemals beeinflusst oder beschrieben. Alle Operationen sind nicht-destruktiv."
        )
        guide_wrap = ttk.Frame(guide_tab, style="Card.TFrame")
        guide_wrap.pack(fill="both", expand=True)

        guide_scroll = ttk.Scrollbar(guide_wrap, orient="vertical")
        guide_scroll.pack(side="right", fill="y")

        self.guide_text = tk.Text(
            guide_wrap,
            wrap="word",
            state="normal",
            bd=0,
            highlightthickness=1,
            yscrollcommand=guide_scroll.set,
        )
        self.guide_text.insert("1.0", guide_text)
        self.guide_text.configure(state="disabled")
        self.guide_text.pack(side="left", fill="both", expand=True)
        guide_scroll.configure(command=self.guide_text.yview)

        tabs.select(tables_tab)

        self.status = ttk.Label(outer, text="Bereit (read-only)", style="Card.TLabel", padding=(10, 8))
        self.status.pack(fill="x", pady=(8, 0))

    # --------------------------------------------------------------- Actions

    def _start_capture(self) -> None:
        mode = self.mode_var.get()
        self._set_buffer_from_ui()

        if mode == "Offline Trace Mode":
            self.status.configure(text="Offline-Modus: Bitte .trc laden.")
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            return

        if self._sniffer.is_running():
            messagebox.showinfo("Sniffer", "Capture läuft bereits.")
            return

        started = self._sniffer.start(self._queue)
        if not started:
            messagebox.showerror("Sniffer", "Live-Sniffer konnte nicht gestartet werden.")
            return

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status.configure(text="Live-Sniffing gestartet (read-only).")

    def _stop_capture(self) -> None:
        if self._sniffer.is_running():
            self._sniffer.stop()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status.configure(text="Capture gestoppt.")

    def _toggle_freeze(self) -> None:
        self._frozen = not self._frozen
        self.freeze_btn.configure(text=("Unfreeze View" if self._frozen else "Freeze View"))
        self.status.configure(text=("Ansicht eingefroren." if self._frozen else "Ansicht aktiv."))
        if not self._frozen:
            self._refresh_views()

    def _clear_data(self) -> None:
        self._store.clear()
        self._refresh_views()
        self._set_report("Datenpuffer geleert.")

    def _load_trace(self) -> None:
        path = filedialog.askopenfilename(
            title="PCAN .trc laden",
            filetypes=(("PCAN Trace", "*.trc"), ("Alle Dateien", "*.*")),
        )
        if not path:
            return

        self._set_buffer_from_ui()
        frames, warnings = parse_pcan_trc(path)
        if not frames and warnings:
            messagebox.showerror("Trace", "Kein Frame geparst.\n" + "\n".join(warnings[:10]))
            return

        self._store.clear()
        for frame in frames:
            self._store.add_frame(frame)

        self._refresh_views()
        status = f"Trace geladen: {os.path.basename(path)} ({len(frames)} Frames)"
        if warnings:
            status += f" | Warnungen: {len(warnings)}"
        self.status.configure(text=status)

    def _load_handbrake_preset(self) -> None:
        self.id_exact_var.set(HANDBRAKE_PRESET["id_exact"])
        self.payload_filter_var.set(HANDBRAKE_PRESET["payload_contains"])
        self.min_count_var.set(HANDBRAKE_PRESET["min_count"])
        self.hide_unchanged_var.set(True)
        self.bookmarks_only_var.set(False)
        self.mode_var.set("Offline Trace Mode")
        self.status.configure(text="Handbremse-Beispiel geladen: Filter auf 0x65E / F1210001FFFFFFFF gesetzt.")
        self._refresh_views()

    def _reset_filters(self) -> None:
        self.id_exact_var.set("")
        self.id_min_var.set("")
        self.id_max_var.set("")
        self.payload_filter_var.set("")
        self.min_count_var.set("1")
        self.hide_unchanged_var.set(False)
        self.bookmarks_only_var.set(False)
        self.status.configure(text="Filter zurückgesetzt.")
        self._refresh_views()

    def _load_trace_pair(self, which: str) -> None:
        path = filedialog.askopenfilename(
            title=f"Trace {which} laden",
            filetypes=(("PCAN Trace", "*.trc"), ("Alle Dateien", "*.*")),
        )
        if not path:
            return
        frames, warnings = parse_pcan_trc(path)
        if warnings:
            self._set_report("\n".join(warnings[:10]))
        if which == "A":
            self._trace_a = frames
        else:
            self._trace_b = frames
        self.status.configure(text=f"Trace {which} geladen: {os.path.basename(path)} ({len(frames)} Frames)")

    def _compare_traces(self) -> None:
        if not self._trace_a or not self._trace_b:
            messagebox.showinfo("Vergleich", "Bitte zuerst Trace A und B laden.")
            return

        cmp_result = compare_traces(self._trace_a, self._trace_b)
        lines: List[str] = []
        lines.append("Trace Vergleich (read-only):")
        lines.append("")
        lines.append(f"Nur in A: {len(cmp_result.only_in_a)}")
        lines.extend(cmp_result.only_in_a[:20])
        lines.append("")
        lines.append(f"Nur in B: {len(cmp_result.only_in_b)}")
        lines.extend(cmp_result.only_in_b[:20])
        lines.append("")
        lines.append(f"Payload-Verteilungsänderungen: {len(cmp_result.payload_distribution_changes)}")
        lines.extend(cmp_result.payload_distribution_changes[:30])
        lines.append("")
        lines.append(f"Frequenzänderungen: {len(cmp_result.frequency_changes)}")
        lines.extend(cmp_result.frequency_changes[:30])
        self._set_report("\n".join(lines))

    def _detect_candidates(self) -> None:
        try:
            window_a = (float(self.win_a_start.get()), float(self.win_a_end.get()))
            window_b = (float(self.win_b_start.get()), float(self.win_b_end.get()))
        except ValueError:
            messagebox.showerror("Analyse", "Fenstergrenzen müssen Zahlen sein.")
            return

        candidates = self._store.detect_window_changes(window_a, window_b)
        lines = ["Candidate trigger detector (read-only):", ""]
        for item in candidates[:50]:
            lines.append(
                f"0x{item.can_id:03X}: {item.freq_window_a_hz:.2f}Hz -> {item.freq_window_b_hz:.2f}Hz | geänderte Bytes: {item.changed_bytes}"
            )

        if len(lines) == 2:
            lines.append("Keine signifikanten Änderungen erkannt.")
        self._set_report("\n".join(lines))

    def _diff_selected_id(self) -> None:
        can_id = self._selected_can_id()
        if can_id is None:
            messagebox.showinfo("Diff", "Bitte zuerst einen Frame oder eine Gruppe auswählen.")
            return

        diff = self._store.payload_diff_for_id(can_id)
        lines = [f"Payload-Diff 0x{can_id:03X}:"]
        lines.append(f"Changing bytes: {diff.changing_bytes}")
        lines.append("Min/Max je Byte:")
        for idx, (mn, mx) in sorted(diff.min_max_per_byte.items()):
            lines.append(f"  Byte {idx}: {mn:02X}..{mx:02X}")
        lines.append("Bit-Flips je Byte:")
        for idx, cnt in sorted(diff.bit_flip_counts.items()):
            lines.append(f"  Byte {idx}: {cnt}")
        self._set_report("\n".join(lines))

    def _bookmark_selected(self) -> None:
        can_id = self._selected_can_id()
        if can_id is None:
            messagebox.showinfo("Bookmark", "Bitte zuerst eine Zeile auswählen.")
            return

        current_tag = self._store.bookmarks.get(can_id, "")
        tag = simpledialog.askstring("Bookmark", f"Tag für 0x{can_id:03X}:", initialvalue=current_tag)
        if tag is None:
            return
        self._store.bookmark_id(can_id, tag)
        self._refresh_views()

    def _export_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            title="CSV exportieren",
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"), ("Alle Dateien", "*.*")),
        )
        if not path:
            return

        rows = self._store.build_view(self._read_filter())
        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["timestamp", "id", "dlc", "data_hex", "count", "source"])
                for row in rows:
                    writer.writerow(
                        [
                            f"{row['timestamp']:.6f}",
                            f"0x{row['id']:03X}",
                            row["dlc"],
                            row["data_hex"].replace(" ", ""),
                            row["count"],
                            row["source"],
                        ]
                    )
            self.status.configure(text=f"CSV exportiert: {os.path.basename(path)}")
        except OSError as exc:
            messagebox.showerror("Export", f"CSV konnte nicht geschrieben werden:\n{exc}")

    # -------------------------------------------------------------- Queue/UI

    def _process_queue(self) -> None:
        dirty = False
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "frame":
                    self._store.add_frame(item[1])
                    dirty = True
                elif kind == "sniffer_error":
                    self.status.configure(text=f"Sniffer-Fehler: {item[1]}")
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                elif kind == "sniffer_status":
                    self.status.configure(text=item[1])
                elif kind == "sniffer_stopped":
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
        except queue.Empty:
            pass

        if dirty and not self._frozen:
            self._refresh_views()

        self.after(120, self._process_queue)

    def _refresh_views(self) -> None:
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            frame_rows = self._store.build_view(self._read_filter())
            self._fill_frame_tree(frame_rows)
            self._fill_group_tree()
        finally:
            self._refresh_lock.release()

    def _fill_frame_tree(self, rows: List[dict]) -> None:
        for iid in self.frame_tree.get_children(""):
            self.frame_tree.delete(iid)

        for row in rows:
            delta_txt = "" if row["delta_ms"] is None else f"{row['delta_ms']:.2f}"
            rate_txt = "" if row["rate_hz"] is None else f"{row['rate_hz']:.2f}"
            self.frame_tree.insert(
                "",
                "end",
                values=(
                    f"{row['timestamp']:.6f}",
                    f"0x{row['id']:03X}",
                    row["dlc"],
                    row["data_hex"],
                    row["count"],
                    delta_txt,
                    rate_txt,
                    row["source"],
                    row.get("channel", ""),
                    row["tag"],
                ),
            )

    def _fill_group_tree(self) -> None:
        for iid in self.group_tree.get_children(""):
            self.group_tree.delete(iid)

        for item in self._store.group_by_id():
            self.group_tree.insert(
                "",
                "end",
                values=(
                    f"0x{item.can_id:03X}",
                    item.total_count,
                    item.distinct_payloads,
                    f"{item.first_seen:.6f}",
                    f"{item.last_seen:.6f}",
                    f"{item.avg_period_ms:.2f}",
                ),
            )

    # --------------------------------------------------------------- Helpers

    def _set_report(self, text: str) -> None:
        self.report.configure(state="normal")
        self.report.delete("1.0", tk.END)
        self.report.insert(tk.END, text)
        self.report.configure(state="disabled")

    def _enable_tree_sorting(self, tree: ttk.Treeview) -> None:
        for col in tree["columns"]:
            tree.heading(col, command=lambda c=col, t=tree: self._sort_tree_by_column(t, c, False))

    def _sort_tree_by_column(self, tree: ttk.Treeview, column: str, reverse: bool) -> None:
        rows = [(tree.set(item, column), item) for item in tree.get_children("")]

        def key_fn(entry: tuple[str, str]):
            value = (entry[0] or "").strip()
            norm = value.replace("0x", "").replace("0X", "")
            try:
                if norm and all(ch in "0123456789ABCDEFabcdef" for ch in norm):
                    return (0, int(norm, 16))
                return (1, float(value))
            except ValueError:
                return (2, value.lower())

        rows.sort(key=key_fn, reverse=reverse)
        for index, (_value, item) in enumerate(rows):
            tree.move(item, "", index)

        tree.heading(column, command=lambda: self._sort_tree_by_column(tree, column, not reverse))

    def _selected_can_id(self) -> Optional[int]:
        selection = self.frame_tree.selection()
        if selection:
            values = self.frame_tree.item(selection[0], "values")
            if len(values) >= 2:
                try:
                    return int(str(values[1]), 16)
                except ValueError:
                    pass

        selection_group = self.group_tree.selection()
        if selection_group:
            values = self.group_tree.item(selection_group[0], "values")
            if values:
                try:
                    return int(str(values[0]), 16)
                except ValueError:
                    pass
        return None

    def _set_buffer_from_ui(self) -> None:
        try:
            max_frames = int(self.max_frames_var.get())
            self._store.set_max_frames(max_frames)
        except ValueError:
            messagebox.showerror("Puffer", "Rolling Buffer muss eine Ganzzahl sein.")

    def _read_filter(self) -> FrameFilter:
        def parse_hex(value: str) -> Optional[int]:
            text = (value or "").strip().upper()
            if not text:
                return None
            return int(text, 16)

        min_count = 1
        try:
            min_count = max(1, int(self.min_count_var.get().strip() or "1"))
        except ValueError:
            min_count = 1

        try:
            return FrameFilter(
                id_exact=parse_hex(self.id_exact_var.get()),
                id_min=parse_hex(self.id_min_var.get()),
                id_max=parse_hex(self.id_max_var.get()),
                payload_contains=(self.payload_filter_var.get() or "").strip(),
                min_count=min_count,
                hide_unchanged_periodic=bool(self.hide_unchanged_var.get()),
                bookmarks_only=bool(self.bookmarks_only_var.get()),
            )
        except ValueError:
            messagebox.showerror("Filter", "Ungültiger Hex-Wert im Filter.")
            return FrameFilter(min_count=min_count)

    # -------------------------------------------------------------- Lifecycle

    def destroy(self) -> None:  # type: ignore[override]
        if self._sniffer.is_running():
            self._sniffer.stop()
        super().destroy()

    def apply_theme(self, bg, fg, card, paint_button):
        self._configure_styles(bg, fg, card)
        self.configure(style="Card.TFrame")
        if hasattr(self, "hero_accent"):
            self.hero_accent.configure(bg=THN_RED if not getattr(self.app, "is_dark", False) else THN_RED)
        self.badge_lbl.configure(style="Modern.Badge.TLabel")
        self.title_lbl.configure(style="Modern.Title.TLabel")
        self.subtitle_lbl.configure(style="Modern.Subtitle.TLabel")
        self.status.configure(style="Modern.Subtitle.TLabel")

        for btn in self._primary_buttons:
            try:
                btn.configure(style="ModernPrimary.TButton")
            except Exception:
                pass
        for btn in self._secondary_buttons:
            try:
                btn.configure(style="ModernSecondary.TButton")
            except Exception:
                pass

        text_bg = card or "#F6F6F6"
        self.report.configure(bg=text_bg, fg=fg, insertbackground=fg)
        if hasattr(self, "guide_text"):
            self.guide_text.configure(bg=text_bg, fg=fg, insertbackground=fg)
        try:
            self.frame_tree.configure(selectbackground=THN_RED, selectforeground=THN_WHITE)
            self.group_tree.configure(selectbackground=THN_RED, selectforeground=THN_WHITE)
        except Exception:
            pass

    def _configure_styles(self, bg, fg, card) -> None:
        style = getattr(self.app, "style", None)
        if style is None:
            return

        surface = card or "#F6F6F6"
        border = "#D9D9D9" if not getattr(self.app, "is_dark", False) else "#343434"
        muted = "#6B6B6B" if not getattr(self.app, "is_dark", False) else "#B8B8B8"

        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("Card.TFrame", background=surface, bordercolor=border)
        style.configure("Card.TLabel", background=surface, foreground=fg)
        style.configure("Modern.Title.TLabel", background=surface, foreground=fg, font=("Segoe UI", 18, "bold"))
        style.configure("Modern.Subtitle.TLabel", background=surface, foreground=muted, font=("Segoe UI", 10))
        style.configure("Modern.Badge.TLabel", background=surface, foreground=THN_RED, font=("Segoe UI", 9, "bold"))
        style.configure(
            "Modern.Section.TLabelframe",
            background=surface,
            bordercolor=border,
            relief="flat",
            padding=(12, 10),
        )
        style.configure(
            "Modern.Section.TLabelframe.Label",
            background=surface,
            foreground=fg,
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "ModernPrimary.TButton",
            background=THN_RED,
            foreground=THN_WHITE,
            padding=(14, 9),
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "ModernPrimary.TButton",
            background=[("pressed", "#9E2626"), ("active", "#B42B2B"), ("disabled", "#D8D8D8")],
            foreground=[("disabled", "#777777")],
        )
        style.configure(
            "ModernSecondary.TButton",
            background=surface,
            foreground=fg,
            padding=(14, 9),
            font=("Segoe UI", 10, "bold"),
            borderwidth=1,
            relief="solid",
        )
        style.map(
            "ModernSecondary.TButton",
            background=[("pressed", bg), ("active", bg), ("disabled", "#E2E2E2")],
            foreground=[("disabled", muted)],
        )
        style.configure(
            "Treeview",
            background=surface,
            fieldbackground=surface,
            foreground=fg,
            borderwidth=0,
            rowheight=30,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background=bg,
            foreground=fg,
            borderwidth=0,
            font=("Segoe UI", 9, "bold"),
            padding=(8, 6),
        )
        style.map(
            "Treeview",
            background=[("selected", THN_RED)],
            foreground=[("selected", THN_WHITE)],
        )
