# Validation report

<!-- docs/validation_report.md is generated from docs/validation_report.template.md by scripts/run_all.py. -->

Personal desk study, not an LTA or URA model. This report sets out what the model was calibrated to, what it was checked against without being fitted to it, and what could not be checked. Every number is generated from `results/`.

**Summary.** Two observed matrices exist: the Census 2020 commuter matrix at region x planning-area level, and LTA DataMall bus rides at stop level. The commuter gravity model is calibrated to the first; a bus-ride gravity model is calibrated to one month of the second and checked on another month. Mode choice is calibrated to Census mode shares on two margins and checked on cells it never sees individually. **Road flows cannot be validated: there are no public link-level traffic counts for Singapore's roads, so this model was not calibrated to counts and claims no road validation.** The road checks below are plausibility checks.

## 1. Commuter distribution against the Census matrix (calibration)

Target: employed residents by region of residence (5) and planning area of workplace (44 named areas), Census 2020, excluding those who work from home, have no fixed workplace or need no transport. Calibrated: the two parameters of the gamma deterrence function (a = {{dc_a}}, b = {{dc_b}} per km), by maximum likelihood on the {{dc_cells}} cells. Row and column totals are reproduced by construction (doubly constrained model), so the fit statistics measure only the internal pattern.

| Measure | Value |
|---|---|
| R2, modelled vs Census cells | {{dc_r2}} |
| Standardised RMSE (RMSE / mean cell) | {{dc_srmse}} |
| Mean trip length at cell resolution (each cell at its mean zone-pair distance): Census / model | {{dc_cell_census}} / {{dc_cell_model}} km |
| Coincidence ratio of the cell-resolution trip-length distributions | {{dc_cr}} |
| Modelled mean commute, zone level | {{dc_mean}} km |
| Intrazonal share of modelled commuters | {{dc_intra}} |

The coincidence ratio is defined here as sum_k min(P_obs,k, P_mod,k) / sum_k max(P_obs,k, P_mod,k) over 1-km bins of proportions; it is 1 for identical distributions. Census distances are not observed: at cell resolution each cell's commuters are placed at the trip-end-weighted mean distance of its zone pairs, the same for Census and model, so this comparison checks the allocation between cells only.

## 2. Bus rides against DataMall (calibration and validation)

Observed: weekday rides tapping in between {{bus_hour}}, per weekday (monthly totals / weekday count), aggregated from stops to subzones. Trip ends of the bus model are the observed zonal tap-ins and tap-outs; only the two deterrence parameters are fitted, to July 2026. August 2026 is used with the July parameters and August's own trip ends.

| | July 2026 (calibration) | August 2026 (validation) |
|---|---|---|
| Rides per hour | {{cal_trips}} | {{val_trips}} |
| Mean zone-to-zone distance, observed / gamma model | {{cal_mean_obs}} / {{cal_mean_mod}} km | {{val_mean_obs}} / {{val_mean_mod}} km |
| Same, exponential model (fitted to the mean) | {{cal_mean_exp}} km | {{val_mean_exp}} km |
| Coincidence ratio, gamma / exponential (1-km bins) | {{cal_cr}} / {{cal_cr_exp}} | {{val_cr}} / {{val_cr_exp}} |
| Intrazonal share, observed / model | {{cal_intra_obs}} / {{cal_intra_mod}} | {{val_intra_obs}} / {{val_intra_mod}} |
| R2, subzone pairs | {{cal_r2z}} | {{val_r2z}} |
| Planning-area pairs with flow | {{cal_pairs}} | {{val_pairs}} |
| R2, planning-area pairs | {{cal_r2pa}} | {{val_r2pa}} |
| R2, planning-area pairs excluding intra-area pairs | {{cal_r2pa_inter}} | {{val_r2pa_inter}} |
| GEH < 5, planning-area pairs | {{cal_geh5}} | {{val_geh5}} |
| GEH < 10, planning-area pairs | {{cal_geh10}} | {{val_geh10}} |
| GEH < 5, pairs with 100+ observed rides | {{cal_geh5_100}} of {{cal_pairs_100}} | {{val_geh5_100}} of {{val_pairs_100}} |

GEH = sqrt(2 (M - C)^2 / (M + C)) on hourly flows. It is normally applied to link counts; here it is applied, as a convenient scale-aware measure, to hourly bus rides between planning-area pairs. No acceptance threshold is claimed.

Reading: the moments are matched exactly in July by construction, and August behaves like July (the two months have nearly the same trip ends, so this is a weak test of transfer over time, not over space or policy). A gamma function on distance gets the planning-area pattern right (R2 {{val_r2pa}}) but leaves much of the subzone detail unexplained (R2 {{val_r2z}}), and the shape at short distances is only approximate (coincidence ratio {{val_cr}}): the observed distribution has fewer very short rides and more 2-3 km rides than the fitted gamma function produces.

**Transfer test.** The bus-calibrated deterrence function applied to commuters: mean commute {{tr_mean}} km (Census-calibrated: {{dc_mean}} km), R2 on the Census cells {{tr_r2}} (vs {{dc_r2}}), SRMSE {{tr_srmse}} (vs {{dc_srmse}}). Bus rides are legs, not journeys (a bus-MRT-bus commute is two short rides; mean straight-line ride {{bus_stop_mean}} km), so their trip-length distribution is not a valid target for whole commuting journeys.

## 3. Mode choice (calibration and a held-out check)

Calibration targets: Census 2020 mode counts by planning area of residence (30 areas + "Others") and by planning area of workplace (44 areas), three modes, at once. Converged: {{mc_conv}}.

| Measure | Value |
|---|---|
| Overall shares, model / Census (residence table) | car {{mc_car_mod}} / {{mc_car_obs}}; PT {{mc_pt_mod}} / {{mc_pt_obs}}; other {{mc_oth_mod}} / {{mc_oth_obs}} |
| Mean absolute error, residence areas | {{mc_res_mae}} share points (R2 of car share {{mc_res_r2}}) |
| Mean absolute error, workplace areas | {{mc_work_mae}} share points (R2 of car share {{mc_work_r2}}) |
| Held out: region x workplace cells with 1,000+ commuters | {{mc_hold_n}} cells |
| Held out: R2 of car share / PT share | {{mc_hold_r2car}} / {{mc_hold_r2pt}} |
| Held out: commuter-weighted mean absolute error, car / PT | {{mc_hold_maecar}} / {{mc_hold_maept}} points |

The held-out cells are not independent of the calibration targets (their sums are the calibration margins), but no cell enters the likelihood on its own. The residence table includes workers with no fixed workplace, whom the commuter matrix leaves out, so the residence targets and the modelled trips do not describe exactly the same people.

Profile of the time coefficient (other parameters re-estimated at each fixed value):

{{profile_table}}

## 4. Assignment convergence and verification

| Scenario | iterations | relative gap (final) | relative gap recomputed from the saved flows |
|---|---|---|---|
| 2020 base | {{as_base_it}} | {{as_base_gap}} | {{as_base_gap2}} |
| 2030 without JRL | {{as_dm_it}} | {{as_dm_gap}} | {{as_dm_gap2}} |
| 2030 with JRL | {{as_ds_it}} | {{as_ds_gap}} | {{as_ds_gap2}} |

`tests/test_pipeline.py` recomputes these gaps from the saved flows and the demand they were solved for (`results/link_flows.csv`, `connector_flows.csv`, `car_demand_*.npy`) with one independent all-or-nothing load each, and solves the base year again from scratch to {{cfg_rgap_ref}} to compare with the saved flows.

What stopping at the usual {{cfg_rgap_ref}} would have cost (flows at the first iteration that reaches it, against the final flows):

{{tightness_table}}

Differences of this size are as large as the scenario effects in section g of the README, which is why the target is {{cfg_rgap}}. A re-run on another machine follows a slightly different iteration path (floating-point arithmetic) and ends at slightly different flows within that gap.

Sioux Falls (24 zones, 76 links, 360,600 trips): the published best-known flows give relative gap {{sf_gap_pub}} and objective {{sf_obj_pub}} x 10^5 in this code (published optimum {{sf_obj}}); total system travel time {{sf_tstt}}. This code at relative gap {{sf_bfw6_gap}}: {{sf_bfw6_it}} iterations, objective {{sf_bfw6_obj}} (relative difference {{sf_bfw6_rel}}), largest link-flow difference {{sf_bfw6_maxabs}} vehicles ({{sf_bfw6_maxrel}}). At gap 1e-4: bi-conjugate FW {{sf_bfw4_it}} iterations (largest flow difference {{sf_bfw4_maxrel}}), plain FW {{sf_fw4_it}} iterations ({{sf_fw4_maxrel}}).

## 5. Roads: plausibility only

No public link-level traffic counts exist for Singapore's roads, and none were used. The road assignment is therefore **not calibrated or validated**; the checks below test only whether the outputs are internally consistent and not absurd.

Share of directed link-km by volume/capacity:

{{vc_table}}

By road class, 2020 base:

{{vc_class_table}}

Screenlines (consistency, not validation): assigned flow crossing a north-south line vs the car OD demand whose origin and destination centroids lie on opposite sides. Assigned flow should be at least the demand, more where routes cross the line more than once.

{{screenline_table}}

What would be needed for real road validation: classified counts on screenlines and key links (none public), or travel times; LTA DataMall's traffic speed bands give observed speeds on road segments and could be compared with modelled speeds in a later version (not done here).

## 6. What was not validated

- Road link flows, turning flows and junction delays (no counts).
- Whole public-transport journeys (no train origin-destination data were used; DataMall publishes them but they were not downloaded for this study).
- The 2030 forecasts (by nature), the Tengah build-out, and the transferability of 2020 behaviour to 2030.
- Mode choice at subzone level, and the time coefficient (weakly identified; see section 3).
