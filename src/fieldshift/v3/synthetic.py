from __future__ import annotations

import math
import random
from datetime import date, timedelta

from .models import Provenance, WeatherDay


def generate_weather(year: int, lat: float, lon: float, elevation_m: float = 20.0, seed: int = 42) -> tuple[WeatherDay, ...]:
    """Stochastic weather generator with year-specific anomalies, dry spells and heat events.

    This remains a synthetic fallback, not a climatological observation source.
    """
    rng = random.Random(seed + year * 1009 + int(abs(lat) * 10) + int(abs(lon) * 10))
    annual_temp_shift = rng.gauss(0, 0.9)
    rainfall_scale = math.exp(rng.gauss(0, 0.10))
    onset_shift = rng.randint(-12, 12)
    heat_events = []
    for _ in range(rng.randint(1, 3)):
        start = rng.randint(120, 310)
        length = rng.randint(3, 9)
        heat_events.append((start, start + length, rng.uniform(2.0, 4.8)))
    dry_events = []
    for _ in range(rng.randint(1, 3)):
        start = rng.randint(40, 320)
        length = rng.randint(5, 16)
        dry_events.append((start, start + length))
    out = []
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    prov = Provenance(source="Field Shift V3 stochastic weather generator", source_type="synthetic", spatial_resolution="point", temporal_resolution="daily", confidence=0.30)
    temp_anom = 0.0
    while d <= end:
        doy = d.timetuple().tm_yday
        seasonal = math.sin(2 * math.pi * (doy - (90 + onset_shift)) / 365)
        pre = max(0.0, math.sin(2 * math.pi * (doy - (115 + onset_shift)) / 365))
        wet = max(0.0, math.sin(2 * math.pi * (doy - (150 + onset_shift)) / 365))
        temp_anom = 0.82 * temp_anom + rng.gauss(0, 0.55)
        tmax = 30.0 + 7.2 * seasonal + 1.2 * pre + annual_temp_shift + temp_anom + rng.gauss(0, 1.2)
        tmin = 17.0 + 5.2 * seasonal + 0.55 * temp_anom + rng.gauss(0, 0.9)
        event_heat = max((delta for a, b, delta in heat_events if a <= doy <= b), default=0.0)
        tmax += event_heat
        tmin += 0.5 * event_heat
        rh = max(35.0, min(98.0, 72 - 18 * pre + 10 * wet - 1.5 * temp_anom + rng.gauss(0, 4.5)))
        wind = max(0.4, 1.3 + 0.7 * wet + rng.gauss(0, 0.3))
        rad = max(3.0, 16 + 8 * max(0, seasonal) - 5 * wet + rng.gauss(0, 1.5))
        rain_prob = max(0.01, min(0.85, (0.07 + 0.53 * wet) * (1.0 / max(rainfall_scale, 0.5))))
        rain = 0.0 if rng.random() > rain_prob else max(0.0, rng.gammavariate(1.3, 9 + 22 * wet) * rainfall_scale)
        if any(a <= doy <= b for a, b in dry_events):
            rain *= 0.08
        out.append(WeatherDay(d, round(tmax, 2), round(tmin, 2), round(rh, 2), round(wind, 2), round(rad, 2), round(rain, 2), "synthetic", prov))
        d += timedelta(days=1)
    return tuple(out)
