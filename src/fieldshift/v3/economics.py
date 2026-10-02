from __future__ import annotations

import math
import random
from dataclasses import replace

from .models import CropV2, FieldV2


def rotation_economics(crops: tuple[CropV2, ...], yield_factors: list[dict[str, float]], field: FieldV2, *, price_yield_rho: float = -0.20, cost_inflation: float = 0.0) -> dict[str, float]:
    revenue = 0.0
    costs = 0.0
    labour = 0.0
    yields: list[float] = []
    for crop, yf in zip(crops, yield_factors):
        y = yf["climate_adjusted_yield_kg_ha"]
        revenue += y * crop.price_bdt_kg
        costs += crop.cost_bdt_ha * (1.0 + cost_inflation)
        labour += crop.labour_person_days_ha
        yields.append(y)
    net = revenue - costs
    roi = net / max(costs, 1.0)
    revenue_shares = []
    for crop, yf in zip(crops, yield_factors):
        crop_revenue = max(0.0, yf["climate_adjusted_yield_kg_ha"] * crop.price_bdt_kg)
        revenue_shares.append(crop_revenue / max(revenue, 1e-9))
    weighted_var = 0.0
    for share, crop in zip(revenue_shares, crops):
        pcv = crop.price_cv
        ycv = crop.yield_cv
        revenue_cv = math.sqrt(max(0.0, pcv * pcv + ycv * ycv + 2 * price_yield_rho * pcv * ycv))
        weighted_var += (share * revenue_cv) ** 2
    income_cv = math.sqrt(max(0.0, weighted_var))
    return {
        "gross_revenue_bdt_ha": revenue,
        "total_cost_bdt_ha": costs,
        "net_return_bdt_ha": net,
        "roi": roi,
        "labour_total_person_days_ha": labour,
        "yield_total_kg_ha": sum(yields),
        "income_volatility_proxy": income_cv,
        "price_yield_tradeoff_rho": price_yield_rho,
    }


def draw_crop_parameters(
    crops: tuple[CropV2, ...],
    rng: random.Random,
    *,
    price_cv: float | None = None,
    yield_cv: float | None = None,
    kc_cv: float | None = None,
    root_depth_cv: float | None = None,
    cost_inflation_sd: float = 0.04,
    price_yield_rho: float = -0.20,
) -> tuple[CropV2, ...]:
    """Sample uncertain inputs, including correlated price/yield shocks and agronomic coefficients."""
    # Cholesky for a 2x2 correlated normal pair.
    z1 = rng.gauss(0.0, 1.0)
    z2 = rng.gauss(0.0, 1.0)
    rho = max(-0.95, min(0.95, price_yield_rho))
    z_yield_common = z1
    z_price_common = rho * z1 + math.sqrt(1.0 - rho * rho) * z2
    cost_inflation = rng.gauss(0.0, cost_inflation_sd)
    out = []
    for c in crops:
        pcv = price_cv if price_cv is not None else c.price_cv
        ycv = yield_cv if yield_cv is not None else c.yield_cv
        kcv = kc_cv if kc_cv is not None else c.kc_cv
        rcv = root_depth_cv if root_depth_cv is not None else c.root_depth_cv
        price = max(0.01, c.price_bdt_kg * math.exp(pcv * z_price_common - 0.5 * pcv * pcv))
        base_y = max(1.0, c.yield_kg_ha * math.exp(ycv * z_yield_common - 0.5 * ycv * ycv))
        kc_mult = max(0.85, min(1.15, 1.0 + rng.gauss(0, kcv)))
        root_mult = max(0.85, min(1.15, 1.0 + rng.gauss(0, rcv)))
        out.append(replace(
            c,
            price_bdt_kg=price,
            yield_kg_ha=base_y,
            cost_bdt_ha=max(0.0, c.cost_bdt_ha * math.exp(cost_inflation)),
            kc_ini=max(0.05, c.kc_ini * kc_mult),
            kc_mid=max(0.05, c.kc_mid * kc_mult),
            kc_end=max(0.05, c.kc_end * kc_mult),
            root_depth_m=max(0.10, c.root_depth_m * root_mult),
        ))
    return tuple(out)
