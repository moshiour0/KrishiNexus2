# -*- coding: utf-8 -*-
"""
fieldshift.engine.pipeline
============================
Orchestrates blueprint Section 6.1 steps 1-8: build field context, generate
candidates, filter by hard constraints, simulate under scenarios, compute
indicators, aggregate with farmer priorities, test robustness, emit a
ScoreCard. This is the one function the API layer and the demo both call.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from fieldshift.engine.constraints import filter_feasible
from fieldshift.engine.indicators import compute_indicators
from fieldshift.engine.models import CropProfile, FieldContext, RotationCandidate, ScoreCard, ScoredOption
from fieldshift.engine.scoring import rank_with_robustness
from fieldshift.engine.weather import generate_year, scale_scenario

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"

DEFAULT_SCENARIOS = (
    # (name, description, dtemp_c, rain_mult) -- delta-method, see weather.scale_scenario.
    # Deltas are illustrative and documented as such; blueprint Appendix A.2
    # is where the real NASA NEX-GDDP-CMIP6 ensemble deltas get pulled in.
    ("baseline", "Recent observed climate (synthetic stand-in)", 0.0, 1.0),
    ("warmer_drier", "Illustrative mid-century warming + reduced-rainfall scenario "
                     "(+1.5C, -10% rainfall) -- placeholder for NEX-GDDP-CMIP6 deltas", 1.5, 0.90),
    ("warmer_wetter", "Illustrative mid-century warming + intensified-monsoon scenario "
                      "(+1.5C, +15% rainfall) -- placeholder for NEX-GDDP-CMIP6 deltas", 1.5, 1.15),
)


def load_crop_library(path: Path | None = None) -> dict:
    path = path or CONFIG_DIR / "crops.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["crops"]
    out = {}
    for crop_id, c in raw.items():
        out[crop_id] = CropProfile(
            crop_id=crop_id, display_name=c["display_name"], family=c["family"],
            season=c["season"], sowing_window=tuple(c["sowing_window"]),
            duration_days=c["duration_days"], kc_ini=c["kc"]["ini"], kc_mid=c["kc"]["mid"],
            kc_end=c["kc"]["end"], stage_days=tuple(c["stage_days"]),
            root_depth_m=c["root_depth_m"], n_fixing=c["n_fixing"],
            residue_return=c["residue_return"], heat_critical_tmax_c=c["heat_critical_tmax_c"],
            heat_sensitive_stage=c["heat_sensitive_stage"],
            labour_person_days_per_ha=c["labour_person_days_per_ha"],
            price_bdt_per_kg=c["price_bdt_per_kg"],
            reference_yield_kg_per_ha=c["reference_yield_kg_per_ha"],
            prod_cost_bdt_per_ha=c["prod_cost_bdt_per_ha"],
            min_ph=c["ph_range"][0], max_ph=c["ph_range"][1],
            tolerates_waterlogging=c["tolerates_waterlogging"],
            sources=tuple(c.get("sources", ())), review_status=c.get("review_status", "placeholder"),
        )
    return out


def load_region_pack(path: Path | None = None) -> dict:
    path = path or CONFIG_DIR / "region_mymensingh.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def build_field_context(region: dict, overrides: dict | None = None) -> FieldContext:
    d = dict(region["field_defaults"])
    if overrides:
        d.update(overrides)
    return FieldContext(**d)


def build_candidate_rotations(region: dict) -> list:
    return [RotationCandidate(rotation_id=r["rotation_id"], label=r["label"],
                              crop_ids=tuple(r["crop_ids"]))
            for r in region["candidate_rotations"]]


def run(priorities: dict, field_overrides: dict | None = None, year: int = 2026,
        confidence_hint: str = "medium") -> ScoreCard:
    crop_lookup = load_crop_library()
    region = load_region_pack()
    field = build_field_context(region, field_overrides)
    rotations = build_candidate_rotations(region)

    # Two consecutive years, concatenated: Boro rice (sown mid-December,
    # ~145-day duration) genuinely crosses the calendar-year boundary, so a
    # single 365-day series runs out of data for any late-sown crop. This is
    # a real agronomic fact, not a bug to normalize away.
    baseline_daily = generate_year(year) + generate_year(year + 1, seed=43)
    scenarios = {}
    for name, desc, dtemp, rmult in DEFAULT_SCENARIOS:
        scenarios[name] = scale_scenario(baseline_daily, dtemp, rmult, name) if dtemp or rmult != 1.0 \
            else baseline_daily

    accepted, rejected = filter_feasible(
        rotations, crop_lookup, field,
        min_turnaround_days=region["min_turnaround_days"], base_year=year,
        avoid_consecutive_families=tuple(region.get("avoid_consecutive_families", ())),
    )

    indicator_sets_by_scenario = {s: {} for s in scenarios}
    for rotation, schedule in accepted:
        for s_name, daily in scenarios.items():
            indicator_sets_by_scenario[s_name][rotation.rotation_id] = compute_indicators(
                rotation.crop_ids, schedule, crop_lookup, daily, field, year
            )

    option_ids = [r.rotation_id for r, _ in accepted]
    ranking = rank_with_robustness(option_ids, indicator_sets_by_scenario, priorities)

    rotation_by_id = {r.rotation_id: r for r, _ in accepted}
    scored_options = []
    for oid in ranking["ranked_ids"]:
        info = ranking["by_option"][oid]
        scored_options.append(ScoredOption(
            rotation=rotation_by_id[oid],
            indicators_by_scenario={s: indicator_sets_by_scenario[s][oid] for s in scenarios},
            normalized_score_by_scenario=info["score_by_scenario"],
            mean_score=info["mean_score"],
            max_regret=info["max_regret"],
            pareto_optimal=info["pareto_optimal"],
            rank_probability_top1=info["rank_probability_top1"],
        ))

    caveats = [
        "Weather is SYNTHETIC (calibrated to general Mymensingh climatology), not a live NASA POWER/IMERG pull -- "
        "see engine/weather.py and blueprint Section 5.3.",
        "Soil values in this field context are regional placeholders, not a SoilGrids pull for this exact block.",
        "Crop coefficients and economic figures are a mix of cited literature values and explicit placeholders -- "
        "see config/crops.yaml 'review_status' and 'sources' per crop before treating any number as fact.",
        "Climate scenarios use an illustrative delta-method shift, not NASA NEX-GDDP-CMIP6 model output.",
    ]

    return ScoreCard(
        block_id=field.block_id,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        priorities=priorities,
        data_freshness={"weather": "synthetic", "soil": "placeholder", "crop_library": "config/crops.yaml v0.1"},
        options=scored_options,
        rejected=rejected,
        confidence=confidence_hint,
        caveats=caveats,
    )
