from __future__ import annotations
import random
from .models import CropV2, FieldV2


def rotation_economics(crops: tuple[CropV2, ...], yield_factors: list[dict[str, float]], field: FieldV2) -> dict[str, float]:
    revenue = 0.0
    costs = 0.0
    labour = 0.0
    yields = []
    for crop, yf in zip(crops, yield_factors):
        y = yf["climate_adjusted_yield_kg_ha"]
        revenue += y * crop.price_bdt_kg
        costs += crop.cost_bdt_ha
        labour += crop.labour_person_days_ha
        yields.append(y)
    net = revenue - costs
    roi = net / max(costs, 1.0)
    return {
        "gross_revenue_bdt_ha": revenue,
        "total_cost_bdt_ha": costs,
        "net_return_bdt_ha": net,
        "roi": roi,
        "labour_total_person_days_ha": labour,
        "yield_total_kg_ha": sum(yields),
        "income_volatility_proxy": 1 - min(1.0, roi / 5.0),
    }


def draw_economic_inputs(crops: tuple[CropV2, ...], rng: random.Random, price_cv: float = 0.12, yield_cv: float = 0.10) -> tuple[CropV2, ...]:
    out = []
    from dataclasses import replace
    for c in crops:
        p = max(0.0, rng.gauss(c.price_bdt_kg, c.price_bdt_kg * price_cv))
        y = max(0.0, rng.gauss(c.yield_kg_ha, c.yield_kg_ha * yield_cv))
        out.append(replace(c, price_bdt_kg=p, yield_kg_ha=y))
    return tuple(out)
