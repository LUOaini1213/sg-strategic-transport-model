# Validation report

<!-- docs/validation_report.md is generated from docs/validation_report.template.md by scripts/run_all.py. -->

Personal desk study, not an LTA or URA model. This report sets out what the model was calibrated to, what it was checked against without being fitted to it, and what could not be checked. Every number is generated from `results/`.

**Summary.** Two observed matrices exist: the Census 2020 commuter matrix at region x planning-area level, and LTA DataMall bus rides at stop level. The commuter gravity model is calibrated to the first; a bus-ride gravity model is calibrated to one month of the second and checked on another month. Mode choice is calibrated to Census mode shares on two margins and checked on cells it never sees individually. **Road flows cannot be validated: there are no public link-level traffic counts for Singapore's roads, so this model was not calibrated to counts and claims no road validation.** The road checks below are plausibility checks.

## 1. Commuter distribution against the Census matrix (calibration)

Target: employed residents by region of residence (5) and planning area of workplace (44 named areas), Census 2020, excluding those who work from home, have no fixed workplace or need no transport. Calibrated: the two parameters of the gamma deterrence function (a = -0.492, b = 0.0424 per km), by maximum likelihood on the 220 cells. Row and column totals are reproduced by construction (doubly constrained model), so the fit statistics measure only the internal pattern.

| Measure | Value |
|---|---|
| R2, modelled vs Census cells | 0.989 |
| Standardised RMSE (RMSE / mean cell) | 0.132 |
| Mean trip length at cell resolution (each cell at its mean zone-pair distance): Census / model | 15.08 / 15.08 km |
| Coincidence ratio of the cell-resolution trip-length distributions | 0.960 |
| Modelled mean commute, zone level | 14.3 km |
| Intrazonal share of modelled commuters | 1.4% |

The coincidence ratio is defined here as sum_k min(P_obs,k, P_mod,k) / sum_k max(P_obs,k, P_mod,k) over 1-km bins of proportions; it is 1 for identical distributions. Census distances are not observed: at cell resolution each cell's commuters are placed at the trip-end-weighted mean distance of its zone pairs, the same for Census and model, so this comparison checks the allocation between cells only.

## 2. Bus rides against DataMall (calibration and validation)

Observed: weekday rides tapping in between 07:00-08:00, per weekday (monthly totals / weekday count), aggregated from stops to subzones. Trip ends of the bus model are the observed zonal tap-ins and tap-outs; only the two deterrence parameters are fitted, to July 2026. August 2026 is used with the July parameters and August's own trip ends.

| | July 2026 (calibration) | August 2026 (validation) |
|---|---|---|
| Rides per hour | 401,547 | 410,148 |
| Mean zone-to-zone distance, observed / gamma model | 4.38 / 4.38 km | 4.34 / 4.38 km |
| Same, exponential model (fitted to the mean) | 4.38 km | 4.38 km |
| Coincidence ratio, gamma / exponential (1-km bins) | 0.771 / 0.727 | 0.772 / 0.726 |
| Intrazonal share, observed / model | 16.9% / 22.1% | 17.0% / 22.0% |
| R2, subzone pairs | 0.637 | 0.638 |
| Planning-area pairs with flow | 2,601 | 2,601 |
| R2, planning-area pairs | 0.971 | 0.971 |
| R2, planning-area pairs excluding intra-area pairs | 0.798 | 0.803 |
| GEH < 5, planning-area pairs | 77% | 76% |
| GEH < 10, planning-area pairs | 89% | 89% |
| GEH < 5, pairs with 100+ observed rides | 29% of 335 | 30% of 340 |

GEH = sqrt(2 (M - C)^2 / (M + C)) on hourly flows. It is normally applied to link counts; here it is applied, as a convenient scale-aware measure, to hourly bus rides between planning-area pairs. No acceptance threshold is claimed.

Reading: the moments are matched exactly in July by construction, and August behaves like July (the two months have nearly the same trip ends, so this is a weak test of transfer over time, not over space or policy). A gamma function on distance gets the planning-area pattern right (R2 0.971) but leaves much of the subzone detail unexplained (R2 0.638), and the shape at short distances is only approximate (coincidence ratio 0.772): the observed distribution has fewer very short rides and more 2-3 km rides than the fitted gamma function produces.

**Transfer test.** The bus-calibrated deterrence function applied to commuters: mean commute 9.3 km (Census-calibrated: 14.3 km), R2 on the Census cells 0.814 (vs 0.989), SRMSE 0.878 (vs 0.132). Bus rides are legs, not journeys (a bus-MRT-bus commute is two short rides; mean straight-line ride 2.6 km), so their trip-length distribution is not a valid target for whole commuting journeys.

## 3. Mode choice (calibration and a held-out check)

Calibration targets: Census 2020 mode counts by planning area of residence (30 areas + "Others") and by planning area of workplace (44 areas), three modes, at once. Converged: yes.

| Measure | Value |
|---|---|
| Overall shares, model / Census (residence table) | car 26.8% / 26.8%; PT 64.3% / 64.0%; other 8.9% / 9.2% |
| Mean absolute error, residence areas | 2.0 share points (R2 of car share 0.92) |
| Mean absolute error, workplace areas | 2.5 share points (R2 of car share 0.37) |
| Held out: region x workplace cells with 1,000+ commuters | 206 cells |
| Held out: R2 of car share / PT share | 0.61 / 0.79 |
| Held out: commuter-weighted mean absolute error, car / PT | 3.0 / 3.6 points |

The held-out cells are not independent of the calibration targets (their sums are the calibration margins), but no cell enters the likelihood on its own. The residence table includes workers with no fixed workplace, whom the commuter matrix leaves out, so the residence targets and the modelled trips do not describe exactly the same people.

Profile of the time coefficient (other parameters re-estimated at each fixed value):

| b_time (per min) |  | log-likelihood minus maximum | West residents' PT share, 2030 without JRL | with JRL | JRL effect (points) | JRL effect on car trips/h |
|---|---|---|---|---|---|---|
| -0.0050 | fixed | -264 | 65.8% | 65.9% | 0.17 | -288 |
| -0.0090 | estimated | 0 | 65.7% | 66.0% | 0.30 | -526 |
| -0.0200 | fixed | -1,721 | 65.6% | 66.3% | 0.65 | -1,144 |
| -0.0300 | fixed | -5,605 | 65.5% | 66.4% | 0.96 | -1,620 |
| -0.0500 | fixed | -16,716 | 65.0% | 66.5% | 1.51 | -2,277 |

## 4. Assignment convergence and verification

| Scenario | iterations | relative gap (final) | relative gap recomputed from the saved flows |
|---|---|---|---|
| 2020 base | 282 | 8.9e-07 | 8.9e-07 |
| 2030 without JRL | 346 | 8.1e-07 | 8.1e-07 |
| 2030 with JRL | 282 | 9.3e-07 | 9.3e-07 |

`tests/test_pipeline.py` recomputes these gaps from the saved flows and the demand they were solved for (`results/link_flows.csv`, `connector_flows.csv`, `car_demand_*.npy`) with one independent all-or-nothing load each, and solves the base year again from scratch to 1e-04 to compare with the saved flows.

What stopping at the usual 1e-04 would have cost (flows at the first iteration that reaches it, against the final flows):

| Scenario | iteration reaching the reference gap | final iteration | links differing from the final flows by more than max(10 pcu/h, 2%) | largest difference (pcu/h) | links differing by 0.05+ in V/C |
|---|---|---|---|---|---|
| base 2020 | 36 | 282 | 3.3% | 411 | 45 |
| dm 2030 | 38 | 346 | 4.0% | 563 | 50 |
| ds 2030 jrl | 40 | 282 | 3.1% | 482 | 46 |

Differences of this size are as large as the scenario effects in section g of the README, which is why the target is 1e-06. A re-run on another machine follows a slightly different iteration path (floating-point arithmetic) and ends at slightly different flows within that gap.

Sioux Falls (24 zones, 76 links, 360,600 trips): the published best-known flows give relative gap below 1e-12 in absolute value and objective 42.31335287 x 10^5 in this code (published optimum 42.31335287); total system travel time 7,480,225. This code at relative gap 8.6e-07: 970 iterations, objective 42.313359 (relative difference 1.3e-07), largest link-flow difference 1.6 vehicles (0.01%). At gap 1e-4: bi-conjugate FW 93 iterations (largest flow difference 0.46%), plain FW 1,049 iterations (0.19%).

## 5. Roads: plausibility only

No public link-level traffic counts exist for Singapore's roads, and none were used. The road assignment is therefore **not calibrated or validated**; the checks below test only whether the outputs are internally consistent and not absurd.

Share of directed link-km by volume/capacity:

| Scenario | V/C 0-0.5 | V/C 0.5-0.85 | V/C 0.85-1.0 | V/C >1.0 |
|---|---|---|---|---|
| base 2020 | 85.1% | 9.7% | 2.3% | 3.0% |
| dm 2030 | 84.7% | 9.8% | 2.3% | 3.2% |
| ds 2030 jrl | 84.9% | 9.7% | 2.2% | 3.2% |

By road class, 2020 base:

| OSM class | km (directed) | mean V/C (km-weighted) | km with V/C > 0.85 | km with V/C > 1.0 | mean speed (km/h, flow-weighted) |
|---|---|---|---|---|---|
| motorway | 313 | 0.50 | 17.7% | 7.6% | 78 |
| trunk | 158 | 0.29 | 6.3% | 2.8% | 52 |
| primary | 856 | 0.22 | 4.1% | 2.8% | 39 |
| secondary | 562 | 0.13 | 2.1% | 1.5% | 36 |
| tertiary | 600 | 0.08 | 2.6% | 1.7% | 29 |
| motorway_link | 243 | 0.27 | 9.3% | 6.4% | 41 |
| trunk_link | 52 | 0.16 | 2.8% | 0.4% | 44 |
| primary_link | 89 | 0.10 | 1.9% | 0.7% | 36 |
| secondary_link | 27 | 0.08 | 1.8% | 1.2% | 33 |
| tertiary_link | 13 | 0.02 | 0.4% | 0.1% | 29 |

Screenlines (consistency, not validation): assigned flow crossing a north-south line vs the car OD demand whose origin and destination centroids lie on opposite sides. Assigned flow should be at least the demand, more where routes cross the line more than once.

| Screenline | Scenario | links | assigned eastbound | OD demand crossing eastbound | assigned westbound | OD demand crossing westbound |
|---|---|---|---|---|---|---|
| x = 21 km (West | rest) | base 2020 | 68 | 28,291 | 17,472 | 29,793 | 21,239 |
| x = 21 km (West | rest) | ds 2030 jrl | 68 | 30,901 | 19,844 | 29,006 | 20,265 |
| x = 30 km (central) | base 2020 | 77 | 33,042 | 25,762 | 41,024 | 32,500 |
| x = 30 km (central) | ds 2030 jrl | 77 | 34,565 | 27,156 | 40,536 | 31,891 |

What would be needed for real road validation: classified counts on screenlines and key links (none public), or travel times; LTA DataMall's traffic speed bands give observed speeds on road segments and could be compared with modelled speeds in a later version (not done here).

## 6. What was not validated

- Road link flows, turning flows and junction delays (no counts).
- Whole public-transport journeys (no train origin-destination data were used; DataMall publishes them but they were not downloaded for this study).
- The 2030 forecasts (by nature), the Tengah build-out, and the transferability of 2020 behaviour to 2030.
- Mode choice at subzone level, and the time coefficient (weakly identified; see section 3).
