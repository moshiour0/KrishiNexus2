# -*- coding: utf-8 -*-
"""
fieldshift.engine.constraints
==============================
The hard feasibility filter (blueprint Section 6.3). Every rejected
candidate is logged with the specific rule that removed it, so the
reasoning layer can later say *why* an option isn't offered -- never a
silent drop.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from fieldshift.engine.models import CropProfile, FieldContext, RotationCandidate


@dataclass
class ScheduledCrop:
    crop_id: str
    sow_date: date
    harvest_date: date


@dataclass
class FeasibilityResult:
    rotation_id: str
    feasible: bool
    schedule: list       # list[ScheduledCrop] (partial if infeasible, up to the failure point)
    reason: str | None    # populated iff feasible is False


def _window_end(window: tuple[str, str], year: int) -> date:
    """Kept for callers (e.g. indicators.py) that want a single year's window-end
    for display purposes. For scheduling, use _next_window_instance instead --
    a fixed `year` alone is ambiguous once a rotation crosses a year boundary."""
    mm, dd = window[1].split("-")
    return date(year, int(mm), int(dd))


def _next_window_instance(window: tuple[str, str], not_before: date) -> tuple[date, date]:
    """
    The (window_start, window_end) pair for the first occurrence of this
    crop's sowing window whose end is not already before `not_before`.
    Handles windows that cross the Dec31->Jan1 boundary (none of the v0.1
    crops do, but a region pack for another climate might add one).

    This matters because a rotation's second, third, ... crop must resolve
    its window relative to WHEN THE PREVIOUS CROP FINISHES, not to a single
    fixed calendar year for the whole rotation -- e.g. Boro rice sown in
    December genuinely finishes the following May, so Aman rice's own
    July-August window has to be read as next year's occurrence, not the
    year the rotation nominally "starts" in.
    Only searches forward from `not_before` (never `not_before.year - 1`):
    searching backward would let a window instance that has ALREADY fully
    closed relative to `not_before` (e.g. last year's Dec-Jan window, once
    today is safely past its January end) get selected just because its
    end date happens to be numerically >= not_before in a later year's
    reading -- which is exactly the ambiguity a Dec-to-Jan window creates.
    """
    mm_s, dd_s = window[0].split("-")
    mm_e, dd_e = window[1].split("-")
    for candidate_year in (not_before.year, not_before.year + 1, not_before.year + 2):
        ws = date(candidate_year, int(mm_s), int(dd_s))
        we = date(candidate_year, int(mm_e), int(dd_e))
        if we < ws:
            we = we.replace(year=we.year + 1)
        if we >= not_before:
            return ws, we
    raise RuntimeError(f"could not resolve a window instance for {window} at or after {not_before}")


def check_calendar_feasibility(rotation: RotationCandidate, crop_lookup: dict,
                                min_turnaround_days: int, base_year: int,
                                max_total_span_days: int = 430) -> FeasibilityResult:
    """
    Walks the rotation's crops in sequence. Each crop is sown as early as
    possible within the first available occurrence of its own sowing window
    that starts no earlier than (previous harvest + min_turnaround_days). If
    that earliest-possible date falls after that window occurrence closes,
    the rotation is infeasible -- there is no way to fit this crop in after
    the one before it without waiting for the window's NEXT occurrence.

    A rotation candidate represents ONE annual cycle, so waiting for a much
    later occurrence is also rejected even when it is technically calendar-
    resolvable: `max_total_span_days` (default 400, i.e. a year plus five
    weeks of slack -- enough for Boro rice's natural into-May overhang) caps
    how long the whole sequence, first sowing to last harvest, may span (430 days comfortably covers the widest legitimate v0.1 case -- the triple-crop rotations R5/R6 span about 401 days -- while still rejecting sequences that only 'work' by waiting for next year's window instance, which isn't a single-cycle rotation anymore).
    """
    schedule: list[ScheduledCrop] = []
    earliest_next_sow = date(base_year, 1, 1)
    for crop_id in rotation.crop_ids:
        crop: CropProfile = crop_lookup[crop_id]
        window_start, window_end = _next_window_instance(crop.sowing_window, earliest_next_sow)
        sow = max(window_start, earliest_next_sow)
        if sow > window_end:
            gap_days = (sow - window_end).days
            return FeasibilityResult(
                rotation_id=rotation.rotation_id, feasible=False, schedule=schedule,
                reason=(f"{crop_id}: earliest possible sowing ({sow.isoformat()}, after the "
                        f"previous crop's harvest plus a {min_turnaround_days}-day turnaround) "
                        f"is {gap_days} day(s) after {crop_id}'s sowing window closes "
                        f"({window_end.isoformat()}). Calendar does not fit."),
            )
        harvest = sow + timedelta(days=crop.duration_days)
        schedule.append(ScheduledCrop(crop_id=crop_id, sow_date=sow, harvest_date=harvest))
        earliest_next_sow = harvest + timedelta(days=min_turnaround_days)

    total_span = (schedule[-1].harvest_date - schedule[0].sow_date).days
    if total_span > max_total_span_days:
        return FeasibilityResult(
            rotation_id=rotation.rotation_id, feasible=False, schedule=schedule,
            reason=(f"full sequence spans {total_span} days ({schedule[0].sow_date.isoformat()} "
                    f"to {schedule[-1].harvest_date.isoformat()}), more than the "
                    f"{max_total_span_days}-day limit for a single annual rotation cycle."),
        )

    return FeasibilityResult(rotation_id=rotation.rotation_id, feasible=True,
                              schedule=schedule, reason=None)


def check_soil_and_land(rotation: RotationCandidate, crop_lookup: dict,
                         field: FieldContext) -> FeasibilityResult:
    for crop_id in rotation.crop_ids:
        crop: CropProfile = crop_lookup[crop_id]
        if not (crop.min_ph <= field.soil_ph <= crop.max_ph):
            return FeasibilityResult(
                rotation.rotation_id, False, [],
                f"{crop_id}: needs soil pH {crop.min_ph}-{crop.max_ph}, "
                f"field is {field.soil_ph}.")
        if field.land_type == "lowland" and not crop.tolerates_waterlogging:
            return FeasibilityResult(
                rotation.rotation_id, False, [],
                f"{crop_id}: does not tolerate waterlogging, field land_type is 'lowland'.")
    return FeasibilityResult(rotation.rotation_id, True, [], None)


def check_family_sequence(rotation: RotationCandidate, crop_lookup: dict,
                           avoid_consecutive_families: tuple[str, ...]) -> FeasibilityResult:
    families = [crop_lookup[cid].family for cid in rotation.crop_ids]
    for i in range(len(families) - 1):
        if families[i] == families[i + 1] and families[i] in avoid_consecutive_families:
            return FeasibilityResult(
                rotation.rotation_id, False, [],
                f"consecutive {families[i]} crops ({rotation.crop_ids[i]} -> "
                f"{rotation.crop_ids[i+1]}) flagged for disease/pest carry-over.")
    return FeasibilityResult(rotation.rotation_id, True, [], None)


def filter_feasible(rotations: list, crop_lookup: dict, field: FieldContext,
                     min_turnaround_days: int, base_year: int,
                     avoid_consecutive_families: tuple[str, ...] = ()) -> tuple[list, list]:
    """Returns (accepted, rejected) where accepted is a list of
    (RotationCandidate, schedule) and rejected is a list of (rotation_id, reason)."""
    accepted, rejected = [], []
    for r in rotations:
        cal = check_calendar_feasibility(r, crop_lookup, min_turnaround_days, base_year)
        if not cal.feasible:
            rejected.append((r.rotation_id, cal.reason))
            continue
        soil = check_soil_and_land(r, crop_lookup, field)
        if not soil.feasible:
            rejected.append((r.rotation_id, soil.reason))
            continue
        fam = check_family_sequence(r, crop_lookup, avoid_consecutive_families)
        if not fam.feasible:
            rejected.append((r.rotation_id, fam.reason))
            continue
        accepted.append((r, cal.schedule))
    return accepted, rejected
