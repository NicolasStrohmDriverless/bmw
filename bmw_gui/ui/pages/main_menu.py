from __future__ import annotations
import time
import tkinter as tk
from tkinter import ttk, messagebox

import can  # type: ignore

from sequences import HEADLIGHT_SEQUENCE, BRAKE_PEDAL_SEQUENCE
from can_utils import open_bus, print_tx, print_rx

# ---- Corporate Design Farben TH Nürnberg ----
THN_RED   = "#C93030"    # Rot (201,48,48)
THN_WHITE = "#FDFDFD"

def ensure_red_button_style():
    """Sorgt dafür, dass der rote THN-Button-Style vorhanden ist."""
    style = ttk.Style()
    # 'clam' zeigt Button-Hintergründe zuverlässig an
    try:
        style.theme_use("clam")
    except Exception:
        pass

    # Damit der Hintergrund wirklich greift, legen wir Layout/Farben fest
    # und mappen Zustände (active/pressed/disabled).
    style.configure(
        "Red.TButton",
        background=THN_RED,
        foreground="white",
        bordercolor=THN_RED,
        focusthickness=3,
        focuscolor=THN_RED,
        padding=(12, 8),
        font=("Segoe UI", 11, "bold")
    )
    style.map(
        "Red.TButton",
        background=[
            ("pressed", "#A32222"),
            ("active",  "#B82828"),
            ("disabled", "#D8D8D8")
        ],
        foreground=[
            ("disabled", "#666666")
        ],
        bordercolor=[
            ("pressed", "#A32222"),
            ("active",  "#B82828")
        ]
    )
    return style


class MainMenu(ttk.Frame):
    def __init__(self, parent, app):  # app: THNApp
        super().__init__(parent, style="Card.TFrame")
        self.app = app

        # Style nur einmal sicherstellen
        ensure_red_button_style()

        self.inner = ttk.Frame(self, padding=24, style="Card.TFrame")
        self.inner.pack(expand=True, fill="both")

        self.title = ttk.Label(self.inner, text="Hauptmenü", style="Card.TLabel", font=("Segoe UI", 18, "bold"))
        self.title.pack(pady=(0, 16))
        try:
            self.title.configure(text="Hauptmenü")
        except Exception:
            self.title.configure(text="Hauptmenue")

        # Four-column layout container
        self.columns = ttk.Frame(self.inner, style="Card.TFrame")
        self.columns.pack(fill="both", expand=True)

        # Configure equal-width columns
        for i in range(4):
            self.columns.grid_columnconfigure(i, weight=1, uniform="cols")
        self.columns.grid_rowconfigure(0, weight=1)

        # Column frames
        self.col_test = ttk.Frame(self.columns, style="Card.TFrame", padding=(8, 0))
        self.col_gear = ttk.Frame(self.columns, style="Card.TFrame", padding=(8, 0))
        self.col_brake = ttk.Frame(self.columns, style="Card.TFrame", padding=(8, 0))
        self.col_misc = ttk.Frame(self.columns, style="Card.TFrame", padding=(8, 0))
        self.col_test.grid(row=0, column=0, sticky="nsew", padx=4)
        self.col_gear.grid(row=0, column=1, sticky="nsew", padx=4)
        self.col_brake.grid(row=0, column=2, sticky="nsew", padx=4)
        self.col_misc.grid(row=0, column=3, sticky="nsew", padx=4)

        # Column 1: Test
        self.btn_test = ttk.Button(
            self.col_test,
            text="Test",
            command=lambda: app.show("TestPage"),
            style="Red.TButton",
        )
        self.btn_test.pack(pady=8, ipadx=16, ipady=8)

        # Column 2: Gear lever simulation
        self.btn_gear = ttk.Button(
            self.col_gear,
            text="Ganghebel",
            command=lambda: app.show("GearLeverPage"),
            style="Red.TButton",
        )
        self.btn_gear.pack(pady=8, ipadx=16, ipady=8)

        # Column 3: Parking brake
        self.btn_brake = ttk.Button(
            self.col_brake,
            text="Feststellbremse",
            command=lambda: app.show("BrakePage"),
            style="Red.TButton",
        )
        self.btn_brake.pack(pady=8, ipadx=16, ipady=8)

        # Column 4: Brake pedal and Headlight
        self.btn_brake_pedal = ttk.Button(
            self.col_misc,
            text="Bremspedal",
            command=self.run_brake_pedal,
            style="Red.TButton",
        )
        self.btn_brake_pedal.pack(pady=(8, 8), ipadx=16, ipady=8)

        self.btn_headlight = ttk.Button(
            self.col_misc,
            text="Scheinwerfer",
            command=self.run_headlight,
            style="Red.TButton",
        )
        self.btn_headlight.pack(pady=(0, 8), ipadx=16, ipady=8)

        self.btn_trigger_finder = ttk.Button(
            self.col_misc,
            text="Trigger Finder",
            command=lambda: app.show("TriggerFinderPage"),
            style="Red.TButton",
        )
        self.btn_trigger_finder.pack(pady=(0, 8), ipadx=16, ipady=8)

        # Protokoll-Fenster-Handles für die Anzeige rechts
        self.log_win: tk.Toplevel | None = None
        self.log_tree: ttk.Treeview | None = None

    def apply_theme(self, bg, fg, card, paint_button):
        # Deine bestehenden Card-Styles bleiben; Buttons behalten Red.TButton
        self.configure(style="Card.TFrame")
        self.inner.configure(style="Card.TFrame")
        try:
            self.columns.configure(style="Card.TFrame")
            self.col_test.configure(style="Card.TFrame")
            self.col_gear.configure(style="Card.TFrame")
            self.col_brake.configure(style="Card.TFrame")
            self.col_misc.configure(style="Card.TFrame")
        except Exception:
            pass
        self.title.configure(style="Card.TLabel")

    # ---------- Protokoll-Fenster (rechts) ----------

    def _ensure_log_window(self):
        if self.log_win and tk.Toplevel.winfo_exists(self.log_win):
            try:
                self.log_win.deiconify()
                self.log_win.lift()
            except Exception:
                pass
        else:
            self.log_win = tk.Toplevel(self)
            self.log_win.title("Protokoll – Gesendet / Empfangen")
            self.log_win.geometry("820x420")

            bg = "#FFFFFF" if not self.app.is_dark else "#1E1E1E"
            self.log_win.configure(bg=bg)

            head = ttk.Frame(self.log_win, padding=10, style="Card.TFrame")
            head.pack(fill="x")
            ttk.Label(head, text="Protokoll", style="Card.TLabel", font=("Segoe UI", 16, "bold")).pack(side="left")
            self._log_clear_btn = ttk.Button(head, text="Leeren", command=self._log_clear, style="Red.TButton")
            self._log_clear_btn.pack(side="right", padx=(4, 0))
            ttk.Button(head, text="Speichern…", command=self._log_save, style="Red.TButton").pack(side="right")

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

        # Position window right of main window
        try:
            self.update_idletasks()
            root_x = self.winfo_rootx()
            root_y = self.winfo_rooty()
            root_w = self.winfo_width()
            if self.log_win is not None:
                x = root_x + root_w + 10
                y = root_y
                self.log_win.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _log_row(self, sent_text: str, recv_texts: list[str]):
        self._ensure_log_window()
        if not self.log_tree:
            return
        joined = " | ".join(recv_texts) if recv_texts else ""
        self.log_tree.insert("", "end", values=(sent_text, joined))

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

    # ---------- Actions ----------

    def run_headlight(self):
        self._ensure_log_window()
        delay_s = 0.02
        rx_window_s = 0.2

        ok = True
        try:
            bus = open_bus()
        except Exception as e:
            messagebox.showerror("CAN Fehler", f"Bus konnte nicht geöffnet werden:\n{e}")
            return

        try:
            for can_id_hex, data_hex in HEADLIGHT_SEQUENCE:
                arb_id = int(can_id_hex, 16)
                msg = can.Message(arbitration_id=arb_id, is_extended_id=False, data=bytes.fromhex(data_hex))
                bus.send(msg)
                try:
                    print_tx(msg)
                except Exception:
                    pass

                recv_texts: list[str] = []
                t_end = time.time() + rx_window_s
                while time.time() < t_end:
                    m = bus.recv(timeout=0.01)
                    if m is None:
                        continue
                    # Auch im Terminal anzeigen
                    try:
                        print_rx(m)
                    except Exception:
                        pass
                    recv_texts.append(
                        f"ID=0x{m.arbitration_id:03X} DLC={m.dlc} Data={' '.join(f'{b:02X}' for b in m.data)}"
                    )

                sent_text = f"ID=0x{arb_id:03X} Data={data_hex.upper()}"
                self._log_row(sent_text, recv_texts)

                if delay_s > 0:
                    time.sleep(delay_s)

        except Exception as e:
            ok = False
            messagebox.showerror("CAN Fehler", f"Senden/Empfangen fehlgeschlagen:\n{e}")
        finally:
            try:
                bus.shutdown()
            except Exception:
                pass

        if ok:
            self._ensure_log_window()

    def run_brake_pedal(self):
        self._ensure_log_window()

        delay_s = 0.02
        rx_window_s = 0.2

        ok = True
        try:
            bus = open_bus()
        except Exception as e:
            messagebox.showerror("CAN Fehler", f"Bus konnte nicht geöffnet werden:\n{e}")
            return

        try:
            for can_id_hex, data_hex in BRAKE_PEDAL_SEQUENCE:
                arb_id = int(can_id_hex, 16)
                msg = can.Message(arbitration_id=arb_id, is_extended_id=False, data=bytes.fromhex(data_hex))
                bus.send(msg)
                try:
                    print_tx(msg)
                except Exception:
                    pass

                recv_texts: list[str] = []
                t_end = time.time() + rx_window_s
                while time.time() < t_end:
                    m = bus.recv(timeout=0.01)
                    if m is None:
                        continue
                    recv_texts.append(
                        f"ID=0x{m.arbitration_id:03X} DLC={m.dlc} Data={' '.join(f'{b:02X}' for b in m.data)}"
                    )

                sent_text = f"ID=0x{arb_id:03X} Data={data_hex.upper()}"
                self._log_row(sent_text, recv_texts)

                if delay_s > 0:
                    time.sleep(delay_s)

        except Exception as e:
            ok = False
            messagebox.showerror("CAN Fehler", f"Senden/Empfangen fehlgeschlagen:\n{e}")
        finally:
            try:
                bus.shutdown()
            except Exception:
                pass

        if ok:
            self._ensure_log_window()
