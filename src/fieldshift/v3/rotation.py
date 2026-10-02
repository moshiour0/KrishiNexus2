from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

from .models import CropV2, Rotation, ScheduledCropV2


def next_window(window: tuple[str, str], not_before: date) -> tuple[date, date]:
    sm, sd = map(int, window[0].split("-"))
    em, ed = map(int, window[1].split("-"))
    for y in range(not_before.year, not_before.year + 6):
        a = date(y, sm, sd)
        b = date(y, em, ed)
        if b < a:
            b = date(y + 1, em, ed)
        if b >= not_before:
            return a, b
    raise RuntimeError("calendar window resolution failed")


def schedule(
    rotation: Rotation,
    crops: dict[str, CropV2],
    start_year: int = 2026,
    turnaround_days: int = 7,
    max_cycle_days: int | None = 430,
) -> tuple[ScheduledCropV2, ...] | None:
    out: list[ScheduledCropV2] = []
    earliest = date(start_year, 1, 1)
    for cid in rotation.crop_ids:
        if cid not in crops:
            return None
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


def generate_rotations(
    crops: dict[str, CropV2], *, max_crops: int = 4, start_year: int = 2026,
    turnaround_days: int = 7, preferred: set[str] | None = None,
    avoided: set[str] | None = None, avoid_consecutive_family: bool = True,
) -> Iterator[Rotation]:
    ids = tuple(crops.keys())
    preferred = preferred or set()
    avoided = avoided or set()
    counter = 0

    def ordered_ids() -> tuple[str, ...]:
        # Preferred crops are explored first; they are not duplicated and are not hard constraints.
        return tuple(sorted(ids, key=lambda cid: (cid not in preferred, cid)))

    def dfs(prefix: tuple[str, ...], earliest: date) -> Iterator[Rotation]:
        nonlocal counter
        if prefix:
            counter += 1
            yield Rotation(f"GEN-{counter:06d}", prefix, " -> ".join(crops[c].display_name for c in prefix), "generated")
        if len(prefix) >= max_crops:
            return
        last_family = crops[prefix[-1]].family if prefix else None
        for cid in ordered_ids():
            if cid in avoided:
                continue
            crop = crops[cid]
            if avoid_consecutive_family and last_family == crop.family:
                continue
            ws, we = next_window(crop.sowing_window, earliest)
            sow = max(ws, earliest)
            if sow > we:
                continue
            harvest = sow + timedelta(days=crop.duration_days)
            yield from dfs(prefix + (cid,), harvest + timedelta(days=turnaround_days))

    yield from dfs((), date(start_year, 1, 1))
