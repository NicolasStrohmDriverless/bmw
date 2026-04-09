from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from statistics import mean
from typing import Deque, Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class RawCanFrame:
    """Normalized CAN frame representation for live and offline sources."""

    timestamp: float
    can_id: int
    dlc: int
    data: bytes
    source: str
    channel: str = ""

    @property
    def data_hex(self) -> str:
        return " ".join(f"{b:02X}" for b in self.data)


@dataclass
class FrameFilter:
    id_exact: Optional[int] = None
    id_min: Optional[int] = None
    id_max: Optional[int] = None
    payload_contains: str = ""
    min_count: int = 1
    hide_unchanged_periodic: bool = False
    bookmarks_only: bool = False


@dataclass
class GroupStats:
    can_id: int
    total_count: int
    distinct_payloads: int
    first_seen: float
    last_seen: float
    avg_period_ms: float


@dataclass
class PayloadDiff:
    can_id: int
    changing_bytes: List[int]
    min_max_per_byte: Dict[int, Tuple[int, int]]
    bit_flip_counts: Dict[int, int]


@dataclass
class CandidateChange:
    can_id: int
    freq_window_a_hz: float
    freq_window_b_hz: float
    changed_bytes: List[int]


@dataclass
class TraceComparison:
    only_in_a: List[str]
    only_in_b: List[str]
    payload_distribution_changes: List[str]
    frequency_changes: List[str]


class FrameStore:
    """Rolling in-memory frame store with read-only analysis helpers."""

    def __init__(self, max_frames: int = 5000) -> None:
        self.max_frames = max_frames
        self.frames: Deque[RawCanFrame] = deque(maxlen=max_frames)
        self._key_counts: Counter[Tuple[int, str]] = Counter()
        self._last_ts_by_id: Dict[int, float] = {}
        self._last_payload_by_id: Dict[int, bytes] = {}
        self.bookmarks: Dict[int, str] = {}

    def clear(self) -> None:
        self.frames.clear()
        self._key_counts.clear()
        self._last_ts_by_id.clear()
        self._last_payload_by_id.clear()

    def set_max_frames(self, max_frames: int) -> None:
        self.max_frames = max(100, int(max_frames))
        self.frames = deque(self.frames, maxlen=self.max_frames)

    def add_frame(self, frame: RawCanFrame) -> None:
        if len(self.frames) == self.frames.maxlen and self.frames:
            dropped = self.frames[0]
            drop_key = (dropped.can_id, dropped.data_hex)
            self._key_counts[drop_key] -= 1
            if self._key_counts[drop_key] <= 0:
                self._key_counts.pop(drop_key, None)

        self.frames.append(frame)
        self._key_counts[(frame.can_id, frame.data_hex)] += 1

    def build_view(self, frame_filter: FrameFilter) -> List[dict]:
        pattern = frame_filter.payload_contains.replace(" ", "").upper()
        rows: List[dict] = []
        prev_by_id: Dict[int, bytes] = {}

        for frame in self.frames:
            data_hex_no_space = frame.data.hex().upper()
            key = (frame.can_id, frame.data_hex)
            count = self._key_counts.get(key, 0)

            if frame_filter.id_exact is not None and frame.can_id != frame_filter.id_exact:
                continue
            if frame_filter.id_min is not None and frame.can_id < frame_filter.id_min:
                continue
            if frame_filter.id_max is not None and frame.can_id > frame_filter.id_max:
                continue
            if pattern and pattern not in data_hex_no_space:
                continue
            if count < frame_filter.min_count:
                continue
            if frame_filter.bookmarks_only and frame.can_id not in self.bookmarks:
                continue

            unchanged = prev_by_id.get(frame.can_id) == frame.data
            prev_by_id[frame.can_id] = frame.data
            if frame_filter.hide_unchanged_periodic and unchanged:
                continue

            delta_ms = None
            last_ts = self._last_ts_by_id.get(frame.can_id)
            if last_ts is not None:
                delta_ms = (frame.timestamp - last_ts) * 1000.0
            self._last_ts_by_id[frame.can_id] = frame.timestamp

            rate_hz = None
            if delta_ms and delta_ms > 0:
                rate_hz = 1000.0 / delta_ms

            rows.append(
                {
                    "timestamp": frame.timestamp,
                    "id": frame.can_id,
                    "dlc": frame.dlc,
                    "data_hex": frame.data_hex,
                    "count": count,
                    "delta_ms": delta_ms,
                    "rate_hz": rate_hz,
                    "source": frame.source,
                    "channel": frame.channel,
                    "tag": self.bookmarks.get(frame.can_id, ""),
                }
            )

        return rows

    def group_by_id(self) -> List[GroupStats]:
        by_id: Dict[int, List[RawCanFrame]] = defaultdict(list)
        for frame in self.frames:
            by_id[frame.can_id].append(frame)

        results: List[GroupStats] = []
        for can_id, items in by_id.items():
            payloads = {f.data_hex for f in items}
            timestamps = [f.timestamp for f in items]
            periods = [
                (timestamps[i] - timestamps[i - 1]) * 1000.0
                for i in range(1, len(timestamps))
                if timestamps[i] > timestamps[i - 1]
            ]
            results.append(
                GroupStats(
                    can_id=can_id,
                    total_count=len(items),
                    distinct_payloads=len(payloads),
                    first_seen=min(timestamps),
                    last_seen=max(timestamps),
                    avg_period_ms=mean(periods) if periods else 0.0,
                )
            )

        return sorted(results, key=lambda item: item.total_count, reverse=True)

    def payload_diff_for_id(self, can_id: int) -> PayloadDiff:
        frames = [f for f in self.frames if f.can_id == can_id]
        if not frames:
            return PayloadDiff(can_id=can_id, changing_bytes=[], min_max_per_byte={}, bit_flip_counts={})

        max_len = max(f.dlc for f in frames)
        values_by_byte: Dict[int, List[int]] = defaultdict(list)
        bit_flip_counts: Dict[int, int] = defaultdict(int)

        prev: Optional[bytes] = None
        for frame in frames:
            data = frame.data.ljust(max_len, b"\x00")
            for idx, value in enumerate(data):
                values_by_byte[idx].append(value)

            if prev is not None:
                xor = bytes(a ^ b for a, b in zip(prev, data))
                for idx, changed in enumerate(xor):
                    bit_flip_counts[idx] += int(bin(changed).count("1"))
            prev = data

        changing = [idx for idx, vals in values_by_byte.items() if min(vals) != max(vals)]
        min_max = {idx: (min(vals), max(vals)) for idx, vals in values_by_byte.items()}

        return PayloadDiff(
            can_id=can_id,
            changing_bytes=sorted(changing),
            min_max_per_byte=min_max,
            bit_flip_counts=dict(bit_flip_counts),
        )

    def detect_window_changes(
        self,
        window_a: Tuple[float, float],
        window_b: Tuple[float, float],
        min_freq_delta_hz: float = 0.5,
    ) -> List[CandidateChange]:
        a_start, a_end = window_a
        b_start, b_end = window_b

        def in_window(frame: RawCanFrame, start: float, end: float) -> bool:
            return start <= frame.timestamp <= end

        ids = {f.can_id for f in self.frames}
        candidates: List[CandidateChange] = []

        for can_id in ids:
            a_frames = [f for f in self.frames if f.can_id == can_id and in_window(f, a_start, a_end)]
            b_frames = [f for f in self.frames if f.can_id == can_id and in_window(f, b_start, b_end)]
            if not a_frames and not b_frames:
                continue

            dur_a = max(a_end - a_start, 1e-6)
            dur_b = max(b_end - b_start, 1e-6)
            freq_a = len(a_frames) / dur_a
            freq_b = len(b_frames) / dur_b

            changed_positions = _payload_change_positions(a_frames, b_frames)
            if abs(freq_b - freq_a) >= min_freq_delta_hz or changed_positions:
                candidates.append(
                    CandidateChange(
                        can_id=can_id,
                        freq_window_a_hz=freq_a,
                        freq_window_b_hz=freq_b,
                        changed_bytes=changed_positions,
                    )
                )

        return sorted(candidates, key=lambda item: abs(item.freq_window_b_hz - item.freq_window_a_hz), reverse=True)

    def bookmark_id(self, can_id: int, tag: str) -> None:
        tag_clean = (tag or "").strip()
        if tag_clean:
            self.bookmarks[can_id] = tag_clean
        else:
            self.bookmarks.pop(can_id, None)


def compare_traces(frames_a: Iterable[RawCanFrame], frames_b: Iterable[RawCanFrame]) -> TraceComparison:
    """Compare two traces by signature, payload distributions, and frequency."""

    list_a = list(frames_a)
    list_b = list(frames_b)

    sig_a = Counter((f.can_id, f.data_hex) for f in list_a)
    sig_b = Counter((f.can_id, f.data_hex) for f in list_b)

    only_in_a = [f"0x{can_id:03X} {data}" for (can_id, data) in sorted(set(sig_a) - set(sig_b))]
    only_in_b = [f"0x{can_id:03X} {data}" for (can_id, data) in sorted(set(sig_b) - set(sig_a))]

    by_id_a: Dict[int, Counter[str]] = defaultdict(Counter)
    by_id_b: Dict[int, Counter[str]] = defaultdict(Counter)
    for frame in list_a:
        by_id_a[frame.can_id][frame.data_hex] += 1
    for frame in list_b:
        by_id_b[frame.can_id][frame.data_hex] += 1

    payload_distribution_changes: List[str] = []
    for can_id in sorted(set(by_id_a) & set(by_id_b)):
        if by_id_a[can_id] != by_id_b[can_id]:
            payload_distribution_changes.append(
                f"0x{can_id:03X}: Payload-Verteilung unterschiedlich ({len(by_id_a[can_id])} vs {len(by_id_b[can_id])} Varianten)"
            )

    frequency_changes: List[str] = []
    for can_id in sorted(set(by_id_a) | set(by_id_b)):
        rate_a = _estimate_rate_hz([f for f in list_a if f.can_id == can_id])
        rate_b = _estimate_rate_hz([f for f in list_b if f.can_id == can_id])
        if abs(rate_a - rate_b) >= 0.5:
            frequency_changes.append(f"0x{can_id:03X}: {rate_a:.2f} Hz -> {rate_b:.2f} Hz")

    return TraceComparison(
        only_in_a=only_in_a,
        only_in_b=only_in_b,
        payload_distribution_changes=payload_distribution_changes,
        frequency_changes=frequency_changes,
    )


def _estimate_rate_hz(frames: List[RawCanFrame]) -> float:
    if len(frames) < 2:
        return 0.0
    frames_sorted = sorted(frames, key=lambda f: f.timestamp)
    duration = max(frames_sorted[-1].timestamp - frames_sorted[0].timestamp, 1e-6)
    return len(frames_sorted) / duration


def _payload_change_positions(a_frames: List[RawCanFrame], b_frames: List[RawCanFrame]) -> List[int]:
    if not a_frames and not b_frames:
        return []

    a_payloads = [f.data for f in a_frames]
    b_payloads = [f.data for f in b_frames]
    max_len = 0
    for payload in a_payloads + b_payloads:
        max_len = max(max_len, len(payload))

    changed: List[int] = []
    for idx in range(max_len):
        a_vals = {payload[idx] if idx < len(payload) else 0 for payload in a_payloads} or {0}
        b_vals = {payload[idx] if idx < len(payload) else 0 for payload in b_payloads} or {0}
        if a_vals != b_vals:
            changed.append(idx)

    return changed
