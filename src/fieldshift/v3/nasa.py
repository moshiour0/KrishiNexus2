from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

from .models import Provenance, RemoteDay, WeatherDay
from .provenance import now_iso

NASA_POWER_BASE = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_PARAMS = "T2M_MAX,T2M_MIN,RH2M,WS2M,ALLSKY_SFC_SW_DWN,PRECTOTCORR"


class NasaDataError(RuntimeError):
    pass


def _http_json(url: str, timeout: int = 30, retries: int = 3) -> dict:
    last: Exception | None = None
    for attempt in range(max(1, retries)):
        req = urllib.request.Request(url, headers={"User-Agent": "FieldShift-V3/3.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # pragma: no cover - network failure is exercised by integration users
            last = exc
            if attempt + 1 < retries:
                time.sleep(0.8 * (2 ** attempt))
    raise NasaDataError(f"NASA data request failed after {retries} attempts: {last}") from last


def _cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return cache_dir / f"power_{digest}.json"


def _fill_missing(
    series: dict[str, float | int | None],
    expected_keys: list[str] | None = None,
) -> tuple[dict[str, float], int]:
    keys = expected_keys or sorted(series)
    vals: list[float | None] = []
    for key in keys:
        value = series.get(key)
        vals.append(float(value) if value is not None and value not in (-999, -999.0) else None)
    missing = sum(v is None for v in vals)
    known = [(i, v) for i, v in enumerate(vals) if v is not None]
    if not known:
        raise NasaDataError("NASA POWER parameter has no usable values")
    max_missing = max(1, int(len(vals) * float(os.getenv("FIELD_SHIFT_POWER_MAX_IMPUTE_FRACTION", "0.10"))))
    if missing > max_missing:
        raise NasaDataError(f"NASA POWER parameter has too many missing days ({missing}/{len(vals)})")
    missing_run = 0
    longest_missing_run = 0
    for value in vals:
        if value is None:
            missing_run += 1
            longest_missing_run = max(longest_missing_run, missing_run)
        else:
            missing_run = 0
    if longest_missing_run > int(os.getenv("FIELD_SHIFT_POWER_MAX_GAP_DAYS", "5")):
        raise NasaDataError(f"NASA POWER has a consecutive gap of {longest_missing_run} days")
    for i, v in enumerate(vals):
        if v is not None:
            continue
        left = max((x for x in known if x[0] < i), default=None, key=lambda x: x[0])
        right = min((x for x in known if x[0] > i), default=None, key=lambda x: x[0])
        if left and right:
            li, lv = left
            ri, rv = right
            frac = (i - li) / max(1, ri - li)
            vals[i] = lv + frac * (rv - lv)
        elif left:
            vals[i] = left[1]
        else:
            vals[i] = right[1]  # type: ignore[index]
    return {k: float(v if v is not None else 0.0) for k, v in zip(keys, vals)}, missing


def _cache_read(cache_path: Path) -> tuple[dict | None, float | None]:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return payload, max(0.0, time.time() - cache_path.stat().st_mtime)
    except (OSError, ValueError, TypeError):
        return None, None


def _cache_write(cache_path: Path, payload: dict) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache_path.parent, delete=False) as handle:
            json.dump(payload, handle)
            tmp_path = Path(handle.name)
        os.replace(tmp_path, cache_path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass


def power_daily(
    lat: float,
    lon: float,
    start: date,
    end: date,
    timeout: int = 30,
    retries: int = 3,
    cache_dir: str | Path | None = None,
) -> tuple[WeatherDay, ...]:
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("invalid latitude/longitude for NASA POWER")
    if start > end:
        raise ValueError("NASA POWER start date must be on or before end date")
    query = urllib.parse.urlencode({
        "parameters": POWER_PARAMS,
        "community": "AG",
        "longitude": f"{lon:.6f}",
        "latitude": f"{lat:.6f}",
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
        "time-standard": "LST",
    })
    url = f"{NASA_POWER_BASE}?{query}"
    payload: dict
    cache_age_seconds: float | None = None
    stale_cache = False
    cache_path = _cache_path(Path(cache_dir), url) if cache_dir else None
    cached_payload = None
    if cache_path and cache_path.exists():
        cached_payload, cache_age_seconds = _cache_read(cache_path)
    cache_ttl_seconds = max(60, int(os.getenv("FIELD_SHIFT_POWER_CACHE_TTL_SECONDS", "43200")))
    if cached_payload is not None and cache_age_seconds is not None and cache_age_seconds <= cache_ttl_seconds:
        payload = cached_payload
        cache_status = "cache"
    else:
        try:
            payload = _http_json(url, timeout=timeout, retries=retries)
            cache_status = "live"
            if cache_path:
                _cache_write(cache_path, payload)
        except NasaDataError:
            if cached_payload is None:
                raise
            payload = cached_payload
            cache_status = "stale-cache"
            stale_cache = True
    try:
        params = payload["properties"]["parameter"]
    except KeyError as exc:
        raise NasaDataError("unexpected NASA POWER payload") from exc
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y%m%d"))
        current = date.fromordinal(current.toordinal() + 1)
    if not dates:
        raise NasaDataError("NASA POWER returned an empty requested date range")
    filled: dict[str, dict[str, float]] = {}
    missing_total = 0
    for name in POWER_PARAMS.split(","):
        series = params.get(name)
        if not isinstance(series, dict):
            raise NasaDataError(f"NASA POWER response is missing parameter {name}")
        filled[name], missing = _fill_missing(series, dates)
        missing_total += missing
    imputation_fraction = missing_total / max(1, len(dates) * len(POWER_PARAMS.split(",")))
    actual_retrieval = (
        datetime.fromtimestamp(time.time() - cache_age_seconds, UTC).isoformat()
        if cache_status in {"cache", "stale-cache"} and cache_age_seconds is not None
        else now_iso()
    )
    prov = Provenance(
        source="NASA POWER Daily API",
        source_type="observed/model-derived",
        retrieval_date=actual_retrieval,
        temporal_resolution="daily",
        spatial_resolution=f"point ({lat:.4f}, {lon:.4f})",
        citation="https://power.larc.nasa.gov/docs/services/api/temporal/daily/",
        confidence=max(0.65, (0.94 if stale_cache else 0.96) - 2.0 * imputation_fraction),
    )
    out = []
    for key in dates:
        y, m, d = int(key[:4]), int(key[4:6]), int(key[6:8])
        out.append(WeatherDay(
            date(y, m, d), filled["T2M_MAX"][key], filled["T2M_MIN"][key], filled["RH2M"][key], filled["WS2M"][key],
            filled["ALLSKY_SFC_SW_DWN"][key], max(0.0, filled["PRECTOTCORR"][key]),
            source=(
                f"NASA POWER ({cache_status}; age={int(cache_age_seconds or 0)}s; {missing_total} values imputed)"
                if stale_cache else
                f"NASA POWER ({cache_status}; {missing_total} values imputed)" if missing_total else
                f"NASA POWER ({cache_status})"
            ),
            provenance=prov,
        ))
    return tuple(out)


def power_json_file(path: str | Path) -> tuple[WeatherDay, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    params = payload["properties"]["parameter"]
    dates = sorted(params["T2M_MAX"].keys())
    filled = {name: _fill_missing(params[name])[0] for name in POWER_PARAMS.split(",")}
    prov = Provenance(
        source=f"NASA POWER cached file: {Path(path).name}", source_type="observed/model-derived",
        temporal_resolution="daily", spatial_resolution="point",
        citation="https://power.larc.nasa.gov/docs/services/api/temporal/daily/", confidence=0.95,
    )
    return tuple(
        WeatherDay(date(int(k[:4]), int(k[4:6]), int(k[6:8])), filled["T2M_MAX"][k], filled["T2M_MIN"][k],
                   filled["RH2M"][k], filled["WS2M"][k], filled["ALLSKY_SFC_SW_DWN"][k], max(0.0, filled["PRECTOTCORR"][k]),
                   source="NASA POWER cache", provenance=prov)
        for k in dates
    )


def load_timeseries_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def remote_csv(path: str | Path, source: str, source_type: str = "satellite") -> tuple[RemoteDay, ...]:
    rows = load_timeseries_csv(path)
    out: list[RemoteDay] = []
    prov = Provenance(source=source, source_type=source_type, temporal_resolution="native", citation=None, confidence=0.85)
    fields = ("ndvi", "evi", "ndmi", "smap_surface_m3_m3", "smap_rootzone_m3_m3", "modis_et_mm", "gpm_rain_mm")
    for r in rows:
        d = date.fromisoformat(r["date"])
        kw = {k: float(r[k]) for k in fields if r.get(k) not in (None, "", "NA", "-999", "-999.0")}
        period_days = 1
        if source == "NASA MODIS MOD16" and "modis_et_mm" in kw:
            try:
                raw_qa = r.get("modis_et_qc")
                if raw_qa is None:
                    raise ValueError("MODIS ET quality flag is missing")
                qa = int(float(raw_qa))
                period_days = max(1, int(float(r.get("modis_et_period_days", "8"))))
            except (TypeError, ValueError):
                kw.pop("modis_et_mm", None)
            else:
                if qa & 0b11:
                    kw.pop("modis_et_mm", None)
        elif source == "NASA HLS":
            raw_qa = r.get("hls_qa")
            if raw_qa is not None and raw_qa not in ("", "NA"):
                try:
                    qa = int(float(raw_qa))
                except (TypeError, ValueError):
                    qa = 255
                if qa < 0 or (qa & 0b00111110) != 0 or ((qa >> 6) & 0b11) == 3:
                    for key in ("ndvi", "evi", "ndmi"):
                        kw.pop(key, None)
        elif source == "NASA SMAP" and ("smap_surface_m3_m3" in kw or "smap_rootzone_m3_m3" in kw):
            product = str(r.get("smap_product", "")).upper()
            if product.startswith("SPL3"):
                try:
                    qa = int(float(r.get("smap_qa", "")))
                except (TypeError, ValueError):
                    qa = -1
                if qa not in {0, 8}:
                    kw.pop("smap_surface_m3_m3", None)
                    kw.pop("smap_rootzone_m3_m3", None)
            elif not product.startswith("SPL4SMGP"):
                kw.pop("smap_surface_m3_m3", None)
                kw.pop("smap_rootzone_m3_m3", None)
        if kw:
            out.append(RemoteDay(d=d, source=source, provenance=prov, modis_et_period_days=period_days, **kw))
    return tuple(out)


def load_gpm_csv(path: str | Path) -> tuple[RemoteDay, ...]:
    return remote_csv(path, "NASA GPM IMERG", "satellite")


def load_smap_csv(path: str | Path) -> tuple[RemoteDay, ...]:
    return remote_csv(path, "NASA SMAP", "satellite")


def load_hls_csv(path: str | Path) -> tuple[RemoteDay, ...]:
    return remote_csv(path, "NASA HLS", "satellite")


def load_modis_et_csv(path: str | Path) -> tuple[RemoteDay, ...]:
    return remote_csv(path, "NASA MODIS MOD16", "satellite")


def load_nex_gddp_csv(path: str | Path, scenario_name: str) -> tuple[WeatherDay, ...]:
    rows = load_timeseries_csv(path)
    prov = Provenance(
        source=f"NASA NEX-GDDP-CMIP6 ({scenario_name})", source_type="modeled",
        temporal_resolution="daily", spatial_resolution="downscaled grid",
        citation="https://www.nccs.nasa.gov/nex-gddp/", confidence=0.80,
    )
    return tuple(
        WeatherDay(
            d=date.fromisoformat(r["date"]), tmax_c=float(r["tmax_c"]), tmin_c=float(r["tmin_c"]),
            rh_mean_pct=float(r.get("rh_mean_pct", 70)), wind_2m_ms=float(r.get("wind_2m_ms", 1.5)),
            solar_rad_mj_m2_day=float(r.get("solar_rad_mj_m2_day", 18)), rain_mm=float(r["rain_mm"]),
            source=f"NEX-GDDP-CMIP6:{scenario_name}", provenance=prov,
        ) for r in rows
    )


def align_nex_weather_to_analysis(
    projected_weather: tuple[WeatherDay, ...], analysis_weather: tuple[WeatherDay, ...],
) -> tuple[WeatherDay, ...]:
    """Map available projected climate years onto the crop-plan calendar.

    NEX-GDDP-CMIP6 files normally contain future dates, while rotations are
    simulated on the farmer's selected planning years. Select one successive
    projected analogue year for each plan year and preserve all target dates,
    so water-balance lookups and sow/harvest schedules remain aligned.
    """
    if not projected_weather or not analysis_weather:
        raise NasaDataError("NEX-GDDP-CMIP6 and analysis weather must both contain daily records")
    source_years = sorted({item.d.year for item in projected_weather})
    target_years = sorted({item.d.year for item in analysis_weather})
    source_by_date = {item.d: item for item in projected_weather}
    if not source_years or not target_years:
        raise NasaDataError("NEX-GDDP-CMIP6 date range is empty")
    out: list[WeatherDay] = []
    for target in analysis_weather:
        year_offset = target.d.year - target_years[0]
        source_year = source_years[year_offset % len(source_years)]
        try:
            source_date = date(source_year, target.d.month, target.d.day)
        except ValueError:
            # A projection calendar without leap day still covers the target's
            # seasonal slot; use February 28 rather than shifting later dates.
            source_date = date(source_year, 2, 28)
        projected = source_by_date.get(source_date)
        if projected is None:
            raise NasaDataError(
                f"NEX-GDDP-CMIP6 does not cover the projected analogue date {source_date.isoformat()}"
            )
        out.append(WeatherDay(
            d=target.d,
            tmax_c=projected.tmax_c,
            tmin_c=projected.tmin_c,
            rh_mean_pct=projected.rh_mean_pct,
            wind_2m_ms=projected.wind_2m_ms,
            solar_rad_mj_m2_day=projected.solar_rad_mj_m2_day,
            rain_mm=projected.rain_mm,
            source=f"{projected.source} (projected analogue year {source_year})",
            provenance=projected.provenance,
        ))
    return tuple(out)
