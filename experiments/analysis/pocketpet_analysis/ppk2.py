"""Streaming reader for CSV files exported by the nRF Connect Power Profiler (PPK2).

The export writes a header chosen from ``Timestamp(ms)``, ``Current(uA)``, ``D0-D7`` and
``D0,D1,...,D7``. Each logic channel is one character: ``0`` low, ``1`` high, ``X`` both levels
seen inside one averaged sample, ``-`` no valid reading. Samples whose current is NaN are left
out of the file, so timestamps can skip.
"""

from __future__ import annotations

import itertools
import warnings
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TIMESTAMP_COLUMN = "Timestamp(ms)"
CURRENT_COLUMN = "Current(uA)"
PACKED_COLUMN = "D0-D7"
CHANNEL_COLUMNS = [f"D{i}" for i in range(8)]
CHANNEL_COUNT = 8
DEFAULT_CHUNK_ROWS = 1_000_000

_BIT_WEIGHTS = (1 << np.arange(CHANNEL_COUNT)).astype(np.uint8)


@dataclass(frozen=True)
class Chunk:
    """A run of consecutive samples. Bit ``n`` of each mask describes logic channel ``Dn``."""

    time_ms: np.ndarray
    current_ua: np.ndarray
    # ``high`` includes mixed samples so a marker pulse shorter than one averaged sample
    # is still seen. All three masks are None when the export has no logic columns.
    high: np.ndarray | None
    mixed: np.ndarray | None
    undriven: np.ndarray | None


def read_capture(path: Path, chunk_rows: int = DEFAULT_CHUNK_ROWS) -> Iterator[Chunk]:
    """Yield the capture in chunks so a multi-hour export never has to fit in memory."""
    # Universal newlines, so an export re-saved with CRLF endings parses the same way.
    with path.open(encoding="utf-8-sig") as lines:
        header = lines.readline().strip().split(",")
        usecols, dtype = _column_layout(header, path)
        while True:
            batch = list(itertools.islice(lines, chunk_rows))
            if not batch:
                return
            with warnings.catch_warnings():
                # A batch of only blank trailing lines parses to zero rows with a warning.
                warnings.simplefilter("ignore", UserWarning)
                rows = np.loadtxt(batch, delimiter=",", dtype=dtype, usecols=usecols, ndmin=1)
            if rows.size:
                yield _to_chunk(rows)


def _column_layout(header: list[str], path: Path) -> tuple[list[int], list[tuple[str, str]]]:
    for required in (TIMESTAMP_COLUMN, CURRENT_COLUMN):
        if required not in header:
            raise ValueError(
                f"{path.name}: column {required!r} is missing; re-export the capture with "
                "timestamp and current selected"
            )
    usecols = [header.index(TIMESTAMP_COLUMN), header.index(CURRENT_COLUMN)]
    dtype = [("time_ms", "f8"), ("current_ua", "f8")]
    if PACKED_COLUMN in header:
        usecols.append(header.index(PACKED_COLUMN))
        dtype.append(("packed", f"S{CHANNEL_COUNT}"))
    elif all(name in header for name in CHANNEL_COLUMNS):
        usecols += [header.index(name) for name in CHANNEL_COLUMNS]
        dtype += [(name, "S1") for name in CHANNEL_COLUMNS]
    return usecols, dtype


def _to_chunk(rows: np.ndarray) -> Chunk:
    names = rows.dtype.names
    if "packed" in names:
        # A short field is NUL-padded and fails the character check below.
        levels = np.frombuffer(rows["packed"].tobytes(), dtype="S1").reshape(-1, CHANNEL_COUNT)
    elif CHANNEL_COLUMNS[0] in names:
        levels = np.stack([rows[name] for name in CHANNEL_COLUMNS], axis=1)
    else:
        return Chunk(rows["time_ms"], rows["current_ua"], None, None, None)

    low, high = levels == b"0", levels == b"1"
    mixed, undriven = levels == b"X", levels == b"-"
    if not (low | high | mixed | undriven).all():
        raise ValueError("logic channel columns contain characters other than 0, 1, X and -")
    return Chunk(
        rows["time_ms"],
        rows["current_ua"],
        _pack(high | mixed),
        _pack(mixed),
        _pack(undriven),
    )


def _pack(channel_flags: np.ndarray) -> np.ndarray:
    return (channel_flags * _BIT_WEIGHTS).sum(axis=1, dtype=np.uint8)
