from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from ...trigger_finder import PROFILES, DETECTORS, TriggerFinderRunner


class TriggerFinderPage(ttk.Frame):
    """GUI wrapper around :class:`TriggerFinderRunner`."""

    def __init__(self, parent, app):
        super().__init__(parent, style="Card.TFrame")
        self.app = app

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.runner: Optional[TriggerFinderRunner] = None

        self._build_ui()
        self._process_log_queue()
        self._update_option_visibility()

    # ---- UI construction -------------------------------------------------

    def _build_ui(self) -> None:
        self.inner = ttk.Frame(self, padding=24, style="Card.TFrame")
        self.inner.pack(fill="both", expand=True)

        header = ttk.Frame(self.inner, style="Card.TFrame")
        header.pack(fill="x")

        self.head = ttk.Label(
            header,
            text="Trigger Finder",
            style="Card.TLabel",
            font=("Segoe UI", 16, "bold"),
        )
        self.head.pack(side="left")

        self.back_btn = ttk.Button(header, text="← Zurück", command=lambda: self.app.show("MainMenu"))
        try:
            self.back_btn.configure(style="Red.TButton")
        except Exception:
            pass
        self.back_btn.pack(side="right")

        self.form = ttk.Frame(self.inner, padding=(0, 16), style="Card.TFrame")
        self.form.pack(fill="x")

        # Profile selection
        profile_row = ttk.Frame(self.form, style="Card.TFrame")
        profile_row.pack(fill="x", pady=4)
        ttk.Label(profile_row, text="Profil:", style="Card.TLabel").pack(side="left")
        self.profile_var = tk.StringVar(value=next(iter(PROFILES.keys())))
        self.profile_combo = ttk.Combobox(
            profile_row,
            textvariable=self.profile_var,
            values=list(PROFILES.keys()),
            state="readonly",
            width=18,
        )
        self.profile_combo.pack(side="left", padx=(8, 0))

        # Target selection
        target_row = ttk.Frame(self.form, style="Card.TFrame")
        target_row.pack(fill="x", pady=4)
        ttk.Label(target_row, text="Target:", style="Card.TLabel").pack(side="left")
        self.target_var = tk.StringVar(value=next(iter(DETECTORS.keys())))
        self.target_combo = ttk.Combobox(
            target_row,
            textvariable=self.target_var,
            values=list(DETECTORS.keys()),
            state="readonly",
            width=18,
        )
        self.target_combo.pack(side="left", padx=(8, 0))
        self.target_combo.bind("<<ComboboxSelected>>", lambda *_: self._update_option_visibility())

        # UDS options
        self.uds_frame = ttk.LabelFrame(self.form, text="UDS Parameter", padding=12)
        ttk.Label(self.uds_frame, text="DID:", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.uds_did_var = tk.StringVar()
        ttk.Entry(self.uds_frame, textvariable=self.uds_did_var, width=12).grid(row=0, column=1, padx=6, sticky="w")

        ttk.Label(self.uds_frame, text="Operator:", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        self.uds_op_var = tk.StringVar(value=">")
        ttk.Combobox(
            self.uds_frame,
            textvariable=self.uds_op_var,
            values=[">", ">=", "==", "!=", "<", "<="],
            state="readonly",
            width=5,
        ).grid(row=0, column=3, padx=6, sticky="w")

        ttk.Label(self.uds_frame, text="Schwelle:", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.uds_th_var = tk.StringVar()
        ttk.Entry(self.uds_frame, textvariable=self.uds_th_var, width=12).grid(row=1, column=1, padx=6, sticky="w", pady=(6, 0))

        ttk.Label(self.uds_frame, text="Byte-Index:", style="Card.TLabel").grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.uds_index_var = tk.StringVar()
        ttk.Entry(self.uds_frame, textvariable=self.uds_index_var, width=6).grid(row=1, column=3, padx=6, sticky="w", pady=(6, 0))

        # CAN bit options
        self.can_frame = ttk.LabelFrame(self.form, text="CAN Bit", padding=12)
        ttk.Label(self.can_frame, text="CAN-ID:", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.can_id_var = tk.StringVar()
        ttk.Entry(self.can_frame, textvariable=self.can_id_var, width=12).grid(row=0, column=1, padx=6, sticky="w")

        ttk.Label(self.can_frame, text="Byte:", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        self.can_byte_var = tk.StringVar()
        ttk.Entry(self.can_frame, textvariable=self.can_byte_var, width=6).grid(row=0, column=3, padx=6, sticky="w")

        ttk.Label(self.can_frame, text="Maske:", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.can_mask_var = tk.StringVar()
        ttk.Entry(self.can_frame, textvariable=self.can_mask_var, width=12).grid(row=1, column=1, padx=6, sticky="w", pady=(6, 0))

        ttk.Label(self.can_frame, text="Wert:", style="Card.TLabel").grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.can_value_var = tk.StringVar()
        ttk.Entry(self.can_frame, textvariable=self.can_value_var, width=12).grid(row=1, column=3, padx=6, sticky="w", pady=(6, 0))

        # Buttons
        btn_row = ttk.Frame(self.inner, padding=(0, 12), style="Card.TFrame")
        btn_row.pack(fill="x")
        self.start_btn = ttk.Button(btn_row, text="Start", command=self._start_trigger_finder)
        self.stop_btn = ttk.Button(btn_row, text="Stopp", command=self._stop_trigger_finder, state="disabled")
        try:
            self.start_btn.configure(style="Red.TButton")
            self.stop_btn.configure(style="Red.TButton")
        except Exception:
            pass
        self.start_btn.pack(side="left", padx=(0, 8), ipadx=12, ipady=6)
        self.stop_btn.pack(side="left", padx=(0, 8), ipadx=12, ipady=6)

        # Status text
        self.status = ttk.Label(self.inner, text="", style="Card.TLabel")
        self.status.pack(fill="x", pady=(0, 8))
        self.status.configure(text="Bereit")

        # Log output
        log_container = ttk.Frame(self.inner, style="Card.TFrame")
        log_container.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_container, height=18, wrap="word", state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_container, orient="vertical", command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    # ---- Trigger Finder control ----------------------------------------

    def _start_trigger_finder(self) -> None:
        if self.runner and self.runner.is_running():
            messagebox.showinfo("Trigger Finder", "Der Trigger Finder läuft bereits.")
            return

        profile = self.profile_var.get()
        target = self.target_var.get()
        kwargs = {}

        try:
            if target == "UDS_CUSTOM":
                kwargs["uds_did"] = self._parse_int(self.uds_did_var.get(), "DID")
                kwargs["uds_op"] = self.uds_op_var.get() or ">"
                kwargs["uds_th"] = self._parse_float(self.uds_th_var.get(), default=0.0)
                kwargs["uds_index"] = self._parse_int(self.uds_index_var.get() or "0", "Byte-Index")
            elif target == "CAN_BIT":
                kwargs["can_id"] = self._parse_int(self.can_id_var.get(), "CAN-ID")
                kwargs["can_byte"] = self._parse_int(self.can_byte_var.get(), "Byte")
                kwargs["can_mask"] = self._parse_int(self.can_mask_var.get(), "Maske")
                kwargs["can_value"] = self._parse_int(self.can_value_var.get(), "Wert")
        except ValueError as exc:
            messagebox.showerror("Trigger Finder", str(exc))
            return

        self.runner = TriggerFinderRunner(
            profile=profile,
            target=target,
            log_callback=self._threadsafe_log,
            **kwargs,
        )

        if not self.runner.start():
            messagebox.showerror("Trigger Finder", "Trigger Finder konnte nicht gestartet werden.")
            return

        self._set_running_state(True)
        self._threadsafe_log("Trigger Finder gestartet …")
        self.status.configure(text="Laufend…")
        self.after(400, self._poll_runner)

    def _stop_trigger_finder(self) -> None:
        if self.runner:
            self.runner.stop()
            self.status.configure(text="Stop angefordert…")

    def destroy(self) -> None:  # type: ignore[override]
        if self.runner:
            self.runner.stop()
        super().destroy()

    # ---- Helper methods -------------------------------------------------

    def _threadsafe_log(self, message: str) -> None:
        if not message.endswith("\n"):
            message += "\n"
        self.log_queue.put(message)

    def _process_log_queue(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert(tk.END, line)
                self.log_text.see(tk.END)
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        finally:
            self.after(200, self._process_log_queue)

    def _poll_runner(self) -> None:
        if self.runner and self.runner.is_running():
            self.after(400, self._poll_runner)
        else:
            self._set_running_state(False)
            self.status.configure(text="Bereit")
            self.runner = None

    def _set_running_state(self, running: bool) -> None:
        state = "disabled" if running else "readonly"
        self.profile_combo.configure(state=state)
        self.target_combo.configure(state=state)

        for frame in (self.uds_frame, self.can_frame):
            for child in frame.winfo_children():
                try:
                    if isinstance(child, ttk.Label):
                        continue
                    if isinstance(child, ttk.Combobox):
                        child.configure(state="disabled" if running else "readonly")
                    else:
                        child.configure(state="disabled" if running else "normal")
                except Exception:
                    pass

        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def _update_option_visibility(self) -> None:
        target = self.target_var.get()

        if target == "UDS_CUSTOM":
            if not self.uds_frame.winfo_ismapped():
                self.uds_frame.pack(fill="x", pady=4)
        else:
            self.uds_frame.pack_forget()

        if target == "CAN_BIT":
            if not self.can_frame.winfo_ismapped():
                self.can_frame.pack(fill="x", pady=4)
        else:
            self.can_frame.pack_forget()

    def _parse_int(self, text: str, label: str) -> int:
        text = text.strip()
        if not text:
            raise ValueError(f"{label}: Bitte einen Wert eingeben.")
        try:
            return int(text, 0)
        except ValueError:
            raise ValueError(f"{label}: Ungültige Zahl '{text}'.")

    def _parse_float(self, text: str, *, default: float = 0.0) -> float:
        text = text.strip()
        if not text:
            return default
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"Schwelle: Ungültige Zahl '{text}'.")

    # ---- Theme ----------------------------------------------------------

    def apply_theme(self, bg, fg, card, paint_button) -> None:  # type: ignore[override]
        for widget in (self, self.inner, self.form):
            widget.configure(style="Card.TFrame")

        style = ttk.Style()
        style.configure("Card.TLabelframe", background=card, foreground=fg)
        style.configure("Card.TLabelframe.Label", background=card, foreground=fg, font=("Segoe UI", 10, "bold"))

        for frame in (self.uds_frame, self.can_frame):
            frame.configure(style="Card.TLabelframe")
            try:
                frame.configure(labelanchor="nw")
            except Exception:
                pass
            for child in frame.winfo_children():
                if isinstance(child, ttk.Label):
                    child.configure(style="Card.TLabel")

        self.head.configure(style="Card.TLabel")
        self.status.configure(style="Card.TLabel")

        for btn in (self.back_btn, self.start_btn, self.stop_btn):
            try:
                paint_button(btn)
            except Exception:
                try:
                    btn.configure(style="Red.TButton")
                except Exception:
                    pass

        text_bg = card or "#F6F6F6"
        self.log_text.configure(bg=text_bg, fg=fg, insertbackground=fg, highlightbackground=text_bg, highlightcolor=text_bg)
