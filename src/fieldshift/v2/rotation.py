from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import product
from typing import Iterator

from .models import CropV2, FieldV2, Rotation, ScheduledCropV2


def next_window(window: tuple[str, str], not_before: date) -> tuple[date, date]:
    sm, sd = map(int, window[0].split("-"))
    em, ed = map(int, window[1].split("-"))
    for y in range(not_before.year, not_before.year + 4):
        a = date(y, sm, sd)
        b = date(y, em, ed)
        if b < a:
            b = date(y + 1, em, ed)
        if b >= not_before:
            return a, b
    raise RuntimeError("calendar window resolution failed")


def schedule(rotation: Rotation, crops: dict[str, CropV2], start_year: int = 2026, turnaround_days: int = 7, max_cycle_days: int | None = 430) -> tuple[ScheduledCropV2, ...] | None:
    out = []
    earliest = date(start_year, 1, 1)
    for cid in rotation.crop_ids:
        crop = crops[cid]
        ws, we = next_window(crop.sowing_window, earliest)
        sow = max(ws, earliest)
        if sow > we:
            return None
        harvest = sow + timedelta(days=crop.duration_days)
        out.append(ScheduledCropV2(cid, sow, harvest))
        earliest = harvest + timedelta(days=turnaround_days)
    if max_cycle_days is not None and out and (out[-1].harvest_date - out[0].sow_date).days > max_cycle_days:
        return None
    return tuple(out)


def generate_rotations(crops: dict[str, CropV2], *, max_crops: int = 3, start_year: int = 2026,
                       turnaround_days: int = 7, preferred: set[str] | None = None,
                       avoid_consecutive_family: bool = True) -> Iterator[Rotation]:
    ids = tuple(crops.keys())
    preferred = preferred or set()
    counter = 0
    # DFS instead of materializing the combinatorial search space. This keeps the
    # engine capable of larger crop libraries while allowing callers to stop early.
    def dfs(prefix: tuple[str, ...], earliest: date) -> Iterator[Rotation]:
        nonlocal counter
        if prefix:
            counter += 1
            yield Rotation(f"GEN-{counter:06d}", prefix, " -> ".join(crops[c].display_name for c in prefix), "generated")
        if len(prefix) >= max_crops:
            return
        for cid in ids:
            crop = crops[cid]
            if cid in prefix and len(prefix) == 0:
                continue
            if avoid_consecutive_family and prefix and crops[prefix[-1]].family == crop.family:
                continue
            ws, we = next_window(crop.sowing_window, earliest)
            sow = max(ws, earliest)
            if sow > we:
                continue
            # Preferred crops are not hard constraints: they are explored first.
            next_ids = []
            if cid in preferred:
                next_ids.append(cid)
            next_ids.append(cid)
            for nid in next_ids:
                if nid == cid:
                    harvest = sow + timedelta(days=crop.duration_days)
                    new_prefix = prefix + (cid,)
                    yield from dfs(new_prefix, harvest + timedelta(days=turnaround_days))
                    break
    yield from dfs((), date(start_year, 1, 1))
