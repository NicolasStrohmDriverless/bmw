from __future__ import annotations

import os
import re
from typing import List, Tuple

from .models import RawCanFrame


_TRC_LINE_RE = re.compile(
    r"^\s*\d+\)\s+"
    r"(?P<time>[0-9]+(?:\.[0-9]+)?)\s+"
    r"(?P<type>[A-Za-z]+)\s+"
    r"(?:(?P<channel>[0-9A-Za-z]+)\s+)?"
    r"(?P<can_id>[0-9A-Fa-f]+)\s+"
    r"(?P<dlc>\d+)\s*"
    r"(?P<data>.*)$"
)


def parse_pcan_trc(file_path: str) -> Tuple[List[RawCanFrame], List[str]]:
    """Parse a PCAN .trc file into normalized frame objects.

    The parser is tolerant against comments, header blocks, and malformed lines.
    It returns parsed frames and a list of parse warnings.
    """
    frames: List[RawCanFrame] = []
    warnings: List[str] = []
    source = os.path.basename(file_path)

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line or line.startswith(";"):
                    continue

                match = _TRC_LINE_RE.match(line)
                if not match:
                    # Ignore unknown non-data lines, but keep track for diagnostics.
                    if ")" in line:
                        warnings.append(f"Zeile {line_no}: Unbekanntes Trace-Format")
                    continue

                try:
                    time_ms = float(match.group("time"))
                    can_id = int(match.group("can_id"), 16)
                    dlc = int(match.group("dlc"))
                except ValueError:
                    warnings.append(f"Zeile {line_no}: Ungueltiger Zeit/ID/DLC-Wert")
                    continue

                data_tokens = [tok for tok in match.group("data").split() if tok]
                parsed_bytes = []
                for token in data_tokens[:dlc]:
                    try:
                        parsed_bytes.append(int(token, 16) & 0xFF)
                    except ValueError:
                        parsed_bytes = []
                        warnings.append(f"Zeile {line_no}: Ungueltiges Datenbyte '{token}'")
                        break

                if len(parsed_bytes) < dlc:
                    parsed_bytes.extend([0] * (dlc - len(parsed_bytes)))

                frames.append(
                    RawCanFrame(
                        timestamp=time_ms / 1000.0,
                        can_id=can_id,
                        dlc=dlc,
                        data=bytes(parsed_bytes[:dlc]),
                        source=source,
                        channel=(match.group("channel") or "").strip(),
                    )
                )
    except OSError as exc:
        warnings.append(f"Dateifehler: {exc}")

    return frames, warnings
