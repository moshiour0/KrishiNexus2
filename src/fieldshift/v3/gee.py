from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NEX_GDDP_ASSET = "NASA/GDDP-CMIP6"
HISTORICAL_START = "1995-01-01"
HISTORICAL_END = "2015-01-01"
MIDCENTURY_START = "2041-01-01"
MIDCENTURY_END = "2061-01-01"
BANDS = ("tasmax", "tasmin", "hurs", "pr", "rsds", "sfcWind")
_BAND_LIMITS = {
    "tasmax": (180.0, 360.0),
    "tasmin": (180.0, 360.0),
    "hurs": (0.0, 100.0),
    "pr": (0.0, 0.05),
    "rsds": (0.0, 1000.0),
    "sfcWind": (0.0, 80.0),
}
_INIT_LOCK = threading.Lock()
_EE_INITIALIZED = False


@dataclass(frozen=True)
class NEXDeltaResult:
    monthly: dict[int, dict[str, float | None]] | None
    status: str
    retrieved_at: str | None = None
    age_seconds: int | None = None
    error: str | None = None


def gee_credentials_configured() -> bool:
    return bool(
        os.getenv("FIELD_SHIFT_GEE_PROJECT", "").strip()
        and os.getenv("FIELD_SHIFT_GEE_SERVICE_ACCOUNT_JSON", "").strip()
    )


def _cache_path(cache_dir: Path, lat: float, lon: float, scenario: str) -> Path:
    key = f"{NEX_GDDP_ASSET}|{lat:.5f}|{lon:.5f}|{scenario}|{HISTORICAL_START}:{HISTORICAL_END}|{MIDCENTURY_START}:{MIDCENTURY_END}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return cache_dir / f"nex_gddp_{digest}.json"


def _read_cache(path: Path) -> tuple[dict[str, Any] | None, int | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = max(0, int(time.time() - path.stat().st_mtime))
        return payload, age
    except (OSError, ValueError, TypeError):
        return None, None


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump(payload, handle, allow_nan=False)
            temp_path = Path(handle.name)
        os.replace(temp_path, path)
    except OSError:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def monthly_climate_deltas(
    historical: dict[int, dict[str, float]], future: dict[int, dict[str, float]],
) -> dict[int, dict[str, float | None]]:
    """Convert NEX model normals into bounded, unit-aware climate-change signals."""
    output: dict[int, dict[str, float | None]] = {}
    for month in range(1, 13):
        old, new = historical.get(month), future.get(month)
        if old is None or new is None:
            raise ValueError(f"NEX-GDDP-CMIP6 is missing a monthly normal for month {month}")
        missing = [band for band in BANDS if _finite(old.get(band)) is None or _finite(new.get(band)) is None]
        if missing:
            raise ValueError(f"NEX-GDDP-CMIP6 is missing {', '.join(missing)} for month {month}")
        old_rain = float(old["pr"]) * 86400.0
        new_rain = float(new["pr"]) * 86400.0
        old_solar = float(old["rsds"])
        new_solar = float(new["rsds"])
        old_wind = float(old["sfcWind"])
        new_wind = float(new["sfcWind"])
        output[month] = {
            # Temperature differences are unchanged by conversion from Kelvin to Celsius.
            "tasmax_delta_c": float(new["tasmax"]) - float(old["tasmax"]),
            "tasmin_delta_c": float(new["tasmin"]) - float(old["tasmin"]),
            "hurs_delta_pct": float(new["hurs"]) - float(old["hurs"]),
            # Keep dry days dry; do not invent a ratio when the modeled historical normal is zero.
            "precip_ratio": new_rain / old_rain if old_rain > 0.05 else None,
            "historical_precip_mm_day": old_rain,
            "future_precip_mm_day": new_rain,
            "solar_ratio": new_solar / old_solar if old_solar > 0.0 else None,
            "wind_ratio": new_wind / old_wind if old_wind > 0.0 else None,
        }
    return output


def apply_monthly_deltas(weather: tuple, monthly: dict[int, dict[str, float | None]]) -> tuple:
    """Apply NEX monthly signals to a dated daily analogue without changing its dates."""
    adjusted = []
    for day in weather:
        delta = monthly.get(day.d.month)
        if not delta:
            raise ValueError(f"NEX-GDDP-CMIP6 has no climate signal for month {day.d.month}")
        rain_ratio = delta.get("precip_ratio")
        solar_ratio = delta.get("solar_ratio")
        wind_ratio = delta.get("wind_ratio")
        adjusted.append(type(day)(
            d=day.d,
            tmax_c=day.tmax_c + float(delta["tasmax_delta_c"] or 0.0),
            tmin_c=day.tmin_c + float(delta["tasmin_delta_c"] or 0.0),
            rh_mean_pct=max(0.0, min(100.0, day.rh_mean_pct + float(delta["hurs_delta_pct"] or 0.0))),
            wind_2m_ms=max(0.0, day.wind_2m_ms * float(wind_ratio if wind_ratio is not None else 1.0)),
            solar_rad_mj_m2_day=max(0.0, day.solar_rad_mj_m2_day * float(solar_ratio if solar_ratio is not None else 1.0)),
            rain_mm=max(0.0, day.rain_mm * float(rain_ratio if rain_ratio is not None else 1.0)),
            source=f"NASA POWER daily analogue + NASA NEX-GDDP-CMIP6 {day.d.month:02d} climate signal",
            provenance=day.provenance,
        ))
    return tuple(adjusted)


def _initialise_ee():
    global _EE_INITIALIZED
    import ee
    if _EE_INITIALIZED:
        return ee
    with _INIT_LOCK:
        if not _EE_INITIALIZED:
            from google.oauth2.service_account import Credentials

            raw = os.environ["FIELD_SHIFT_GEE_SERVICE_ACCOUNT_JSON"]
            info = json.loads(raw)
            if not isinstance(info, dict) or info.get("type") != "service_account":
                raise ValueError("FIELD_SHIFT_GEE_SERVICE_ACCOUNT_JSON must be a service-account JSON object")
            credentials = Credentials.from_service_account_info(
                info,
                scopes=["https://www.googleapis.com/auth/earthengine", "https://www.googleapis.com/auth/cloud-platform"],
            )
            ee.Initialize(credentials, project=os.environ["FIELD_SHIFT_GEE_PROJECT"].strip())
            _EE_INITIALIZED = True
    return ee


def _model_weighted_band_image(ee, collection, month: int, band: str):
    subset = collection.filter(ee.Filter.calendarRange(month, month, "month"))
    subset = subset.filter(ee.Filter.listContains("system:band_names", band))
    lower, upper = _BAND_LIMITS[band]

    def mask_physical_values(image):
        values = image.select([band])
        valid = values.gte(lower).And(values.lte(upper))
        return image.addBands(values.updateMask(valid), overwrite=True)

    subset = subset.map(mask_physical_values)
    model_names = ee.List(subset.aggregate_array("model")).distinct().sort()
    model_images = model_names.map(
        lambda model: subset.filter(ee.Filter.eq("model", model)).select([band]).mean()
    )
    return ee.ImageCollection.fromImages(model_images).mean().rename(band)


def _fetch_monthly_normals(lat: float, lon: float, scenario: str) -> dict[str, dict[int, dict[str, float]]]:
    ee = _initialise_ee()
    point = ee.Geometry.Point([lon, lat])
    collection = ee.ImageCollection(NEX_GDDP_ASSET)
    periods = {
        "historical": (HISTORICAL_START, HISTORICAL_END, "historical"),
        "future": (MIDCENTURY_START, MIDCENTURY_END, scenario),
    }
    features = []
    for period_name, (start, end, scenario_name) in periods.items():
        subset = collection.filterDate(start, end).filter(ee.Filter.eq("scenario", scenario_name))
        for month in range(1, 13):
            image = ee.Image.cat([_model_weighted_band_image(ee, subset, month, band) for band in BANDS])
            stats = image.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=point, scale=27830, maxPixels=10000, bestEffort=True,
            )
            features.append(ee.Feature(None, stats).set({"period": period_name, "month": month}))
    result = ee.FeatureCollection(features).getInfo()
    normals: dict[str, dict[int, dict[str, float]]] = {"historical": {}, "future": {}}
    for feature in result.get("features", []):
        props = feature.get("properties", {})
        period = str(props.get("period", ""))
        month = int(props.get("month", 0))
        if period not in normals or not 1 <= month <= 12:
            continue
        vals = {band: _finite(props.get(band)) for band in BANDS}
        if all(value is not None for value in vals.values()):
            normals[period][month] = {band: float(value) for band, value in vals.items() if value is not None}
    if len(normals["historical"]) != 12 or len(normals["future"]) != 12:
        raise ValueError("Earth Engine returned incomplete monthly model normals for the selected point")
    return normals


def nex_gddp_monthly_deltas(
    lat: float, lon: float, scenario: str, cache_dir: str | Path,
) -> NEXDeltaResult:
    if scenario not in {"ssp245", "ssp585"}:
        raise ValueError("NEX-GDDP-CMIP6 scenario must be 'ssp245' or 'ssp585'")
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("invalid latitude/longitude for NASA NEX-GDDP-CMIP6")
    cache_path = _cache_path(Path(cache_dir), lat, lon, scenario)
    cached, age = _read_cache(cache_path)
    ttl = max(60, int(os.getenv("FIELD_SHIFT_GEE_CACHE_TTL_SECONDS", "604800")))
    if cached and age is not None and age <= ttl:
        try:
            monthly = {int(month): values for month, values in cached["monthly"].items()}
            if len(monthly) == 12:
                return NEXDeltaResult(monthly, "cache", cached.get("retrieved_at"), age)
        except (KeyError, TypeError, ValueError):
            pass
    if not gee_credentials_configured():
        if cached and age is not None:
            try:
                monthly = {int(month): values for month, values in cached["monthly"].items()}
                if len(monthly) == 12:
                    return NEXDeltaResult(monthly, "stale-cache", cached.get("retrieved_at"), age)
            except (KeyError, TypeError, ValueError):
                pass
        return NEXDeltaResult(None, "not_configured", error="Google Earth Engine service credentials are not configured.")
    try:
        normals = _fetch_monthly_normals(lat, lon, scenario)
        monthly = monthly_climate_deltas(normals["historical"], normals["future"])
        retrieved_at = datetime.now(UTC).isoformat()
        _write_cache(cache_path, {"monthly": monthly, "retrieved_at": retrieved_at})
        return NEXDeltaResult(monthly, "live", retrieved_at)
    except Exception as exc:
        if cached and age is not None:
            try:
                monthly = {int(month): values for month, values in cached["monthly"].items()}
                if len(monthly) == 12:
                    return NEXDeltaResult(monthly, "stale-cache", cached.get("retrieved_at"), age, type(exc).__name__)
            except (KeyError, TypeError, ValueError):
                pass
        # Do not surface provider response text here: it may contain auth or account details.
        return NEXDeltaResult(None, "unavailable", error=f"Earth Engine request failed ({type(exc).__name__}).")
