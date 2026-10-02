from __future__ import annotations

import csv
import json
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Iterable

from .models import Provenance, RemoteDay, WeatherDay
from .provenance import now_iso

NASA_POWER_BASE = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_PARAMS = "T2M_MAX,T2M_MIN,RH2M,WS2M,ALLSKY_SFC_SW_DWN,PRECTOTCORR"


class NasaDataError(RuntimeError):
    pass


def _http_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "FieldShift-V2/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise NasaDataError(f"NASA data request failed: {exc}") from exc


def power_daily(lat: float, lon: float, start: date, end: date, timeout: int = 30) -> tuple[WeatherDay, ...]:
    query = urllib.parse.urlencode({
        "parameters": POWER_PARAMS,
        "community": "AG",
        "longitude": f"{lon:.6f}",
        "latitude": f"{lat:.6f}",
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
    })
    payload = _http_json(f"{NASA_POWER_BASE}?{query}", timeout=timeout)
    try:
        params = payload["properties"]["parameter"]
    except KeyError as exc:
        raise NasaDataError("unexpected NASA POWER payload") from exc

    dates = sorted(params["T2M_MAX"].keys())
    prov = Provenance(
        source="NASA POWER Daily API",
        source_type="observed/model-derived",
        retrieval_date=now_iso(),
        temporal_resolution="daily",
        spatial_resolution="point",
        citation="https://power.larc.nasa.gov/docs/services/api/temporal/daily/",
        confidence=0.95,
    )
    out = []
    for key in dates:
        y, m, d = int(key[:4]), int(key[4:6]), int(key[6:8])
        def v(name: str) -> float:
            x = params[name][key]
            if x in (None, -999, -999.0):
                raise NasaDataError(f"missing NASA POWER value {name} on {key}")
            return float(x)
        out.append(WeatherDay(
            date(y, m, d), v("T2M_MAX"), v("T2M_MIN"), v("RH2M"), v("WS2M"),
            v("ALLSKY_SFC_SW_DWN"), max(0.0, v("PRECTOTCORR")),
            source="NASA POWER", provenance=prov,
        ))
    return tuple(out)


def power_json_file(path: str | Path) -> tuple[WeatherDay, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    params = payload["properties"]["parameter"]
    dates = sorted(params["T2M_MAX"].keys())
    prov = Provenance(
        source=f"NASA POWER cached file: {Path(path).name}", source_type="observed/model-derived",
        temporal_resolution="daily", spatial_resolution="point",
        citation="https://power.larc.nasa.gov/docs/services/api/temporal/daily/", confidence=0.95,
    )
    out = []
    for key in dates:
        y, m, d = int(key[:4]), int(key[4:6]), int(key[6:8])
        out.append(WeatherDay(date(y, m, d), float(params["T2M_MAX"][key]), float(params["T2M_MIN"][key]),
                              float(params["RH2M"][key]), float(params["WS2M"][key]),
                              float(params["ALLSKY_SFC_SW_DWN"][key]), max(0.0, float(params["PRECTOTCORR"][key])),
                              source="NASA POWER", provenance=prov))
    return tuple(out)


def load_timeseries_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def remote_csv(path: str | Path, source: str, source_type: str = "satellite") -> tuple[RemoteDay, ...]:
    rows = load_timeseries_csv(path)
    out: list[RemoteDay] = []
    prov = Provenance(source=source, source_type=source_type, temporal_resolution="native", citation=None, confidence=0.85)
    for r in rows:
        d = date.fromisoformat(r["date"])
        kw = {k: float(r[k]) for k in ("ndvi", "evi", "ndmi", "smap_surface_m3_m3", "smap_rootzone_m3_m3", "modis_et_mm", "gpm_rain_mm") if r.get(k) not in (None, "", "NA")}
        out.append(RemoteDay(d=d, source=source, provenance=prov, **kw))
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
    out = []
    for r in rows:
        out.append(WeatherDay(
            d=date.fromisoformat(r["date"]), tmax_c=float(r["tmax_c"]), tmin_c=float(r["tmin_c"]),
            rh_mean_pct=float(r.get("rh_mean_pct", 70)), wind_2m_ms=float(r.get("wind_2m_ms", 1.5)),
            solar_rad_mj_m2_day=float(r.get("solar_rad_mj_m2_day", 18)), rain_mm=float(r["rain_mm"]),
            source=f"NEX-GDDP-CMIP6:{scenario_name}", provenance=prov,
        ))
    return tuple(out)
