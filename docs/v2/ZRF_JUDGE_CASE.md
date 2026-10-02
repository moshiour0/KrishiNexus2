# ZRF / science-hackathon judge case

The same engine is suitable for a science/innovation judging conversation where the emphasis is on problem understanding, technical depth, reproducibility and demonstration quality.

## Demonstration narrative

**Problem:** rotation choices interact with climate, water, soil, yield, labour and economics.

**Innovation:** combine satellite/model observations with agronomic simulation and multi-objective optimization instead of using a single crop score.

**Technical depth:** the engine contains a root-zone water model, crop stress/yield response, automatic rotation search, scenario analysis, uncertainty and explainability.

**Reproducibility:** data source, parameter provenance, configuration and test suite are part of the repository.

**Usability:** the final output is a ranked decision frontier with reasons, baseline deltas and uncertainty rather than an opaque model prediction.

## Judge questions the engine should answer

- Why did this rotation score well?
- Which data source affected the result?
- What happens if rainfall changes?
- What happens if irrigation reliability falls?
- Does the recommendation remain stable if the farmer changes priorities?
- How much does the baseline practice differ?
- What is known vs estimated?
- What new BAU/local data would change the result?

Every one of these is represented in V2 output objects or configuration.
