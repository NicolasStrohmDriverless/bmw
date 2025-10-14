"""Thin compatibility wrapper for the GUI.

The actual app and pages now live under `ui/`.
This keeps `from gui import THNApp` working.
"""

from ui import THNApp

__all__ = ["THNApp"]

if __name__ == "__main__":
    app = THNApp()
    app.mainloop()

