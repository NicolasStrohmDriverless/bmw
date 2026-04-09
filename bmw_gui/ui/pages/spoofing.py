from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

import can  # type: ignore

from can_utils import open_bus, print_rx, print_tx


class SpoofingPage(ttk.Frame):
    def __init__(self, parent, app):  # app: THNApp
        super().__init__(parent, style="Card.TFrame")
        self.app = app

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
            text="Manuelles CAN-Frame senden und die Antworten direkt mitprotokollieren.",
            style="Card.TLabel",
        )
        intro.pack(anchor="w", pady=(0, 12))

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

        param_row = ttk.Frame(body, style="Card.TFrame")
        param_row.pack(fill="x", pady=6)
        ttk.Label(param_row, text="RX-Fenster (ms):", style="Card.TLabel").pack(side="left")
        self.entry_rx = ttk.Entry(param_row, width=8)
        self.entry_rx.insert(0, "250")
        self.entry_rx.pack(side="left", padx=8)

        ttk.Label(param_row, text="Status-Text:", style="Card.TLabel").pack(side="left", padx=(16, 0))
        self.entry_status = ttk.Entry(param_row, width=28)
        self.entry_status.insert(0, "Sende Frame und beobachte Antworten")
        self.entry_status.pack(side="left", padx=8)

        btn_row = ttk.Frame(body, style="Card.TFrame")
        btn_row.pack(fill="x", pady=(14, 10))

        self.send_btn = ttk.Button(btn_row, text="Senden", command=self._send_frame)
        self.clear_btn = ttk.Button(btn_row, text="Log leeren", command=self._clear_log)
        try:
            self.send_btn.configure(style="Red.TButton")
            self.clear_btn.configure(style="Red.TButton")
        except Exception:
            pass
        self.send_btn.pack(side="left", padx=(0, 8), ipadx=16, ipady=8)
        self.clear_btn.pack(side="left", ipadx=16, ipady=8)

        self.status = ttk.Label(body, text="Bereit.", style="Card.TLabel")
        self.status.pack(fill="x", pady=(0, 8))

        log_container = ttk.Frame(body, style="Card.TFrame")
        log_container.pack(fill="both", expand=True)

        self.log_text = tk.Text(log_container, height=16, wrap="word", state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(log_container, orient="vertical", command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)

    def apply_theme(self, bg, fg, card, paint_button):
        self.configure(style="Card.TFrame")
        for child in self.winfo_children():
            if isinstance(child, ttk.Frame):
                child.configure(style="Card.TFrame")
        self.head.configure(style="Card.TLabel")
        self.status.configure(style="Card.TLabel")
        try:
            paint_button(self.send_btn)
            paint_button(self.clear_btn)
            paint_button(self.back_btn)
        except Exception:
            try:
                self.send_btn.configure(style="Red.TButton")
                self.clear_btn.configure(style="Red.TButton")
                self.back_btn.configure(style="Red.TButton")
            except Exception:
                pass

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _send_frame(self) -> None:
        can_id_text = self.entry_id.get().strip().upper().replace("0X", "")
        data_text = self.entry_data.get().strip().upper().replace(" ", "").replace("0X", "")

        if not can_id_text:
            messagebox.showerror("Spoofing", "Bitte eine CAN-ID angeben.")
            return
        if not data_text:
            messagebox.showerror("Spoofing", "Bitte Daten angeben.")
            return
        if len(data_text) % 2 != 0:
            messagebox.showerror("Spoofing", "Die Daten müssen eine gerade Anzahl Hex-Zeichen haben.")
            return

        try:
            rx_window_s = max(0.0, int(self.entry_rx.get()) / 1000.0)
        except ValueError:
            messagebox.showerror("Spoofing", "Das RX-Fenster muss eine ganze Zahl in Millisekunden sein.")
            return

        try:
            arb_id = int(can_id_text, 16)
            data = bytes.fromhex(data_text)
        except ValueError as exc:
            messagebox.showerror("Spoofing", f"Ungültige Hex-Eingabe:\n{exc}")
            return

        if len(data) > 8:
            messagebox.showerror("Spoofing", "CAN Classic unterstützt maximal 8 Datenbytes.")
            return

        try:
            bus = open_bus()
        except Exception as exc:
            messagebox.showerror("CAN Fehler", f"Bus konnte nicht geöffnet werden:\n{exc}")
            return

        self.status.configure(text=self.entry_status.get().strip() or "Sende …")
        self.update_idletasks()

        try:
            msg = can.Message(arbitration_id=arb_id, is_extended_id=False, data=data)
            bus.send(msg)
            try:
                print_tx(msg)
            except Exception:
                pass

            self._append_log(f"TX  ID=0x{arb_id:03X} DLC={len(data)} Data={data_text}")

            t_end = time.time() + rx_window_s
            rx_seen = 0
            while time.time() < t_end:
                rx_msg = bus.recv(timeout=0.01)
                if rx_msg is None:
                    continue
                rx_seen += 1
                try:
                    print_rx(rx_msg)
                except Exception:
                    pass
                data_repr = " ".join(f"{byte:02X}" for byte in rx_msg.data)
                self._append_log(f"RX  ID=0x{rx_msg.arbitration_id:03X} DLC={rx_msg.dlc} Data={data_repr}")

            if rx_seen:
                self.status.configure(text=f"Senden abgeschlossen, {rx_seen} RX-Frame(s) gesehen.")
            else:
                self.status.configure(text="Senden abgeschlossen, keine Antwort im RX-Fenster gesehen.")
        except Exception as exc:
            self.status.configure(text="Fehler beim Senden.")
            messagebox.showerror("CAN Fehler", f"Senden fehlgeschlagen:\n{exc}")
        finally:
            try:
                bus.shutdown()
            except Exception:
                pass