# -*- coding: utf-8 -*-
"""
tests.test_engine
==================
Run with:  PYTHONPATH=src python3 -m unittest tests.test_engine -v

Deliberately stdlib-only (unittest, not pytest) since this container has no
network access to install anything -- see README "Why no pydantic/pytest".

Test philosophy (blueprint Section 10, "definition of done"): where a value
can be checked against a cited worked example, do that; where it can't
(nobody has the FAO-56 PDF's own numeric worked example memorized reliably
enough to assert to 2 decimal places), test physical sanity -- monotonicity,
sign, plausible magnitude -- instead of a from-memory number dressed up as
ground truth.
"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from fieldshift.engine.models import (CropProfile, DailyWeather, FieldContext,
                                       RotationCandidate, ScoreCard)
from fieldshift.engine.weather import generate_year
from fieldshift.engine.water import reference_et0_mm, kc_on_day, crop_water_requirement
from fieldshift.engine.constraints import filter_feasible, check_calendar_feasibility
from fieldshift.engine.scoring import is_pareto_optimal, CRITERIA
from fieldshift.engine.pipeline import run, load_crop_library, load_region_pack


def _toy_crop(crop_id="toy", duration=90, stage=(10, 20, 40, 20), kc=(0.4, 1.1, 0.5),
              sowing_window=("01-01", "12-01"), **kw):
    defaults = dict(
        display_name=crop_id, family="Testaceae", season="rabi",
        sowing_window=sowing_window, duration_days=duration, kc_ini=kc[0], kc_mid=kc[1],
        kc_end=kc[2], stage_days=stage, root_depth_m=0.5, n_fixing=False,
        residue_return="medium", heat_critical_tmax_c=35, heat_sensitive_stage="mid",
        labour_person_days_per_ha=50, price_bdt_per_kg=30, reference_yield_kg_per_ha=3000,
        prod_cost_bdt_per_ha=40000, min_ph=5.0, max_ph=8.0, tolerates_waterlogging=True,
    )
    defaults.update(kw)
    return CropProfile(crop_id=crop_id, **defaults)


class TestDataContracts(unittest.TestCase):
    def test_stage_days_must_sum_to_duration(self):
        with self.assertRaises(ValueError):
            _toy_crop(duration=100, stage=(10, 20, 40, 20))  # sums to 90, not 100

    def test_cited_crop_needs_sources(self):
        with self.assertRaises(ValueError):
            _toy_crop(review_status="cited", sources=())

    def test_scorecard_rejects_weights_not_summing_to_one(self):
        with self.assertRaises(ValueError):
            ScoreCard(block_id="x", generated_at="now",
                     priorities={"soil_health": 0.5, "water_saving": 0.6},
                     data_freshness={}, options=[], rejected=[],
                     confidence="low", caveats=[])

    def test_field_context_rejects_implausible_ph(self):
        with self.assertRaises(ValueError):
            FieldContext(block_id="x", lat=24.7, lon=90.4, area_ha=0.5,
                        soil_texture="loam", soil_ph=14.0, soil_organic_carbon_pct=1.0,
                        irrigation_reliable=True, irrigation_source="tubewell",
                        land_type="highland")


class TestWaterPhysics(unittest.TestCase):
    def setUp(self):
        self.hot_dry_sunny = DailyWeather(
            d=dt.date(2026, 4, 20), tmax_c=36, tmin_c=26, rh_mean_pct=40,
            wind_2m_ms=2.5, solar_rad_mj_m2_day=26, rain_mm=0)
        self.cool_humid_cloudy = DailyWeather(
            d=dt.date(2026, 1, 10), tmax_c=20, tmin_c=10, rh_mean_pct=85,
            wind_2m_ms=0.8, solar_rad_mj_m2_day=12, rain_mm=0)

    def test_et0_is_positive(self):
        self.assertGreater(reference_et0_mm(self.hot_dry_sunny, 110), 0)
        self.assertGreater(reference_et0_mm(self.cool_humid_cloudy, 10), 0)

    def test_et0_higher_for_hot_dry_sunny_than_cool_humid_cloudy(self):
        hot = reference_et0_mm(self.hot_dry_sunny, 110)
        cool = reference_et0_mm(self.cool_humid_cloudy, 10)
        self.assertGreater(hot, cool)

    def test_et0_plausible_magnitude_across_synthetic_year(self):
        # FAO-56's own general guidance: roughly 1 mm/day cool humid winter up
        # to 10-13 mm/day hot dry summer: https://www.fao.org/3/x0490e/x0490e00.htm
        daily = generate_year(2026)
        values = [reference_et0_mm(w, w.d.timetuple().tm_yday) for w in daily]
        self.assertGreater(min(values), 0.5)
        self.assertLess(max(values), 11.0)

    def test_et0_monotonic_in_temperature(self):
        base = self.hot_dry_sunny
        hotter = DailyWeather(d=base.d, tmax_c=base.tmax_c + 4, tmin_c=base.tmin_c + 4,
                              rh_mean_pct=base.rh_mean_pct, wind_2m_ms=base.wind_2m_ms,
                              solar_rad_mj_m2_day=base.solar_rad_mj_m2_day, rain_mm=0)
        self.assertGreater(reference_et0_mm(hotter, 110), reference_et0_mm(base, 110))

    def test_kc_curve_boundaries(self):
        crop = _toy_crop(duration=90, stage=(10, 20, 40, 20), kc=(0.4, 1.1, 0.5))
        self.assertAlmostEqual(kc_on_day(crop, 0), 0.4)          # start of initial stage
        self.assertAlmostEqual(kc_on_day(crop, 9), 0.4)          # end of initial stage
        self.assertAlmostEqual(kc_on_day(crop, 30), 1.1)         # start of mid stage
        self.assertAlmostEqual(kc_on_day(crop, 69), 1.1)         # end of mid stage
        self.assertAlmostEqual(kc_on_day(crop, 89), 0.5, places=1)  # last day ~ kc_end
        self.assertEqual(kc_on_day(crop, 90), 0.0)               # past the crop's life

    def test_crop_water_requirement_runs_and_is_nonnegative(self):
        crop = _toy_crop()
        daily = generate_year(2026)
        result = crop_water_requirement(crop, daily, start_index=0)
        self.assertGreaterEqual(result["irrigation_requirement_mm"], 0)
        self.assertGreater(result["etc_total_mm"], 0)

    def test_crop_water_requirement_raises_if_series_too_short(self):
        crop = _toy_crop(duration=90)
        daily = generate_year(2026)
        with self.assertRaises(IndexError):
            crop_water_requirement(crop, daily, start_index=len(daily) - 5)


class TestConstraints(unittest.TestCase):
    def test_calendar_rejects_impossible_back_to_back_crops(self):
        # Two 100-day crops both confined to the SAME narrow 5-day window ->
        # the second one cannot possibly fit after the first one's harvest.
        crops = {
            "a": _toy_crop("a", duration=100, stage=(10, 20, 50, 20),
                          sowing_window=("01-01", "01-05")),
            "b": _toy_crop("b", duration=100, stage=(10, 20, 50, 20),
                          sowing_window=("01-01", "01-05")),
        }
        rotation = RotationCandidate("bad", "impossible back-to-back", ("a", "b"))
        result = check_calendar_feasibility(rotation, crops, min_turnaround_days=10, base_year=2026)
        self.assertFalse(result.feasible)
        self.assertIn("annual rotation cycle", result.reason)

    def test_calendar_accepts_boro_then_aman_across_year_boundary(self):
        # Regression test for the bug found while building this: Boro rice
        # (sown mid-December, ~145 days) finishes the following May, so
        # Aman's July-August window must resolve to the FOLLOWING year, not
        # the rotation's nominal start year.
        crops = load_crop_library()
        rotation = RotationCandidate("R1", "boro then aman", ("boro_rice", "aman_rice"))
        result = check_calendar_feasibility(rotation, crops, min_turnaround_days=10, base_year=2026)
        self.assertTrue(result.feasible, msg=result.reason)
        self.assertEqual(result.schedule[0].sow_date.year, 2026)
        self.assertEqual(result.schedule[1].sow_date.year, 2027)
        self.assertGreater(result.schedule[1].sow_date, result.schedule[0].harvest_date)

    def test_soil_ph_constraint_rejects_incompatible_field(self):
        crops = {"acidic_only": _toy_crop("acidic_only", min_ph=4.0, max_ph=5.5)}
        field = FieldContext(block_id="x", lat=24.7, lon=90.4, area_ha=0.4,
                            soil_texture="loam", soil_ph=7.2, soil_organic_carbon_pct=1.0,
                            irrigation_reliable=True, irrigation_source="tubewell",
                            land_type="highland")
        rotation = RotationCandidate("r", "acidic-only crop on neutral field", ("acidic_only",))
        accepted, rejected = filter_feasible([rotation], crops, field, min_turnaround_days=10,
                                             base_year=2026)
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("pH", rejected[0][1])


class TestScoring(unittest.TestCase):
    def test_pareto_front_known_dominance(self):
        # A dominates B on every criterion -> B is NOT Pareto-optimal.
        # C trades off against A -> both A and C ARE Pareto-optimal.
        matrix = [
            {"soil_health": 0.9, "water_saving": 0.8, "income": 0.7, "risk": 0.9, "labour": 0.8},  # A
            {"soil_health": 0.5, "water_saving": 0.4, "income": 0.3, "risk": 0.5, "labour": 0.4},  # B (dominated by A)
            {"soil_health": 0.3, "water_saving": 0.9, "income": 0.9, "risk": 0.4, "labour": 0.5},  # C (trades off vs A)
        ]
        self.assertTrue(is_pareto_optimal(0, matrix))
        self.assertFalse(is_pareto_optimal(1, matrix))
        self.assertTrue(is_pareto_optimal(2, matrix))


class TestFullPipeline(unittest.TestCase):
    def test_runs_and_produces_ranked_options(self):
        priorities = {"soil_health": 0.3, "water_saving": 0.25, "income": 0.2,
                     "risk": 0.15, "labour": 0.1}
        sc = run(priorities)
        self.assertGreater(len(sc.options), 0)
        scores = [o.mean_score for o in sc.options]
        self.assertEqual(scores, sorted(scores, reverse=True))  # best-first

    def test_all_eight_candidates_are_feasible_for_the_default_region_pack(self):
        # Regression test: before the calendar-rollover fix, every multi-crop
        # rotation (6 of the 8 candidates) was wrongly rejected.
        priorities = {"soil_health": 0.2, "water_saving": 0.2, "income": 0.2,
                     "risk": 0.2, "labour": 0.2}
        sc = run(priorities)
        accepted_ids = {o.rotation.rotation_id for o in sc.options}
        region = load_region_pack()
        all_ids = {r["rotation_id"] for r in region["candidate_rotations"]}
        self.assertEqual(accepted_ids, all_ids, msg=f"rejected: {sc.rejected}")

    def test_conventional_double_rice_is_not_silently_hidden(self):
        # R1 (Boro->Aman) is today's common practice. The tool should show it
        # (not filter it out) even where it scores poorly, so a farmer can
        # see the comparison rather than only ever seeing the model's favourite.
        sc = run({"soil_health": 0.3, "water_saving": 0.25, "income": 0.2,
                 "risk": 0.15, "labour": 0.1})
        ids = [o.rotation.rotation_id for o in sc.options]
        self.assertIn("R1", ids)

    def test_caveats_are_present_and_nonempty(self):
        sc = run({"soil_health": 0.2, "water_saving": 0.2, "income": 0.2,
                 "risk": 0.2, "labour": 0.2})
        self.assertGreater(len(sc.caveats), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
