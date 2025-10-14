from __future__ import annotations
from tkinter import ttk, messagebox
from typing import Optional

from sequences import WORKSHOP_SEQUENCE, OPERATION_SEQUENCE, send_sequence


class BrakePage(ttk.Frame):
    def __init__(self, parent, app):  # app: THNApp
        super().__init__(parent, style="Card.TFrame")
        self.app = app

        top = ttk.Frame(self, padding=16, style="Card.TFrame")
        top.pack(fill="x")

        self.head = ttk.Label(top, text="Feststellbremse – Modi", style="Card.TLabel", font=("Segoe UI", 16, "bold"))
        self.head.pack(side="left")

        self.close_btn = ttk.Button(top, text="← Zurück", command=lambda: app.show("MainMenu"))
        # Einheitlicher roter Stil
        try:
            self.close_btn.configure(style="Red.TButton")
        except Exception:
            pass
        self.close_btn.pack(side="right")

        body = ttk.Frame(self, padding=24, style="Card.TFrame")
        body.pack(expand=True)

        self.btn_workshop = ttk.Button(body, text="Werkstattmodus", command=self.run_workshop)
        try:
            self.btn_workshop.configure(style="Red.TButton")
        except Exception:
            pass
        self.btn_workshop.pack(pady=10)

        self.btn_operation = ttk.Button(body, text="Betriebsmodus", command=self.run_operation)
        try:
            self.btn_operation.configure(style="Red.TButton")
        except Exception:
            pass
        self.btn_operation.pack(pady=10)

        self.status = ttk.Label(self, text="", style="Card.TLabel")
        self.status.pack(pady=(0, 16))

    def apply_theme(self, bg, fg, card, paint_button):
        self.configure(style="Card.TFrame")
        for w in self.winfo_children():
            if isinstance(w, ttk.Frame):
                w.configure(style="Card.TFrame")
        self.head.configure(style="Card.TLabel")
        self.status.configure(style="Card.TLabel")

    def _send_and_report(self, seq, delay_s, rx_window_s, success_msg, info_after: Optional[str] = None):
        self.status.configure(text="Sende Sequenz …")
        self.update_idletasks()
        try:
            ok = send_sequence(seq, delay_s=delay_s, rx_window_s=rx_window_s)
        except Exception as e:
            ok = False
            messagebox.showerror("CAN Fehler", f"Senden fehlgeschlagen:\n{e}")
        if ok:
            self.status.configure(text=success_msg)
            if info_after:
                messagebox.showinfo("Hinweis", info_after)
        else:
            self.status.configure(text="Fehler beim Senden – Details im Dialog.")

    def run_workshop(self):
        self._send_and_report(
            seq=WORKSHOP_SEQUENCE,
            delay_s=0.1,
            rx_window_s=0.2,
            success_msg="OK – Werkstatt-Sequenz gesendet (100 ms Delay).",
        )

    def run_operation(self):
        self._send_and_report(
            seq=OPERATION_SEQUENCE,
            delay_s=0.02,
            rx_window_s=0.2,
            success_msg="OK – Betriebs-Sequenz gesendet.",
            info_after="Bitte jetzt an der Handbremse ziehen und das Bremspedal betätigen.",
        )
