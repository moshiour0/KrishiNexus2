from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Provenance:
    source: str
    source_type: str  # observed, satellite, modeled, farmer, literature, estimated, synthetic
    retrieval_date: str | None = None
    spatial_resolution: str | None = None
    temporal_resolution: str | None = None
    citation: str | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("provenance confidence must be within [0,1]")


@dataclass
class SoilProfile:
    ph: float | None = None
    soc_pct: float | None = None
    total_n_mgkg: float | None = None
    available_p_mgkg: float | None = None
    exchangeable_k_mgkg: float | None = None
    ec_ds_m: float | None = None
    cec_cmolkg: float | None = None
    bulk_density_g_cm3: float | None = None
    sand_pct: float | None = None
    silt_pct: float | None = None
    clay_pct: float | None = None
    soil_depth_m: float | None = None
    field_capacity_v_v: float | None = None
    wilting_point_v_v: float | None = None
    drainage_class: str | None = None
    provenance: dict[str, Provenance] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, lo, hi in [
            ("ph", 2.0, 12.0), ("soc_pct", 0.0, 30.0), ("sand_pct", 0.0, 100.0),
            ("silt_pct", 0.0, 100.0), ("clay_pct", 0.0, 100.0), ("bulk_density_g_cm3", 0.5, 2.3),
            ("field_capacity_v_v", 0.0, 0.9), ("wilting_point_v_v", 0.0, 0.9),
        ]:
            value = getattr(self, name)
            if value is not None and not (lo <= value <= hi):
                raise ValueError(f"{name}={value} outside [{lo}, {hi}]")
        if self.field_capacity_v_v is not None and self.wilting_point_v_v is not None:
            if self.field_capacity_v_v <= self.wilting_point_v_v:
                raise ValueError("field capacity must exceed wilting point")


@dataclass(frozen=True)
class WeatherDay:
    d: date
    tmax_c: float
    tmin_c: float
    rh_mean_pct: float
    wind_2m_ms: float
    solar_rad_mj_m2_day: float
    rain_mm: float
    source: str = "synthetic"
    provenance: Provenance | None = None


@dataclass(frozen=True)
class RemoteDay:
    d: date
    ndvi: float | None = None
    evi: float | None = None
    ndmi: float | None = None
    smap_surface_m3_m3: float | None = None
    smap_rootzone_m3_m3: float | None = None
    modis_et_mm: float | None = None
    gpm_rain_mm: float | None = None
    source: str = "unknown"
    provenance: Provenance | None = None


@dataclass(frozen=True)
class CropV2:
    crop_id: str
    display_name: str
    family: str
    seasons: tuple[str, ...]
    sowing_window: tuple[str, str]
    duration_days: int
    stage_days: tuple[int, int, int, int]
    kc_ini: float
    kc_mid: float
    kc_end: float
    root_depth_m: float
    heat_sensitive_stage: tuple[str, int, int]  # label, offset_start, offset_end within cycle
    heat_threshold_c: float
    drought_tolerance: float
    waterlogging_tolerance: float
    salinity_tolerance: float
    n_fixing: bool
    residue_score: float
    yield_kg_ha: float
    price_bdt_kg: float
    cost_bdt_ha: float
    labour_person_days_ha: float
    n_demand_kg_ha: float
    p_demand_kg_ha: float
    k_demand_kg_ha: float
    family_break_value: float
    pH_range: tuple[float, float]
    rice_paddy: bool = False
    standing_water_days: float = 0.0
    percolation_mm_day: float = 0.0
    seepage_mm_day: float = 0.0
    yield_stress_sens_water: float = 1.0
    yield_stress_sens_heat: float = 1.0
    source_refs: tuple[str, ...] = ()
    review_status: str = "placeholder"


@dataclass(frozen=True)
class ScheduledCropV2:
    crop_id: str
    sow_date: date
    harvest_date: date


@dataclass(frozen=True)
class Rotation:
    rotation_id: str
    crop_ids: tuple[str, ...]
    label: str
    source: str = "generated"


@dataclass
class FarmerContext:
    priorities: dict[str, float]
    water_available_mm_season: float | None = None
    irrigation_reliability: float = 1.0
    labour_available_person_days_ha: float | None = None
    budget_bdt_ha: float | None = None
    market_access_score: float = 0.8
    risk_tolerance: float = 0.5
    preferred_crops: tuple[str, ...] = ()
    avoided_crops: tuple[str, ...] = ()

    def validate(self) -> None:
        if any(v < 0 for v in self.priorities.values()):
            raise ValueError("priority weights must be non-negative")
        if abs(sum(self.priorities.values()) - 1.0) > 1e-6:
            raise ValueError("priority weights must sum to 1")
        if not 0 <= self.irrigation_reliability <= 1:
            raise ValueError("irrigation_reliability must be in [0,1]")


@dataclass
class FieldV2:
    field_id: str
    lat: float
    lon: float
    area_ha: float
    elevation_m: float = 20.0
    land_type: str = "medium highland"
    soil: SoilProfile = field(default_factory=SoilProfile)
    irrigation_source: str = "unknown"
    farmer: FarmerContext = field(default_factory=lambda: FarmerContext(priorities={}))
    previous_crop: str | None = None
    polygon: list[tuple[float, float]] | None = None
    provenance: dict[str, Provenance] = field(default_factory=dict)

    def validate(self) -> None:
        if not -90 <= self.lat <= 90 or not -180 <= self.lon <= 180:
            raise ValueError("invalid latitude/longitude")
        if self.area_ha <= 0:
            raise ValueError("area_ha must be positive")
        self.farmer.validate()


@dataclass
class Scenario:
    name: str
    description: str
    weather: tuple[WeatherDay, ...]
    remote: tuple[RemoteDay, ...] = ()
    source: str = "synthetic"
    provenance: list[Provenance] = field(default_factory=list)


@dataclass
class IndicatorBundle:
    rotation_id: str
    scenario: str
    values: dict[str, float]
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DimensionResult:
    values: dict[str, float]
    contributions: dict[str, float]


@dataclass
class ScenarioScore:
    scenario: str
    dimension_scores: dict[str, float]
    overall_score: float


@dataclass
class RobustnessResult:
    score_mean: float
    score_p10: float
    score_p50: float
    score_p90: float
    top1_probability: float
    rank_mean: float
    rank_p90: float
    regret_max: float
    pareto_optimal: bool
    sensitivity: dict[str, float]


@dataclass
class Evaluation:
    rotation: Rotation
    schedule: tuple[ScheduledCropV2, ...]
    indicators_by_scenario: dict[str, IndicatorBundle]
    scenario_scores: dict[str, ScenarioScore]
    robustness: RobustnessResult
    explanation: dict[str, Any]


@dataclass
class EngineRun:
    engine_version: str
    generated_at: str
    field_id: str
    objective_weights: dict[str, float]
    scenarios: list[str]
    evaluations: list[Evaluation]
    rejected: list[dict[str, str]]
    dataset_registry: list[dict[str, Any]]
    validation: dict[str, Any]
    ablation: dict[str, Any]
    system_capabilities: list[str]

    def top(self, n: int = 3) -> list[Evaluation]:
        return self.evaluations[:n]
