# Fitness Design (GA Objective + Scoring Pipeline)

## Objective

The optimizer minimizes:

`J = w_in*E_in + w_out*E_out + w_bw*E_bw + w_smooth*E_smooth + w_eff*E_eff + w_mfg*E_mfg`

This repository's GA implementation is a maximize loop, so conversion is:

`fitness = -J`

Default weights (configurable):

- `w_in = 0.40`
- `w_out = 0.30`
- `w_bw = 0.15`
- `w_smooth = 0.05`
- `w_eff = 0.05`
- `w_mfg = 0.05`

## Data Pipeline

1. Parse observation file: `scoring/io.py::parse_observation_file`
2. Load target coverage config: `scoring/coverage.py::load_coverage_target`
3. Resolve per-frequency targets/weights: `scoring/coverage.py::resolve_frequency_target`
4. Compute score terms: `scoring/fitness.py::score_observation_file`
5. Return scalar fitness + breakdown + write score artifacts

## Observation Schema

Supported input formats:

- CSV
- JSON (list of records or `records`/`observations`/`data` list)
- NPZ (column arrays with equal length)

Required logical fields (auto-detected by aliases):

- frequency: `frequency_hz`, `freq_hz`, `frequency`, `f_hz`, `freq`
- polar angle: `theta_polar_rad`, `theta_rad`, `theta_polar_deg`, `theta_deg`, `theta`
- SPL: `spl_normalized_db`, `spl_db`, `spl_norm_db`, `spl`

Optional fields:

- `phi_azimuth_rad`, `phi_rad`, `phi_azimuth_deg`, `phi_deg`, `phi` (defaults to `0 deg` when missing)
- `inside_coverage`
- `efficiency_proxy_db`
- `matching_proxy`
- `target_db`
- `x`, `y`, `z`, `r_distance_m`

Angle unit is inferred from column name first, then from value range.

## Coverage Target Config

Reference files:

- `config/coverage_target.example.yaml`
- `config/coverage_target.yaml`

Main keys:

- `horizontal_coverage_deg`
- `vertical_coverage_deg`
- `transition_margin_deg`
- `in_coverage_target_db`
- `out_of_coverage_threshold_db`
- `frequency_weights` and/or `alpha_frequency_weights`, `beta_frequency_weights`, `gamma_frequency_weights`
- `horizontal_target_beamwidth_deg`
- `vertical_target_beamwidth_deg`
- optional `per_frequency` overrides

CSV targets remain supported for backward compatibility (`config/coverage_target.example.csv`).

## Term Definitions

- `E_in`: in-coverage point error + ripple penalty
- `E_out`: out-of-coverage spill penalty above threshold only
- `E_bw`: beamwidth target mismatch (`-6 dB` or configured down level)
- `E_smooth`: transition + boundary roughness + side-lobe over-limit penalties
- `E_eff`: efficiency/matching penalties
  - preferred: `efficiency_proxy_db` + `matching_proxy`
  - fallback proxy: in-vs-out energy concentration + matching
- `E_mfg`: manufacturability/geometry penalty (bound violations + extreme ratios/slopes)

## Score Breakdown and Artifacts

Each scoring call returns:

- `total_cost`, `fitness`
- `E_in`, `E_out`, `E_bw`, `E_smooth`, `E_eff`, `E_mfg`
- `skipped_components`, `warnings`
- per-frequency metrics

If output directory is provided, scoring also writes:

- `outputs/scoring/score_<case_tag>.json`
- `outputs/scoring/score_summary.csv`

## Mock vs Real

- `mock` mode:
  - synthetic observation generation (not real physics)
  - used for parser/scoring/GA loop validation
- `real` mode:
  - uses ATH + Gmsh + available BEM backend path
  - currently solver backend is placeholder-style output compatible with scoring schema
