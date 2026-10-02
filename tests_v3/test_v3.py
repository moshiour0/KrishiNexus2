from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fieldshift.v3.agronomy import nutrient_stock_kg_ha, soil_mass_kg_ha
from fieldshift.v3.indicators import compute_rotation_indicators
from fieldshift.v3.models import (
    CropV2,
    FarmerContext,
    FieldV2,
    RemoteDay,
    Rotation,
    Scenario,
    SoilProfile,
    WeatherDay,
)
from fieldshift.v3.nasa import align_nex_weather_to_analysis, power_daily
from fieldshift.v3.pipeline import DEFAULT_WEIGHTS, build_field, load_config, run_v3
from fieldshift.v3.scoring import dimension_scores, rank_options, validate_weights
from fieldshift.v3.water import et0, simulate_crop_water


class TestV3Scoring(unittest.TestCase):
    def test_absolute_scale_is_candidate_set_invariant(self):
        defs = {"d": {"features": {"x": {"weight": 1.0, "direction": "higher", "scale": [0, 100]}}}}
        base = dimension_scores([{"x": 20}, {"x": 40}], ("d",), defs)["d"]
        extended = dimension_scores([{"x": 20}, {"x": 40}, {"x": 100}], ("d",), defs)["d"]
        self.assertEqual(base, extended[:2])

    def test_missing_remote_feature_is_not_neutral_injected(self):
        defs = {"d": {"features": {"x": {"weight": 1.0, "direction": "higher", "scale": [0, 1]}}}}
        out = dimension_scores([{}, {"x": 1.0}], ("d",), defs)["d"]
        self.assertEqual(out[0], 0.5)
        self.assertEqual(out[1], 1.0)
        # The neutral score above is only the dimension fallback when every feature is unavailable;
        # no raw indicator value is fabricated into the evidence bundle.

    def test_rank_p90_uses_rank_samples_not_score_samples(self):
        dims = {"baseline": {"d": [0.9, 0.4, 0.1]}}
        result = rank_options(["a", "b", "c"], dims, {"d": 1.0}, n_weight_samples=60, uncertainty_samples={"a":[0.2,0.3,0.4],"b":[0.2,0.3,0.4],"c":[0.2,0.3,0.4]})
        for x in result["results"].values():
            self.assertGreaterEqual(x["rank_p90"], 1.0)
            self.assertLessEqual(x["rank_p90"], 3.0)
            self.assertEqual(x["rank_p90"], x["rank_mean"])
            self.assertGreaterEqual(x["score_p90"], x["score_p50"])

    def test_weights_sum(self):
        validate_weights(DEFAULT_WEIGHTS, tuple(DEFAULT_WEIGHTS))
        self.assertAlmostEqual(sum(DEFAULT_WEIGHTS.values()), 1.0)


class TestV3Physics(unittest.TestCase):
    def setUp(self):
        self.crop = CropV2(
            "x", "X", "Fabaceae", ("rabi",), ("01-01", "01-31"), 30, (5, 8, 12, 5),
            0.5, 1.0, 0.7, 0.5, ("flower", 10, 20), 35, 0.5, 0.8, 0.5,
            True, 0.8, 1000, 40, 1000, 10, 40, 10, 20, 0.8, (5.5, 7.5),
        )
        self.soil = SoilProfile(ph=6.4, soc_pct=1.1, total_n_mgkg=800, available_p_mgkg=12, exchangeable_k_mgkg=140,
                                bulk_density_g_cm3=1.38, soil_depth_m=1.2, field_capacity_v_v=0.31,
                                wilting_point_v_v=0.16, sand_pct=20, silt_pct=48, clay_pct=32, drainage_class="medium")
        self.field = FieldV2("f", 24.75, 90.41, 1.0, soil=self.soil, farmer=FarmerContext(priorities={"d":1.0}))
        start=date(2026,1,1)
        self.weather=tuple(WeatherDay(start+timedelta(days=i),30,20,60,2,20,5) for i in range(30))

    def test_water_mass_balance(self):
        r = simulate_crop_water(self.crop, self.weather[0].d, self.weather, self.field)
        self.assertLess(abs(r["water_balance_error_mm"]), 1e-6)
        self.assertGreaterEqual(r["irrigation_loss_mm"], 0)
        self.assertGreaterEqual(r["runoff_mm"], 0)
        self.assertAlmostEqual(r["irrigation_mm"] - r["irrigation_effective_mm"], r["irrigation_loss_mm"], places=7)

    def test_nutrient_units_use_depth_and_bulk_density(self):
        expected = 800 * soil_mass_kg_ha(self.field) / 1_000_000 * 0.02
        self.assertAlmostEqual(nutrient_stock_kg_ha(800, self.field, 0.02), expected)
        # 800 mg/kg x 1.38 g/cm3 x 1.2 m = 16,560 kg soil/ha per mg/kg; 2% mineralization.
        self.assertGreater(expected, 100)

    def test_fao56_golden_example_close_to_official_result(self):
        # FAO-56 Chapter 4 April example reports ETo ~5.72 mm/day for 13.73N, z=2m,
        # Tmax=34.8C, Tmin=25.6C, Rs=22.65 MJ/m2/day, u2=2m/s, ea=2.85 kPa.
        w=WeatherDay(date(2026,4,15),34.8,25.6,64.48,2,22.65,0)
        value=et0(w,13.73,2)
        self.assertAlmostEqual(value,5.72,delta=0.08)


class TestV3NASAAndLineage(unittest.TestCase):
    def test_nex_cmip6_monthly_delta_units_and_analogue_adjustment(self):
        from fieldshift.v3.gee import apply_monthly_deltas, monthly_climate_deltas

        historical = {
            month: {"tasmax": 300.0, "tasmin": 290.0, "hurs": 65.0, "pr": 0.00001, "rsds": 200.0, "sfcWind": 2.0}
            for month in range(1, 13)
        }
        future = {
            month: {"tasmax": 302.0, "tasmin": 291.0, "hurs": 60.0, "pr": 0.00002, "rsds": 220.0, "sfcWind": 2.4}
            for month in range(1, 13)
        }
        deltas = monthly_climate_deltas(historical, future)
        self.assertEqual(deltas[1]["tasmax_delta_c"], 2.0)
        self.assertEqual(deltas[1]["hurs_delta_pct"], -5.0)
        self.assertEqual(deltas[1]["precip_ratio"], 2.0)
        source = WeatherDay(date(2026, 1, 1), 30, 20, 60, 2, 20, 5)
        adjusted = apply_monthly_deltas((source,), deltas)[0]
        self.assertEqual((adjusted.tmax_c, adjusted.tmin_c), (32.0, 21.0))
        self.assertEqual(adjusted.rh_mean_pct, 55.0)
        self.assertEqual(adjusted.rain_mm, 10.0)
        self.assertEqual(adjusted.solar_rad_mj_m2_day, 22.0)
        self.assertEqual(adjusted.wind_2m_ms, 2.4)

    def test_nex_csv_projection_years_align_to_plan_dates(self):
        projected = tuple(
            WeatherDay(date(year, 1, 1), float(year - 2040), 18, 70, 1, 19, 4, "NEX", None)
            for year in (2041, 2042, 2043)
        )
        analysis = tuple(
            WeatherDay(date(year, 1, 1), 30, 20, 60, 2, 20, 5)
            for year in (2026, 2027, 2028)
        )
        aligned = align_nex_weather_to_analysis(projected, analysis)
        self.assertEqual([item.d for item in aligned], [item.d for item in analysis])
        self.assertEqual([item.tmax_c for item in aligned], [1.0, 2.0, 3.0])

    def test_gee_nex_connector_stays_explicitly_not_configured_without_secrets(self):
        from fieldshift.v3.gee import nex_gddp_monthly_deltas

        with tempfile.TemporaryDirectory() as cache_dir, patch.dict(
            os.environ,
            {"FIELD_SHIFT_GEE_PROJECT": "", "FIELD_SHIFT_GEE_SERVICE_ACCOUNT_JSON": ""},
        ):
            result = nex_gddp_monthly_deltas(24.75, 90.41, "ssp245", cache_dir)
        self.assertEqual(result.status, "not_configured")
        self.assertIsNone(result.monthly)
        self.assertNotIn("private_key", result.error or "")

    def test_appeears_point_csv_uses_provider_scaled_values_and_normalizes_modis_et(self):
        from fieldshift.v3.appeears import LayerSelection, _records_from_csv_files
        selections = (
            LayerSelection("smap", "NASA SMAP", "SPL4SMGP.008", "sm_rootzone", "smap_rootzone_m3_m3", "9 km", "3 hourly"),
            LayerSelection("modis_et", "NASA MODIS MOD16", "MOD16A2GF.061", "ET_500m", "modis_et_mm", "500m", "8 day"),
            LayerSelection("modis_et", "NASA MODIS MOD16", "MOD16A2GF.061", "ET_QC_500m", "modis_et_qc", "500m", "8 day"),
            LayerSelection("hls_vi", "NASA HLS", "HLSL30_VI.002", "NDVI", "ndvi", "30m", "daily"),
        )
        csv_text = (
            "Date,Latitude,Longitude,SPL4SMGP_008_sm_rootzone,MOD16A2GF_061_ET_500m,MOD16A2GF_061_ET_QC_500m,HLSL30_VI_002_NDVI\n"
            "2026-06-01,23.71,90.41,0.31,16.0,0,0.64\n"
        )
        rows = _records_from_csv_files(
            [("field-MOD16A2GF-061-results.csv", csv_text.encode())], selections,
            "2026-10-01T00:00:00+00:00", date(2026, 1, 1), date(2026, 12, 31),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].smap_rootzone_m3_m3, 0.31)
        self.assertEqual(rows[0].modis_et_mm, 2.0)
        self.assertEqual(rows[0].modis_et_period_days, 8)
        self.assertEqual(rows[0].ndvi, 0.64)

    def test_appeears_requires_modis_qc_and_filters_bad_hls_pixels(self):
        from fieldshift.v3.appeears import LayerSelection, _records_from_csv_files
        selections = (
            LayerSelection("modis_et", "NASA MODIS MOD16", "MOD16A2GF.061", "ET_500m", "modis_et_mm", "500m", "8 day"),
            LayerSelection("modis_et", "NASA MODIS MOD16", "MOD16A2GF.061", "ET_QC_500m", "modis_et_qc", "500m", "8 day"),
            LayerSelection("hls_vi", "NASA HLS", "HLSL30_VI.002", "NDVI", "ndvi", "30m", "daily"),
            LayerSelection("hls_vi", "NASA HLS", "HLSL30_VI.002", "QA", "hls_qa", "30m", "daily"),
        )
        csv_text = (
            "Date,MOD16A2GF_061_ET_500m,MOD16A2GF_061_ET_QC_500m,HLSL30_VI_002_NDVI,HLSL30_VI_002_QA\n"
            "2026-06-01,16,0,0.64,0\n"
            "2026-06-02,24,1,0.71,0\n"
            "2026-06-03,32,0,0.77,2\n"
        )
        rows = _records_from_csv_files(
            [("field-MOD16A2GF-061-results.csv", csv_text.encode())], selections,
            "2026-10-01T00:00:00+00:00", date(2026, 1, 1), date(2026, 12, 31),
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].modis_et_mm, 2.0)
        self.assertEqual(rows[0].ndvi, 0.64)
        self.assertIsNone(rows[1].modis_et_mm)  # MODLAND_QC 1 is not retained.
        self.assertEqual(rows[1].ndvi, 0.71)
        self.assertEqual(rows[2].modis_et_mm, 4.0)
        self.assertIsNone(rows[2].ndvi)  # QA bit 1 is cloud.

    def test_appeears_l3_smap_uses_only_recommended_quality_flags(self):
        from fieldshift.v3.appeears import LayerSelection, _records_from_csv_files
        selections = (
            LayerSelection("smap", "NASA SMAP", "SPL3SMP_E.006", "soil_moisture", "smap_surface_m3_m3", "9 km", "daily"),
            LayerSelection("smap", "NASA SMAP", "SPL3SMP_E.006", "retrieval_qual_flag", "smap_qa", "9 km", "daily"),
        )
        csv_text = (
            "Date,SPL3SMP_E_006_soil_moisture,SPL3SMP_E_006_retrieval_qual_flag\n"
            "2026-06-01,0.25,0\n"
            "2026-06-02,0.31,1\n"
            "2026-06-03,0.29,8\n"
        )
        rows = _records_from_csv_files(
            [("field-SPL3SMP-E-006-results.csv", csv_text.encode())], selections,
            "2026-10-01T00:00:00+00:00", date(2026, 1, 1), date(2026, 12, 31),
        )
        self.assertEqual([row.d for row in rows], [date(2026, 6, 1), date(2026, 6, 3)])
        self.assertEqual([row.smap_surface_m3_m3 for row in rows], [0.25, 0.29])

    def test_appeears_deduplicates_task_after_serverless_cache_loss(self):
        from fieldshift.v3.appeears import LayerSelection, _find_recent_task
        task = {"task_id": "existing-123", "task_name": "fieldshift-test", "status": "processing"}
        selections = (LayerSelection("smap", "NASA SMAP", "SPL4SMGP.008", "sm_rootzone", "smap_rootzone_m3_m3", "9 km", "3 hourly"),)
        with patch("fieldshift.v3.appeears._safe_json_request", return_value=[task]) as request:
            found = _find_recent_task("token", "fieldshift-test", selections, timeout=10)
        self.assertEqual(found, task)
        request.assert_called_once_with(
            "task?task_type=point&limit=100&offset=0", token="token", timeout=10,
        )

    def test_appeears_status_keeps_applied_qa_after_sampling(self):
        from fieldshift.v3 import appeears
        selections = (
            appeears.LayerSelection("modis_et", "NASA MODIS MOD16", "MOD16A2GF.061", "ET_500m", "modis_et_mm", "500m", "8 day"),
            appeears.LayerSelection("modis_et", "NASA MODIS MOD16", "MOD16A2GF.061", "ET_QC_500m", "modis_et_qc", "500m", "8 day"),
        )

        def api_request(path, **kwargs):
            if path == "login":
                return {"token": "short-lived-test-token"}
            if path.startswith("task?"):
                return []
            if path == "task" and kwargs.get("method") == "POST":
                return {"task_id": "task-123"}
            if path == "task/task-123":
                return {"task_id": "task-123", "status": "done"}
            if path == "bundle/task-123":
                return {"files": [{"file_type": "csv", "file_id": "file-1", "file_name": "field-MOD16A2GF-061-results.csv"}]}
            raise AssertionError(f"Unexpected AppEEARS request: {path}")

        csv_bytes = (
            b"Date,MOD16A2GF_061_ET_500m,MOD16A2GF_061_ET_QC_500m\n"
            b"2026-06-01,16,0\n"
        )
        with (
            tempfile.TemporaryDirectory() as cache_dir,
            patch.dict(os.environ, {"FIELD_SHIFT_APPEEARS_USER": "test", "FIELD_SHIFT_APPEEARS_PASSWORD": "test"}),
            patch.object(appeears, "discover_layers", return_value=selections),
            patch.object(appeears, "_safe_json_request", side_effect=api_request),
            patch.object(appeears, "_download", return_value=csv_bytes),
        ):
            result = appeears.appeears_point_timeseries(
                24.75, 90.41, date(2026, 1, 1), date(2026, 9, 18),
                cache_dir=cache_dir, max_wait_seconds=0,
            )
        modis = next(row for row in result.datasets if row["name"] == "NASA MODIS MOD16")
        self.assertEqual(modis["quality_status"], "applied")
        self.assertIn("MODLAND_QC=0", modis["quality_note"])
        self.assertEqual(result.remote[0].modis_et_mm, 2.0)

    def test_modis_known_fill_values_are_rejected(self):
        from fieldshift.v3.appeears import LayerSelection, _records_from_csv_files
        selections = (
            LayerSelection("modis_et", "NASA MODIS MOD16", "MOD16A2GF.061", "ET_500m", "modis_et_mm", "500m", "8 day"),
            LayerSelection("modis_et", "NASA MODIS MOD16", "MOD16A2GF.061", "ET_QC_500m", "modis_et_qc", "500m", "8 day"),
        )
        csv_text = (
            "Date,MOD16A2GF_061_ET_500m,MOD16A2GF_061_ET_QC_500m\n"
            "2026-06-01,32766,0\n"
        )
        rows = _records_from_csv_files(
            [("field-MOD16A2GF-061-results.csv", csv_text.encode())], selections,
            "2026-10-01T00:00:00+00:00", date(2026, 1, 1), date(2026, 12, 31),
        )
        self.assertEqual(rows, ())

    def test_manual_modis_csv_drops_rows_without_good_quality_flags(self):
        from fieldshift.v3.nasa import load_modis_et_csv
        with tempfile.TemporaryDirectory() as temp_dir:
            path=Path(temp_dir)/'modis_et.csv'
            path.write_text(
                'date,modis_et_mm,modis_et_qc,modis_et_period_days\n'
                '2026-06-01,2.0,0,8\n'
                '2026-06-09,3.0,2,8\n'
                '2026-06-17,4.0,,8\n',
                encoding='utf-8',
            )
            rows=load_modis_et_csv(path)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].modis_et_mm,2.0)
        self.assertEqual(rows[0].modis_et_period_days,8)

    def test_appeears_missing_credentials_do_not_make_network_calls(self):
        from fieldshift.v3 import appeears
        with (
            tempfile.TemporaryDirectory() as cache_dir,
            patch.dict(os.environ, {
                "FIELD_SHIFT_APPEEARS_USER": "", "FIELD_SHIFT_APPEEARS_PASSWORD": "",
            }),
            patch.object(appeears, "_safe_json_request", side_effect=AssertionError("network should not be called")),
        ):
            result = appeears.appeears_point_timeseries(
                23.71, 90.41, date(2026, 1, 1), date(2026, 9, 1), cache_dir=cache_dir,
            )
        self.assertFalse(result.remote)
        self.assertEqual({x["status"] for x in result.datasets}, {"not_configured"})

    def test_power_single_missing_value_is_interpolated(self):
        from fieldshift.v3 import nasa
        old=nasa._http_json
        try:
            nasa._http_json=lambda url,timeout=30,retries=3:{"properties":{"parameter":{
                "T2M_MAX":{"20260101":25,"20260102":-999,"20260103":27},
                "T2M_MIN":{"20260101":12,"20260102":13,"20260103":14},
                "RH2M":{"20260101":70,"20260102":71,"20260103":72},
                "WS2M":{"20260101":1.5,"20260102":1.6,"20260103":1.7},
                "ALLSKY_SFC_SW_DWN":{"20260101":18,"20260102":17,"20260103":16},
                "PRECTOTCORR":{"20260101":2,"20260102":3,"20260103":4}}}}
            out=power_daily(24.75,90.41,date(2026,1,1),date(2026,1,3))
            self.assertEqual(out[1].tmax_c,26.0)
            self.assertIn('imputed',out[1].source)
        finally:
            nasa._http_json=old

    def test_power_uses_marked_stale_cache_if_live_service_fails(self):
        from fieldshift.v3 import nasa
        values = {
            "T2M_MAX": {"20260101": 25, "20260102": 26},
            "T2M_MIN": {"20260101": 12, "20260102": 13},
            "RH2M": {"20260101": 70, "20260102": 71},
            "WS2M": {"20260101": 1.5, "20260102": 1.6},
            "ALLSKY_SFC_SW_DWN": {"20260101": 18, "20260102": 17},
            "PRECTOTCORR": {"20260101": 2, "20260102": 3},
        }
        payload = {"properties": {"parameter": values}}
        with tempfile.TemporaryDirectory() as cache_dir:
            with patch.object(nasa, "_http_json", return_value=payload):
                nasa.power_daily(24.75, 90.41, date(2026, 1, 1), date(2026, 1, 2), cache_dir=cache_dir)
            cache_path = next(Path(cache_dir).glob("power_*.json"))
            old_time = time.time() - 86400
            os.utime(cache_path, (old_time, old_time))
            with (
                patch.dict(os.environ, {"FIELD_SHIFT_POWER_CACHE_TTL_SECONDS": "60"}),
                patch.object(nasa, "_http_json", side_effect=nasa.NasaDataError("offline")),
            ):
                out = nasa.power_daily(24.75, 90.41, date(2026, 1, 1), date(2026, 1, 2), cache_dir=cache_dir)
        self.assertIn("stale-cache", out[0].source)
        self.assertLess(out[0].provenance.confidence, 0.96)

    def test_non_pilot_coordinates_do_not_inherit_mymensingh_soil(self):
        field = build_field(load_config(), DEFAULT_WEIGHTS, {
            "lat": 23.71, "lon": 90.41, "area_ha": 0.4, "soil": {}, "farmer": {},
        })
        self.assertIsNone(field.soil.ph)
        self.assertIsNone(field.soil.soc_pct)

    def test_bangladesh_soil_sample_import_uses_nearest_within_radius_only(self):
        from fieldshift.v3.pipeline import _nearest_soil_point
        with tempfile.TemporaryDirectory() as temp_dir:
            path=Path(temp_dir)/'soil_points.csv'
            path.write_text(
                'sample_id,latitude,longitude,district,upazila,sample_date,ph,soc_pct,source_organization,source_url,license\n'
                'BD-TEST-1,24.75,90.41,Mymensingh,Trishal,2026-03-01,6.2,1.1,BAU,https://example.org/data,CC-BY-4.0\n',
                encoding='utf-8',
            )
            result=_nearest_soil_point(path,24.75,90.41,1.0)
            self.assertIsNotNone(result)
            soil,metadata=result
            self.assertEqual(soil.ph,6.2)
            self.assertEqual(metadata['district'],'Mymensingh')
            self.assertIn('BAU',soil.provenance['ph'].source)
            self.assertIsNone(_nearest_soil_point(path,25.0,91.0,1.0))

    def test_no_remote_defaults_in_indicator_values(self):
        crop=self._crop()
        field=self._field()
        start=date(2026,1,1)
        weather=tuple(WeatherDay(start+timedelta(days=i),30,20,60,2,20,5) for i in range(40))
        scenario=Scenario('baseline','x',weather,())
        rotation=Rotation('x',('x',),'X')
        from fieldshift.v3.rotation import schedule
        sch=schedule(rotation,{'x':crop},2026,0,60)
        values,_=compute_rotation_indicators(rotation,sch,{'x':crop},scenario,field)
        self.assertNotIn('mean_hls_ndvi',values)
        self.assertNotIn('mean_hls_ndmi',values)

    def test_modis_eight_day_composite_overlaps_crop_even_when_start_date_does_not(self):
        crop=self._crop()
        field=self._field()
        start=date(2026,1,1)
        weather=tuple(WeatherDay(start+timedelta(days=i),30,20,60,2,20,5) for i in range(40))
        observation=RemoteDay(start-timedelta(days=1),modis_et_mm=2.0,modis_et_period_days=8,source='NASA MODIS MOD16')
        scenario=Scenario('baseline','x',weather,(observation,))
        rotation=Rotation('x',('x',),'X')
        from fieldshift.v3.rotation import schedule
        sch=schedule(rotation,{'x':crop},2026,0,60)
        values,_=compute_rotation_indicators(rotation,sch,{'x':crop},scenario,field)
        self.assertEqual(values['modis_observation_count'],1.0)
        self.assertEqual(values['modis_et_mean_mm'],2.0)
        self.assertGreater(values['remote_observation_coverage_fraction'],0.0)

    def _crop(self):
        return CropV2('x','X','Fabaceae',('rabi',),('01-01','01-31'),30,(5,8,12,5),0.5,1,0.7,0.5,('flower',10,20),35,0.5,0.8,0.5,True,0.8,1000,40,1000,10,40,10,20,0.8,(5.5,7.5))
    def _field(self):
        soil=SoilProfile(ph=6.4,soc_pct=1.1,total_n_mgkg=800,available_p_mgkg=12,exchangeable_k_mgkg=140,bulk_density_g_cm3=1.38,soil_depth_m=1.2,field_capacity_v_v=0.31,wilting_point_v_v=0.16,sand_pct=20,silt_pct=48,clay_pct=32,drainage_class='medium')
        return FieldV2('f',24.75,90.41,1,soil=soil,farmer=FarmerContext(priorities={'soil_health':1.0}))


class TestV3Engine(unittest.TestCase):
    def test_full_engine_and_validation(self):
        run=run_v3(n_weight_samples=40,n_uncertainty_samples=16)
        self.assertEqual(run.engine_version,'3.0.0')
        self.assertTrue(run.validation['passed'])
        self.assertGreater(len(run.evaluations),0)
        self.assertTrue(any(e.rotation.rotation_id=='BASELINE' for e in run.evaluations))
        self.assertTrue(all(1.0<=e.robustness.rank_p90<=len(run.evaluations) for e in run.evaluations))

    def test_parameter_monte_carlo_is_not_score_jitter(self):
        run=run_v3(n_weight_samples=20,n_uncertainty_samples=12)
        self.assertTrue(any(e.robustness.score_std>0 for e in run.evaluations))
        self.assertEqual(run.evaluations[0].robustness.uncertainty_type,'input-parameter Monte Carlo')

    def test_constraints_are_active(self):
        run=run_v3(n_weight_samples=20,n_uncertainty_samples=8)
        accepted={e.rotation.rotation_id for e in run.evaluations}
        self.assertGreater(len(run.rejected),0)
        # Generated options violating the demo budget/labour/water ceilings must not be ranked.
        self.assertTrue(any('budget' in x['reason'] or 'labour' in x['reason'] or 'irrigation' in x['reason'] for x in run.rejected))
        self.assertIn('BASELINE', accepted)  # reference baseline remains visible even when it exceeds a farmer constraint.


if __name__=='__main__':
    unittest.main(verbosity=2)
