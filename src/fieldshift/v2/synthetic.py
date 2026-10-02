from __future__ import annotations
import math, random
from datetime import date, timedelta
from .models import Provenance, WeatherDay


def generate_weather(year: int, lat: float, lon: float, elevation_m: float = 20.0, seed: int = 42) -> tuple[WeatherDay, ...]:
    rng = random.Random(seed + int(abs(lat) * 10) + int(abs(lon) * 10))
    out = []
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    prov = Provenance(source="Field Shift synthetic generator", source_type="synthetic", spatial_resolution="point", temporal_resolution="daily", confidence=0.25)
    while d <= end:
        doy = d.timetuple().tm_yday
        seasonal = math.sin(2 * math.pi * (doy - 90) / 365)
        pre = max(0.0, math.sin(2 * math.pi * (doy - 115) / 365))
        wet = max(0.0, math.sin(2 * math.pi * (doy - 150) / 365))
        tmax = 30.0 + 7.2 * seasonal + 1.2 * pre + rng.gauss(0, 1.3)
        tmin = 17.0 + 5.2 * seasonal + rng.gauss(0, 1.0)
        rh = 72 - 18 * pre + 10 * wet + rng.gauss(0, 5)
        rh = max(35, min(98, rh))
        wind = max(0.4, 1.3 + 0.7 * wet + rng.gauss(0, 0.3))
        rad = max(3.0, 16 + 8 * max(0, seasonal) - 5 * wet + rng.gauss(0, 1.6))
        rain_prob = 0.07 + 0.53 * wet
        rain = 0.0 if rng.random() > rain_prob else max(0.0, rng.gammavariate(1.4, 9 + 20 * wet))
        out.append(WeatherDay(d, round(tmax, 2), round(tmin, 2), round(rh, 2), round(wind, 2), round(rad, 2), round(rain, 2), "synthetic", prov))
        d += timedelta(days=1)
    return tuple(out)
