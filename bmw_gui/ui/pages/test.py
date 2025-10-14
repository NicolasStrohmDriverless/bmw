from __future__ import annotations
import itertools
import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import List

import can  # type: ignore

from can_utils import open_bus, tokens_from_boxes, print_tx, print_rx


class TestPage(ttk.Frame):
    def __init__(self, parent, app):  # app: THNApp
        super().__init__(parent, style="Card.TFrame")
        self.app = app

        top = ttk.Frame(self, padding=16, style="Card.TFrame")
        top.pack(fill="x")

        self.head = ttk.Label(top, text="Test – Manuelle CAN-Nachricht", style="Card.TLabel", font=("Segoe UI", 16, "bold"))
        self.head.pack(side="left")

        self.close_btn = ttk.Button(top, text="← Zurück", command=lambda: app.show("MainMenu"))
        # Einheitlicher roter Stil
        try:
            self.close_btn.configure(style="Red.TButton")
        except Exception:
            pass
        self.close_btn.pack(side="right")

        body = ttk.Frame(self, padding=24, style="Card.TFrame")
        body.pack(expand=True, fill="both")

        # CAN-ID
        id_row = ttk.Frame(body, style="Card.TFrame")
        id_row.pack(fill="x", pady=6)
        ttk.Label(id_row, text="CAN-ID (hex, z.B. 1777 / 6F1):", style="Card.TLabel").pack(side="left")
        self.entry_id = ttk.Entry(id_row, width=20)
        self.entry_id.pack(side="left", padx=8)

        # 8 Byte-Felder
        bytes_row = ttk.Frame(body, style="Card.TFrame")
        bytes_row.pack(fill="x", pady=10)
        ttk.Label(bytes_row, text="Daten (8 Bytes):", style="Card.TLabel").pack(side="left", padx=(0, 8))

        self.byte_entries: List[ttk.Entry] = []
        for _ in range(8):
            e = ttk.Entry(bytes_row, width=4, justify="center")
            e.pack(side="left", padx=3)
            self.byte_entries.append(e)

        hint = ttk.Label(
            body,
            text="Hinweis: Jedes Feld akzeptiert 0–FF. Leer lassen = alle 256 Werte an dieser Position durchprobieren.",
            style="Card.TLabel",
        )
        hint.pack(anchor="w", pady=(6, 0))

        # Sende-Parameter
        param_row = ttk.Frame(body, style="Card.TFrame")
        param_row.pack(fill="x", pady=10)
        ttk.Label(param_row, text="Delay zwischen Varianten (ms):", style="Card.TLabel").pack(side="left")
        self.entry_delay = ttk.Entry(param_row, width=8)
        self.entry_delay.insert(0, "20")
        self.entry_delay.pack(side="left", padx=8)

        ttk.Label(param_row, text="RX-Fenster je Burst (ms):", style="Card.TLabel").pack(side="left")
        self.entry_rx = ttk.Entry(param_row, width=8)
        self.entry_rx.insert(0, "200")
        self.entry_rx.pack(side="left", padx=8)

        ttk.Label(param_row, text="Max parallel:", style="Card.TLabel").pack(side="left", padx=(16, 0))
        self.entry_parallel = ttk.Entry(param_row, width=6)
        self.entry_parallel.insert(0, "8")
        self.entry_parallel.pack(side="left", padx=8)

        # Senden-/Abbrechen-Buttons
        btn_row = ttk.Frame(body, style="Card.TFrame")
        btn_row.pack(pady=16)
        self.send_btn = ttk.Button(btn_row, text="Senden", command=self.on_send)
        try:
            self.send_btn.configure(style="Red.TButton")
        except Exception:
            pass
        self.send_btn.pack(side="left", padx=6, ipadx=18, ipady=10)

        self.cancel_btn = ttk.Button(btn_row, text="Abbrechen", command=self.on_cancel)
        try:
            self.cancel_btn.configure(style="Red.TButton")
        except Exception:
            pass
        self.cancel_btn.pack(side="left", padx=6, ipadx=18, ipady=10)
        self.cancel_btn.configure(state="disabled")

        # Protokoll-Fenster
        self.log_win = None
        self.log_tree = None

        # Status
        self.status = ttk.Label(self, text="", style="Card.TLabel")
        self.status.pack(pady=(0, 16))

        # Abbruch-Flag
        self._abort = False

        # Tastatur-Validierung
        self._wire_keybindings()

    # ---------- Keybindings & Validierung ----------

    def _wire_keybindings(self):
        for idx, entry in enumerate(self.byte_entries):
            entry.configure(validate="key")
            entry["validatecommand"] = (entry.register(self._validate_hex), "%P")
            entry.bind("<KeyRelease>", lambda e, i=idx: self._advance_on_two_chars(e, i))
            entry.bind("<BackSpace>", lambda e, i=idx: self._jump_back_on_delete(e, i))

    @staticmethod
    def _validate_hex(proposed: str) -> bool:
        proposed = proposed.strip().upper().replace("0X", "")
        if proposed in ("", "?", "??"):
            return True
        if len(proposed) > 2:
            return False
        try:
            int(proposed or "0", 16)
            return True
        except ValueError:
            return False

    def _advance_on_two_chars(self, event, idx: int):
        text = self.byte_entries[idx].get().strip().upper()
        if len(text) == 2 and idx < 7:
            self.byte_entries[idx + 1].focus_set()
            self.byte_entries[idx + 1].icursor(tk.END)

    def _jump_back_on_delete(self, event, idx: int):
        if idx > 0 and self.byte_entries[idx].get() == "":
            self.byte_entries[idx - 1].focus_set()
            self.byte_entries[idx - 1].icursor(tk.END)

    # ---------- UI Lock / Cancel ----------

    def _set_edit_mode(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.entry_id.configure(state=state)
        self.entry_delay.configure(state=state)
        self.entry_rx.configure(state=state)
        self.entry_parallel.configure(state=state)
        for e in self.byte_entries:
            e.configure(state=state)
        self.send_btn.configure(state=("disabled" if not enabled else "normal"))
        self.cancel_btn.configure(state=("normal" if not enabled else "disabled"))

    def on_cancel(self):
        self._abort = True
        self.status.configure(text="Abbruch angefordert …")

    # ---------- Theme ----------

    def apply_theme(self, bg, fg, card, paint_button):
        self.configure(style="Card.TFrame")
        for w in self.winfo_children():
            if isinstance(w, ttk.Frame):
                w.configure(style="Card.TFrame")
        self.head.configure(style="Card.TLabel")
        self.status.configure(style="Card.TLabel")
        # Buttons behalten ihren expliziten Stil (Red.TButton)
        try:
            self.close_btn.configure(style="Red.TButton")
            self.send_btn.configure(style="Red.TButton")
            self.cancel_btn.configure(style="Red.TButton")
        except Exception:
            pass

    # ---------- Protokoll-Fenster ----------

    def _ensure_log_window(self):
        if self.log_win and tk.Toplevel.winfo_exists(self.log_win):
            try:
                self.log_win.deiconify()
                self.log_win.lift()
            except Exception:
                pass
            return

        self.log_win = tk.Toplevel(self)
        self.log_win.title("Protokoll – Gesendet / Empfangen")
        self.log_win.geometry("820x420")

        bg = "#FFFFFF" if not self.app.is_dark else "#1E1E1E"
        self.log_win.configure(bg=bg)

        head = ttk.Frame(self.log_win, padding=10, style="Card.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Protokoll", style="Card.TLabel", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Button(head, text="Leeren", command=self._log_clear).pack(side="right", padx=(4, 0))
        ttk.Button(head, text="Speichern…", command=self._log_save).pack(side="right")

        body = ttk.Frame(self.log_win, padding=10, style="Card.TFrame")
        body.pack(fill="both", expand=True)

        cols = ("sent", "received")
        tree = ttk.Treeview(body, columns=cols, show="headings", height=16)
        tree.heading("sent", text="Gesendete Nachricht")
        tree.heading("received", text="Empfangene Nachricht(en)")
        tree.column("sent", width=320, anchor="w", stretch=True)
        tree.column("received", width=460, anchor="w", stretch=True)
        tree.pack(fill="both", expand=True)

        vsb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        vsb.place(relx=1, rely=0, relheight=1, anchor="ne")
        tree.configure(yscrollcommand=vsb.set)

        self.log_tree = tree
        # Kopfzeilen-Buttons ebenfalls im roten Stil
        try:
            for child in head.winfo_children():
                if isinstance(child, ttk.Button):
                    child.configure(style="Red.TButton")
        except Exception:
            pass

    def _log_clear(self):
        if self.log_tree:
            for iid in self.log_tree.get_children(""):
                self.log_tree.delete(iid)

    def _log_save(self):
        try:
            from tkinter import filedialog
            if not self.log_tree:
                return
            path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[["CSV", "*.csv"], ["Text", "*.txt"]],
            )
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                f.write("Gesendet;Empfangen\n")
                for iid in self.log_tree.get_children(""):
                    vals = self.log_tree.item(iid, "values")
                    sent = vals[0] if len(vals) > 0 else ""
                    recv = vals[1] if len(vals) > 1 else ""
                    sent_q = '"' + str(sent).replace('"', '""') + '"'
                    recv_q = '"' + str(recv).replace('"', '""') + '"'
                    f.write(f"{sent_q};{recv_q}\n")
        except Exception as e:
            messagebox.showerror("Export", f"Speichern fehlgeschlagen:\n{e}")

    def _log_row(self, sent_text: str, recv_texts: list[str]):
        self._ensure_log_window()
        if not self.log_tree:
            return
        joined = " | ".join(recv_texts) if recv_texts else ""
        self.log_tree.insert("", "end", values=(sent_text, joined))

    # ---------- Senden ----------

    def on_send(self):
        can_id = self.entry_id.get().strip().upper().replace("0X", "")
        if not can_id:
            messagebox.showerror("Eingabe", "Bitte eine CAN-ID angeben (hex).")
            return

        try:
            delay_ms = int(self.entry_delay.get())
            rx_ms = int(self.entry_rx.get())
            max_parallel = max(1, int(self.entry_parallel.get()))
        except ValueError:
            messagebox.showerror("Eingabe", "Delay/RX/Parallel müssen ganze Zahlen sein.")
            return

        try:
            user_vals = [e.get() for e in self.byte_entries]
            tokens, total = tokens_from_boxes(user_vals)
        except ValueError as e:
            messagebox.showerror("Eingabe", f"Byte-Eingabe fehlerhaft: {e}")
            return

        if total > 65536:
            if not messagebox.askyesno("Viele Varianten", f"Es würden {total} Varianten gesendet.\nFortfahren?"):
                return

        choices = [[f"{i:02X}" for i in range(256)] if t is None else [t] for t in tokens]
        choices_reversed = list(reversed(choices))
        wildcard_idx = [i for i, t in enumerate(tokens) if t is None]

        self._abort = False
        self._set_edit_mode(False)
        self.status.configure(text="Sende …")
        self.update_idletasks()

        try:
            bus = open_bus()
        except Exception as e:
            self._set_edit_mode(True)
            messagebox.showerror("CAN Fehler", f"Bus konnte nicht geöffnet werden:\n{e}")
            return

        ok = True
        delay_s = max(0.0, delay_ms / 1000.0)
        rx_window_s = max(0.0, rx_ms / 1000.0)

        def combo_iter():
            for rev_combo in itertools.product(*choices_reversed):
                yield list(reversed(rev_combo))

        try:
            arb_id = int(can_id, 16)

            burst: list[list[str]] = []
            for combo in combo_iter():
                self.update()
                if self._abort:
                    ok = False
                    break

                burst.append(combo)
                if len(burst) < max_parallel:
                    continue

                for idx in wildcard_idx:
                    self.byte_entries[idx].configure(state="normal")
                    self.byte_entries[idx].delete(0, tk.END)
                    self.byte_entries[idx].insert(0, burst[-1][idx])
                    self.byte_entries[idx].configure(state="disabled")
                self.update_idletasks()

                sent_texts = []
                for c in burst:
                    data_hex = "".join(c)
                    msg = can.Message(arbitration_id=arb_id, is_extended_id=False, data=bytes.fromhex(data_hex))
                    bus.send(msg)
                    sent_texts.append(f"ID=0x{arb_id:03X} Data={data_hex}")
                    try:
                        print_tx(msg)
                    except Exception:
                        pass

                recv_texts = []
                t_end = time.time() + rx_window_s
                while time.time() < t_end:
                    self.update()
                    if self._abort:
                        ok = False
                        break
                    m = bus.recv(timeout=0.01)
                    if m is None:
                        continue
                    # RX auch im Terminal ausgeben
                    try:
                        print_rx(m)
                    except Exception:
                        pass
                    recv_texts.append(
                        f"ID=0x{m.arbitration_id:03X} DLC={m.dlc} Data={' '.join(f'{b:02X}' for b in m.data)}"
                    )

                for s in sent_texts:
                    self._log_row(s, recv_texts)

                if delay_s > 0:
                    time.sleep(delay_s)

                burst = []

            if ok and burst:
                for idx in wildcard_idx:
                    self.byte_entries[idx].configure(state="normal")
                    self.byte_entries[idx].delete(0, tk.END)
                    self.byte_entries[idx].insert(0, burst[-1][idx])
                    self.byte_entries[idx].configure(state="disabled")
                self.update_idletasks()

                sent_texts = []
                for c in burst:
                    data_hex = "".join(c)
                    msg = can.Message(arbitration_id=arb_id, is_extended_id=False, data=bytes.fromhex(data_hex))
                    bus.send(msg)
                    sent_texts.append(f"ID=0x{arb_id:03X} Data={data_hex}")
                    try:
                        print_tx(msg)
                    except Exception:
                        pass

                recv_texts = []
                t_end = time.time() + rx_window_s
                while time.time() < t_end:
                    self.update()
                    if self._abort:
                        ok = False
                        break
                    m = bus.recv(timeout=0.01)
                    if m is None:
                        continue
                    # RX auch im Terminal ausgeben
                    try:
                        print_rx(m)
                    except Exception:
                        pass
                    recv_texts.append(
                        f"ID=0x{m.arbitration_id:03X} DLC={m.dlc} Data={' '.join(f'{b:02X}' for b in m.data)}"
                    )

                for s in sent_texts:
                    self._log_row(s, recv_texts)

        except Exception as e:
            ok = False
            messagebox.showerror("CAN Fehler", f"Senden fehlgeschlagen:\n{e}")
        finally:
            try:
                bus.shutdown()
            except Exception:
                pass

        if self._abort:
            self.status.configure(text="Abgebrochen – Bearbeiten wieder möglich.")
        elif ok:
            self.status.configure(text="OK – Senden abgeschlossen.")
        else:
            self.status.configure(text="Abgebrochen/Fehler – Details im Dialog.")

        self._set_edit_mode(True)
        self._ensure_log_window()
