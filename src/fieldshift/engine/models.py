# -*- coding: utf-8 -*-
"""
fieldshift.engine.models
=========================
Typed data contracts for the Field Shift decision engine.

Deliberately dependency-free (stdlib `dataclasses` only, no pydantic) so the
project runs anywhere with zero install friction during a live demo. Each
class validates itself in __post_init__ so a bad value fails loudly at the
boundary that produced it, per Section 4.2 of the architecture blueprint
("typed contracts at every boundary", "fail safe, not silent").
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Literal

Season = Literal["rabi", "kharif1", "kharif2"]


def _check_range(name: str, value: float, lo: float, hi: float) -> None:
    if not (lo <= value <= hi):
        raise ValueError(f"{name}={value!r} is outside the plausible range [{lo}, {hi}]")


def _check_unit_weights(weights: dict) -> None:
    total = sum(weights.values())
    if any(w < 0 for w in weights.values()):
        raise ValueError(f"priority weights must be non-negative, got {weights}")
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"priority weights must sum to 1.0, got {total:.6f} ({weights})")


@dataclass(frozen=True)
class FieldContext:
    """Where and what we are planning for. Section 6.1 Step 1."""
    block_id: str
    lat: float
    lon: float
    area_ha: float
    soil_texture: str          # e.g. "silty clay loam" -- from SoilGrids or farmer input
    soil_ph: float
    soil_organic_carbon_pct: float
    irrigation_reliable: bool
    irrigation_source: str     # "shallow tubewell" | "canal" | "rainfed" | ...
    land_type: str             # "highland" | "medium highland" | "medium lowland" | "lowland"
    previous_crop: str | None = None
    data_sources: dict = field(default_factory=dict)   # provenance: {"soil": "SoilGrids v2.0 snapshot 2026-09", ...}

    def __post_init__(self):
        _check_range("lat", self.lat, -90, 90)
        _check_range("lon", self.lon, -180, 180)
        _check_range("area_ha", self.area_ha, 0.01, 10_000)
        _check_range("soil_ph", self.soil_ph, 2.5, 10.5)
        _check_range("soil_organic_carbon_pct", self.soil_organic_carbon_pct, 0, 30)


@dataclass(frozen=True)
class DailyWeather:
    """One day of the variables FAO-56 Penman-Monteith needs. Section 5 / Appendix A.5."""
    d: date
    tmax_c: float
    tmin_c: float
    rh_mean_pct: float
    wind_2m_ms: float
    solar_rad_mj_m2_day: float
    rain_mm: float
    source: str = "synthetic"   # "NASA POWER" once wired to the live API (Section 5.3)


@dataclass(frozen=True)
class ClimateScenario:
    """A named weather series plus its provenance. Section 6.5."""
    name: str                  # "baseline" | "ssp245_midcentury" | "ssp585_midcentury"
    description: str
    daily: tuple[DailyWeather, ...]
    provenance: str


@dataclass(frozen=True)
class CropProfile:
    """One entry of the crop library (config/crops.yaml). Section 6.2."""
    crop_id: str
    display_name: str
    family: str
    season: Season
    sowing_window: tuple[str, str]      # ("MM-DD", "MM-DD")
    duration_days: int
    kc_ini: float
    kc_mid: float
    kc_end: float
    stage_days: tuple[int, int, int, int]   # ini, dev, mid, late (sums to duration_days)
    root_depth_m: float
    n_fixing: bool
    residue_return: Literal["low", "medium", "high"]
    heat_critical_tmax_c: float
    heat_sensitive_stage: str
    labour_person_days_per_ha: float
    price_bdt_per_kg: float
    reference_yield_kg_per_ha: float
    prod_cost_bdt_per_ha: float
    min_ph: float
    max_ph: float
    tolerates_waterlogging: bool
    sources: tuple[str, ...] = ()
    review_status: Literal["cited", "placeholder", "expert_reviewed"] = "placeholder"

    def __post_init__(self):
        if sum(self.stage_days) != self.duration_days:
            raise ValueError(
                f"{self.crop_id}: stage_days {self.stage_days} sum to "
                f"{sum(self.stage_days)}, expected duration_days={self.duration_days}"
            )
        if self.review_status == "cited" and not self.sources:
            raise ValueError(f"{self.crop_id}: marked 'cited' but has no sources listed")


@dataclass(frozen=True)
class RotationCandidate:
    """A one-year (or multi-crop) sequence proposed by the generator. Section 6.1 Step 2."""
    rotation_id: str
    label: str
    crop_ids: tuple[str, ...]
    notes: str = ""


@dataclass
class IndicatorSet:
    """Per-option, per-scenario computed indicators. Section 6.4."""
    irrigation_requirement_mm: float
    water_stress_risk: float          # 0-1, share of scenario-days short of supply
    heat_stress_days: int
    waterlogging_risk_days: int
    soil_health_index: float          # 0-100
    income_proxy_bdt_per_ha: float
    labour_peak_person_days_per_ha: float
    turnaround_margin_days: int

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScoredOption:
    rotation: RotationCandidate
    indicators_by_scenario: dict            # scenario_name -> IndicatorSet
    normalized_score_by_scenario: dict      # scenario_name -> float (0-1)
    mean_score: float
    max_regret: float
    pareto_optimal: bool
    rank_probability_top1: float | None = None   # filled by weight-sensitivity sampling


@dataclass
class ScoreCard:
    """The Layer-3 -> Layer-4 contract. Section 4.3."""
    block_id: str
    generated_at: str
    priorities: dict                    # {"soil_health": 0.35, "water_saving": 0.25, ...}
    data_freshness: dict
    options: list                       # list[ScoredOption], best-first
    rejected: list                      # [(rotation_id, reason), ...]
    confidence: Literal["high", "medium", "low"]
    caveats: list

    def __post_init__(self):
        _check_unit_weights(self.priorities)

    def top(self, n: int = 3):
        return self.options[:n]
