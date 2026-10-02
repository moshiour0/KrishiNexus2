# FieldShift V3 — known unknowns

These are not hidden implementation gaps; they are explicitly marked evidence limitations.

1. Crop coefficients, yield baselines, economics and disease-break values in the demo crop pack still contain placeholders and require local agronomic review.
2. The SOC module is a lightweight two-pool trajectory proxy, not a locally calibrated RothC/ICBM model.
3. Nutrient availability fractions are explicit assumptions until soil-test interpretation/calibration data are supplied.
4. The diagnostic `ssp245_midcentury` / `ssp585_midcentury` fallback is a stress-test delta, not a multi-GCM climate ensemble.
5. SoilGrids REST access is opt-in because the upstream REST service is beta/availability-limited.
6. Model-vs-MODIS and model-vs-SMAP checks quantify consistency; they do not by themselves calibrate the model.
7. The final decision should be reviewed by a farmer/advisor when recommendations have material livelihood or input-cost consequences.
