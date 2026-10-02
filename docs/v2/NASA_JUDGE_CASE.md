# NASA judge case

## What problem are we solving?

Crop rotation is a multi-variable planning problem. A farmer is not choosing between crops in isolation; the choice changes water demand, root-zone moisture, heat exposure, nutrient balance, labour timing, yield stability and farm economics under uncertain weather.

Field Shift V2 makes that planning problem explicit and computable.

## Why NASA data matters

NASA data is used as model input rather than decoration:

- POWER contributes daily meteorological drivers for ET0 and crop-water demand.
- GPM contributes precipitation observations.
- SMAP contributes soil-moisture state information.
- HLS contributes field vegetation-condition signals.
- MODIS ET contributes an independent evapotranspiration signal.
- NEX-GDDP-CMIP6 supplies future climate scenarios.

The model then turns those observations into crop stress, yield response, economics and rotation-level decision dimensions.

## How to defend scientific validity

1. Equations are isolated in modules.
2. Units are explicit.
3. Crop parameters carry source/review status.
4. Data provenance is retained in the output.
5. Observed/modelled/estimated/synthetic data remain distinguishable.
6. Scenario assumptions are named.
7. Unit tests cover physical and structural sanity.
8. Baseline practice stays visible.
9. Ablation identifies which decision dimensions actually change the result.
10. Uncertainty is shown as an envelope instead of hidden behind one number.

## The strongest judge demo

Start with a conventional baseline rotation. Then change one data layer at a time:

```text
baseline only
      ↓
+ NASA weather
      ↓
+ NASA soil moisture / precipitation / vegetation
      ↓
+ local soil lab values
      ↓
+ crop expert parameters
      ↓
+ farmer constraints
```

At each step show how the decision frontier changes and why.

This makes the NASA contribution measurable instead of rhetorical.

## What not to claim

Do not claim a rotation is proven optimal or safe for a real farm. State exactly which parts are observed, modelled, estimated or pending local validation.
