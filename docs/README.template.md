# sg-strategic-transport-model

**A reproducible strategic (four-step) transport model of Singapore for the weekday AM peak hour: {{n_zones}} URA Master Plan 2019 subzones, commuting from the Census of Population 2020, gravity distribution calibrated to Census and to LTA DataMall bus origin-destination data, logit mode choice, user-equilibrium assignment on the OpenStreetMap road network, and a 2030 test of Tengah with and without the Jurong Region Line.**

> **Read this first.** This is a personal desk study. It is **not an LTA or URA model**, not a consultancy study, and it has not been reviewed by either agency. It uses public data plus stated assumptions, and every input is labelled REAL, DERIVED, ASSUMPTION or ILLUSTRATIVE in the [data provenance](#data-provenance) section. **There are no public link-level traffic counts for Singapore's roads, so the road side of this model is not calibrated or validated against counts; only plausibility checks are reported.** The demand model covers resident commuters with a fixed workplace (Census 2020); all other road traffic enters through one assumed factor.

<!-- README.md is generated from docs/README.template.md by scripts/run_all.py. Do not edit README.md by hand. -->

## What it does

| Step | What | Calibrated or checked against |
|---|---|---|
| a. Zones | {{n_zones}} MP2019 subzones in {{n_pa}} planning areas; one centroid each, placed by floor area | - |
| b. Trip generation | {{commuters}} daily commuters (employed residents travelling to a fixed workplace in a named planning area) produced from Census 2020 tables and attracted in proportion to MP2019 floor space; AM peak-hour share from DataMall bus volumes | Census totals by construction |
| c. Distribution | doubly constrained gravity model, gamma deterrence on road distance | commuters: Census 2020 region of residence x planning area of workplace ({{dc_cells}} cells); a separate bus-trip model: DataMall bus trip-length distribution, July 2026 (calibration) and August 2026 (validation) |
| d. Mode choice | multinomial logit, car / public transport / other | Census 2020 usual mode of transport to work, by planning area of residence and of workplace; region x workplace cells held out |
| e. Assignment | static user equilibrium, bi-conjugate Frank-Wolfe, BPR links, relative gap <= {{cfg_rgap}}, on {{road_links}} OpenStreetMap links (motorway to tertiary) | code verified on the Sioux Falls test network against its published equilibrium |
| f. Validation | bus OD: GEH, R2, trip-length distribution; road: V/C distribution and screenlines | no road counts exist: plausibility only |
| g. 2030 scenarios | Tengah built out ({{tg_homes}} homes, HDB), with and without the {{jrl_n}}-station Jurong Region Line; junction growth factors and a worked signal check | - |
| h. Microsimulation | **not done** (optional step; no time left after a-g) | - |

## Headline numbers

All values are generated from the files in [`results/`](results/) by `scripts/run_all.py`.

| | | Source file |
|---|---|---|
| Commuter gravity model vs Census cells | R2 {{dc_r2}} on {{dc_cells}} region x workplace cells; mean trip length {{dc_cell_model}} km modelled vs {{dc_cell_census}} km Census at that resolution | `results/summary.json`, `calibration_commute_cells.csv` |
| Bus gravity model, calibration month (July 2026, {{bus_hour}}) | mean zone-to-zone distance {{cal_mean_mod}} km modelled = {{cal_mean_obs}} km observed (fitted); coincidence ratio {{cal_cr}} | `results/summary.json`, `tld_bus.csv` |
| Bus gravity model, validation month (August 2026) | planning-area pairs: R2 {{val_r2pa}}, GEH < 5 for {{val_geh5}} of {{val_pairs}} pairs ({{val_geh5_100}} of the {{val_pairs_100}} pairs with 100+ trips); subzone pairs: R2 {{val_r2z}} | `results/summary.json`, `bus_pa_pairs_202608.csv` |
| Bus deterrence used for commuting instead | mean commute length {{tr_mean}} km instead of {{dc_mean}} km ({{tr_mean_drop}} shorter); R2 on Census cells {{tr_r2}} instead of {{dc_r2}} | `results/summary.json` |
| Mode shares, 2020 | car {{mc_car_mod}} / PT {{mc_pt_mod}} / other {{mc_oth_mod}} modelled; Census {{mc_car_obs}} / {{mc_pt_obs}} / {{mc_oth_obs}} | `results/summary.json` |
| Mode choice on held-out cells | {{mc_hold_n}} region x workplace cells: R2 {{mc_hold_r2car}} (car share), {{mc_hold_r2pt}} (PT share); weighted mean absolute error {{mc_hold_maecar}} and {{mc_hold_maept}} points | `results/mode_shares_holdout_cells.csv` |
| Assignment, 2020 AM peak hour | {{as_base_q}} car trips/h; relative gap {{as_base_gap}} after {{as_base_it}} iterations (recomputed independently: {{as_base_gap2}}) | `results/summary.json`, `assignment_convergence.csv` |
| Sioux Falls check | the published equilibrium flows give relative gap {{sf_gap_pub}} and objective {{sf_obj_pub}} in this code (published optimum {{sf_obj}}); this code at gap {{sf_bfw6_gap}}: objective {{sf_bfw6_obj}}, largest link-flow difference {{sf_bfw6_maxrel}} | `results/sioux_falls_check.json` |
| Road plausibility, 2020 | {{vc_over085_base}} of directed link-km above V/C 0.85, {{vc_over1_base}} above 1.0; flow-weighted mean speed {{motorway_speed}} km/h on expressways, {{primary_speed}} km/h on primary roads | `results/vc_by_class_base.csv` |
| Tengah, 2030 | {{tg_homes}} homes x {{cfg_persons}} persons = {{tg_pop}} residents, {{tg_comm}} commuters; {{tengah_car_trips}} extra car trips/h | `results/summary.json` |
| Jurong Region Line, 2030 | West Region residents' PT share {{jrl_west_pt_pts}} points ({{ms_dm_west_residents_pt}} -> {{ms_ds_west_residents_pt}}), Tengah {{jrl_tengah_pt_pts}} points; {{jrl_car_trips}} car trips/h; links in the West with V/C down by 0.05+: {{west_down}}, up by 0.05+: {{west_up}} | `results/summary.json`, `scenario_mode_share_west.csv` |
| How much that JRL result depends on one parameter | the estimated time coefficient is small ({{mc_b_time}} per minute); with fixed values from -0.005 to -0.05 the JRL effect on West residents' PT share ranges from {{jrl_pts_lo}} to {{jrl_pts_hi}} points | `results/mode_choice_time_profile.csv` |

What the numbers say:

- **The gravity model reproduces where Census commuters work.** With two calibrated parameters, the doubly constrained model fits the {{dc_cells}} region x workplace cells with R2 {{dc_r2}}, and matches the Census mean trip length at that resolution ({{dc_cell_census}} km Census, {{dc_cell_model}} km model).
- **Bus trip lengths are the wrong target for commuting.** DataMall counts bus *rides* (tap-in to tap-out), not whole journeys, and they are short: {{cal_intra_obs}} of morning-peak rides start and end in the same subzone, and the mean straight-line ride is {{bus_stop_mean}} km. Calibrated to bus rides, the deterrence function makes commutes {{tr_mean_drop}} shorter than Census implies. The bus data are therefore used for their own sub-model and for validation, and the commuter model is calibrated to Census.
- **The JRL changes mode shares by tenths of a point, and that number rests on a weakly identified parameter.** Planning-area shares identify housing type and workplace type far better than travel time; the estimated time coefficient is {{mc_b_time}} per minute, and forcing -0.03 costs {{ll_drop_003}} log-likelihood units. Read the JRL result as a range ({{jrl_pts_lo}} to {{jrl_pts_hi}} points), not a forecast.

![Zones](results/figures/zones.png)

![Calibration](results/figures/calibration.png)

![Volume / capacity](results/figures/vc_base.png)

![2030 scenarios](results/figures/scenario_2030.png)

More figures: [desire lines](results/figures/desire_lines.png), [bus planning-area pairs](results/figures/bus_pa_pairs.png), [mode shares](results/figures/mode_shares.png), [assignment convergence](results/figures/convergence.png). Full validation: [docs/validation_report.md](docs/validation_report.md).

## Method

### a. Zones and networks

- **Zones.** The {{n_zones}} subzones of URA's Master Plan 2019 (Subzone Boundary, No Sea). {{zones_with_residents}} have Census 2020 residents; {{zones_a}} receive commuters. Each zone has one centroid: the floor-area-weighted mean of its MP2019 parcels, moved to a point inside the zone when the mean falls outside.
- **Roads.** OpenStreetMap ways tagged motorway, trunk, primary, secondary, tertiary and their links, from the BBBike extract for Singapore, clipped to the MP2019 boundary, split at junctions, chains of identical links merged, and reduced to the largest strongly connected component: {{road_nodes}} nodes, {{road_links}} directed links, {{road_km}} directed km. Lanes come from OSM tags on {{lanes_tag}} of links and speed limits on {{speed_tag}}; the rest use class defaults (ASSUMPTION). Each zone is connected to its {{cfg_conn}} nearest non-expressway nodes.
- **Rail.** {{st_base}} stations in the 2020 network (lines and LRT loops in station-code order; positions from LTA's MRT station exits), {{st_jrl}} with the Jurong Region Line (positions of {{jrl_osm}} new JRL stations from OpenStreetMap).

### b. Trip generation

The Census 2020 table of employed residents by planning area of workplace, mode and region of residence gives, for each of the five regions, how many residents travel to a workplace in each named planning area. Those who work from home, have no fixed workplace, work outside Singapore or need no transport are left out: {{commuters}} commuters ({{commuter_share}} of the {{census_employed}} employed residents).

- Productions: each region's total is shared among its planning areas by the Census table of employed residents by planning area of residence (less "no transport required"), then among subzones by Census 2020 residents aged 20-64 (ASSUMPTION: equal employment rates within a planning area).
- Attractions: each workplace planning area's total is shared among its subzones by MP2019 floor area (site area x gross plot ratio) weighted by relative job densities per land-use class (ASSUMPTION; only ratios within a planning area matter).
- AM peak hour: daily trips x attendance factor {{attendance}} (ASSUMPTION) x peak-hour share {{phf}} = {{peak_trips}} commuter trips from 07:00 to 08:00. The share is DERIVED from DataMall bus tap-ins (07:00-07:59 is the busiest weekday morning hour; share of the 05:00-10:59 window) and transferred to all modes (ASSUMPTION).

### c. Distribution

Doubly constrained gravity model T_ij = A_i O_i B_j D_j f(c_ij), balanced by Furness iteration, with a gamma deterrence function f(c) = c^a exp(-b c) on road distance along the free-flow shortest path (intrazonal distance: half the distance to the nearest other centroid).

- **Commuters**: (a, b) = ({{dc_a}}, {{dc_b}} per km), maximising the multinomial likelihood of the Census region x workplace counts. Fit: R2 {{dc_r2}}, standardised RMSE {{dc_srmse}} over {{dc_cells}} cells; modelled mean commute {{dc_mean}} km.
- **Bus rides**: a second gravity model whose trip ends are the observed tap-ins and tap-outs of each zone between {{bus_hour}} on weekdays (DataMall, July 2026; {{cal_trips}} rides per hour). The gamma parameters ({{bus_a}}, {{bus_b}} per km) solve the two maximum-likelihood conditions of a doubly constrained gamma model: modelled mean distance and mean log distance equal to the observed ones. An exponential function calibrated by mean trip length (Hyman's condition) is shown for comparison (b = {{bus_bexp}} per km).

Why the commuter model is not calibrated to the bus trip-length distribution: the bus data are rides, not journeys. A bus-MRT-bus commute appears as two short bus rides; the mean straight-line ride length is {{bus_stop_mean}} km. Used for commuters, the bus-calibrated function gives a {{tr_mean}} km mean commute (vs {{dc_mean}} km) and R2 {{tr_r2}} on the Census cells.

### d. Mode choice

Multinomial logit on origin-destination pairs:

```
V_car   = asc_car + b_time * t_car + b_priv * private_i + b_central * central_j + b_ind_car * industrial_j
V_pt    =           b_time * g_pt
V_other = asc_other + b_dist_other * d_ij + b_ind_other * industrial_j
```

t_car is free-flow car time plus {{cfg_terminal}} minutes at the ends; g_pt is the generalised PT time (walking weighted {{cfg_walk_w}}, waiting {{cfg_wait_w}}) by the better of a bus-only path and the best rail path (access by walking or feeder bus, transfers penalised); private_i is the share of residents in condominiums and landed housing (Census 2020); central_j flags URA's Central Area; industrial_j is the share of a zone's job weight on Business 1/2 and port land. Modes follow the Census categories: car = car only + taxi/private-hire car only; PT = any combination of MRT/LRT and public bus; other = chartered bus/van, lorry, motorcycle, others.

Calibrated by maximising the log-likelihood of the Census mode counts by planning area of residence and by planning area of workplace at once (converged: {{mc_conv}}):

| asc_car | asc_other | b_time (/min) | b_priv | b_central | b_dist_other (/km) | b_ind_car | b_ind_other |
|---|---|---|---|---|---|---|---|
| {{mc_asc_car}} | {{mc_asc_other}} | {{mc_b_time}} | {{mc_b_priv}} | {{mc_b_central}} | {{mc_b_dist_other}} | {{mc_b_ind_car}} | {{mc_b_ind_other}} |

Mean absolute error {{mc_res_mae}} share points by residence area and {{mc_work_mae}} by workplace area. On the {{mc_hold_n}} region x workplace cells with 1,000+ commuters, which the calibration never sees cell by cell: R2 {{mc_hold_r2car}} (car share) and {{mc_hold_r2pt}} (PT share).

The time coefficient is weakly identified by planning-area shares. Its profile, and what each value does to the JRL result:

{{profile_table}}

### e. Assignment

Car trips per hour = commuters x attendance x peak-hour share x car probability / car occupancy {{cfg_occ}} (ASSUMPTION) x background factor {{cfg_bg}} (ASSUMPTION: the model has no goods vehicles, buses, taxis between fares, non-work trips or non-resident workers; this single factor stands in for all of them and is not calibrated). Intrazonal trips are not assigned.

Link costs follow the BPR function t = t0 (1 + {{cfg_alpha}} (v/c)^{{cfg_beta}}) (Bureau of Public Roads 1964). Capacity = lanes x a per-lane capacity by road class, free-flow speed = speed limit x a class factor (both ASSUMPTION, in `config/model.json`). The equilibrium is solved with the bi-conjugate Frank-Wolfe method of Mitradjieva and Lindberg (2013), with exact line search by bisection, falling back to plain Frank-Wolfe whenever the conjugate direction is not a descent direction. The relative gap (TSTT - SPTT) / SPTT is computed every iteration from a fresh all-or-nothing load; the final gap is recomputed independently.

| Scenario | car trips/h | iterations | relative gap | vehicle-hours | vehicle-km |
|---|---|---|---|---|---|
| 2020 base | {{as_base_q}} | {{as_base_it}} | {{as_base_gap}} | {{as_base_vht}} | {{as_base_vkt}} |
| 2030 without JRL | {{as_dm_q}} | {{as_dm_it}} | {{as_dm_gap}} | {{as_dm_vht}} | {{as_dm_vkt}} |
| 2030 with JRL | {{as_ds_q}} | {{as_ds_it}} | {{as_ds_gap}} | {{as_ds_vht}} | {{as_ds_vkt}} |

**Why {{cfg_rgap}} and not {{cfg_rgap_ref}}.** At the iteration where the 2020 run first reaches a relative gap of {{cfg_rgap_ref}} (iteration {{tight_it_ref}} of {{as_base_it}}), {{tight_share}} of links still differ from the final flows by more than max(10 pcu/h, 2%), the largest difference is {{tight_max}} pcu/h, and {{tight_vc_links}} links differ by 0.05 or more in V/C, which is the size of the scenario effects being measured. All three scenarios are therefore solved to {{cfg_rgap}} (`results/assignment_tightness.csv`). The path of the iterations depends on the last digits of floating-point arithmetic, so a re-run on another machine stops at slightly different flows, within the gap; iteration counts differ too. The saved flows are stored with the demand they were solved for (`results/car_demand_*.npy`), so the equilibrium can be re-checked exactly on any machine.

**Verification on Sioux Falls** (bstabler/TransportationNetworks, pinned commit; `tests/test_sioux_falls.py`). The published best-known flows have relative gap {{sf_gap_pub}} and Beckmann objective {{sf_obj_pub}} (x 10^5) in this code, the published optimum being {{sf_obj}}. Run to gap {{sf_bfw6_gap}} ({{sf_bfw6_it}} iterations), this code reaches objective {{sf_bfw6_obj}} (relative difference {{sf_bfw6_rel}}) with every link flow within {{sf_bfw6_maxrel}} ({{sf_bfw6_maxabs}} vehicles) of the published one. To gap 1e-4, bi-conjugate FW needs {{sf_bfw4_it}} iterations and plain FW {{sf_fw4_it}}.

AequilibraE 1.7.2 also installs on Windows with Python 3.11 (tried in a separate environment, because it pulls NumPy 2.4 and pandas 3.1), and its bi-conjugate Frank-Wolfe ran on Sioux Falls in a one-off trial (relative gap 2.2e-05 after 500 iterations; its flows were not compared further, and the trial is not part of this repository). The model uses its own implementation so that every formula is hand-checked and mutation-tested inside this repository.

### f. Validation

Summary here; details, tables and the reasoning are in [docs/validation_report.md](docs/validation_report.md).

- **Public transport (bus rides).** Calibrated on July, checked on August: coincidence ratio of the trip-length distributions {{val_cr}}; planning-area pairs R2 {{val_r2pa}} (R2 {{val_r2pa_inter}} without the intra-planning-area pairs) and GEH < 5 for {{val_geh5}} of {{val_pairs}} pairs; subzone pairs R2 {{val_r2z}}. The doubly constrained model with one distance function reproduces the broad pattern between planning areas, not the detail between subzones.
- **Roads.** There are no public traffic counts, so nothing here is calibrated to counts. Plausibility only: {{vc_over085_base}} of directed link-km is above V/C 0.85 in the 2020 base, concentrated on expressways (see the map); flow-weighted mean speeds are {{motorway_speed}} km/h on expressways and {{primary_speed}} km/h on primary roads; assigned flows across two north-south screenlines exceed the OD demand that must cross them, as they should when routes cross a line more than once.

### g. 2030: Tengah and the Jurong Region Line

- **Tengah**: HDB's {{tg_homes}} homes (HDB, Tengah annex, 2024) spread over Tengah's MP2019 residential parcels by floor area, {{cfg_persons}} persons per home (ASSUMPTION) and the West Region's 2020 ratio of commuters to residents ({{tg_per_res}}): {{tg_comm}} extra commuters; {{tg_jobs}} jobs on Tengah's own non-residential parcels; other attractions scaled up to balance. Full build-out by 2030 is an upper bound (ASSUMPTION). Everything outside Tengah is held at 2020 levels, so the scenarios isolate Tengah and the JRL.
- **Jurong Region Line**: {{jrl_n}} stations in three stages, 2028 to 2029, per LTA's project page (retrieved 2026-11-15); the in-fill station JS2A (mid-2030s) is left out. Distribution is held fixed between the two 2030 runs; the JRL acts through mode choice only.
- **Result**: average generalised PT time change for West Region commuters {{jrl_dt_west}} min (Tengah {{jrl_dt_tengah}} min; {{jrl_save5}} of West commuters save 5 minutes or more). Mode share of West residents: car {{ms_dm_west_residents_car}} -> {{ms_ds_west_residents_car}}, PT {{ms_dm_west_residents_pt}} -> {{ms_ds_west_residents_pt}}.

{{west_mode_table}}

**Junction growth factors.** Signalised junctions are clusters of OSM traffic-signal nodes within 60 m (expressway carriageways excluded). For the {{jn}} clusters in the West Region with 3+ approaches and 500+ pcu/h, `results/junction_growth_factors.csv` lists each approach's modelled flow in the three scenarios and the growth factors (2030 / 2020); the median junction factor without the JRL is {{jgf_med}} (largest {{jgf_max}}).

**Worked example**: how growth factors feed a junction capacity check, at the junction with the largest growth in entering flow ({{junction_name}}, near {{junction_xy}}).

1. Base turning flows are estimated from the modelled approach and exit flows by Furness balancing with U-turns banned. In a real study these would be a surveyed turning count; here they are model outputs standing in for one (ILLUSTRATIVE).
2. Each approach's turning flows are multiplied by its growth factor, then balanced again to the forecast exit flows (`results/junction_example_turns.csv`).
3. Each scenario is checked with the critical flow-ratio method: opposing approaches share a phase, approach lanes are the OSM lane count of the approach link (which may include turning pockets), saturation flow {{cfg_sat}} pcu/h per approach lane (HCM 2000 base value; ASSUMPTION for Singapore), {{cfg_lost}} s lost per phase, Webster's optimum cycle, degree of saturation X per approach and Webster's delay (`stm/junction.py`).

{{junction_table}}

{{junction_check_table}}

## Data provenance

REAL = published or observed data, used as published. DERIVED = computed here from REAL data. ASSUMPTION = chosen by the author, no source. ILLUSTRATIVE = used only in the worked example. **No input is synthetic data presented as observed.** SHA-256 hashes: `data/inputs/raw_sources.csv` (raw downloads) and `data/inputs/manifest.csv` (committed inputs). Licences and attribution: [DATA_SOURCES.md](DATA_SOURCES.md).

| Input | Status | Source | Accessed |
|---|---|---|---|
| Subzone and planning-area boundaries, Master Plan 2019 (No Sea) | REAL | URA via data.gov.sg, datasets `d_8594ae9ff96d0c708bc2af633048edfb`, `d_4765db0e87b9c86336792efe8a1f7a66` | 2026-11-14 |
| Master Plan 2019 land use (parcels, use, gross plot ratio) | REAL | URA via data.gov.sg, `d_90d86daa5bfaa371668b84fa5f01424f` | 2026-11-14 |
| Employed residents by planning area of residence and usual mode of transport to work (Census 2020) | REAL | SingStat via data.gov.sg, `d_1f8f5ec7201964e365c77551cab99503` | 2026-11-15 |
| Employed residents by planning area of workplace, usual mode and region of residence (Census 2020) | REAL | SingStat via data.gov.sg, `d_5b38192e9c6f8d2c5f38c70939c76e71` | 2026-11-15 |
| Resident population by subzone, age group and sex; by subzone and type of dwelling (Census 2020) | REAL | SingStat Table Builder 17560 and 17562, https://tablebuilder.singstat.gov.sg/table/CT/17560 | 2026-11-15 |
| Passenger volume by origin-destination bus stops, July and August 2026; bus stops | REAL (aggregated to zones here; raw files not redistributed) | LTA DataMall (downloaded 2026-09-26 with the owner's own AccountKey) | 2026-09-26 |
| MRT/LRT station exits (station positions) | REAL | LTA via data.gov.sg, `d_b39d3a0871985372d7e1637193335da5` | 2026-11-09 |
| Road network and JRL station positions | REAL | (c) OpenStreetMap contributors, BBBike extract for Singapore (file dated 2026-09-26) | 2026-09-26 |
| Jurong Region Line stages and station codes | REAL | LTA, https://www.lta.gov.sg/content/ltagov/en/upcoming_projects/rail_expansion/jurong_region_line.html | 2026-11-15 |
| Tengah: about 42,000 homes when fully developed | REAL | HDB, Annex B to a 2024 news release, https://www.hdb.gov.sg/-/media/hdb-pulse/news/2024/four-tengah-bto-projects-awarded-top-tier-active-beautiful-clean-waters-certification/Annex-B.pdf | 2026-11-15 |
| Sioux Falls test network and best-known flows | REAL (test data; "for academic research purposes only", downloaded, not committed) | https://github.com/bstabler/TransportationNetworks, commit 977ee75 | 2026-11-15 |
| BPR parameters 0.15 and 4 | REAL (standard) | Bureau of Public Roads (1964), Traffic Assignment Manual | - |
| Peak-hour share, AM peak hour | DERIVED | from the DataMall bus volumes above | - |
| Rail line order | DERIVED | LTA station codes | - |
| Base turning flows in the junction example | ILLUSTRATIVE | modelled flows standing in for a count | - |

Every model parameter, with its status and note, generated from `config/model.json`:

{{assumption_table}}

## Limitations

- **No road counts.** The road results are plausible-looking model outputs, not validated flows. V/C depends directly on the background factor, the per-lane capacities and the car occupancy, all assumptions.
- **Commuters only.** Students, business, shopping and leisure trips, goods vehicles, and the non-resident workforce are outside the demand model (the background factor stands in for their road traffic). Census 2020 counts residents only.
- **2020 demand, 2026 network.** The road network is OpenStreetMap as of September 2026; the rail network is set back to 2020 by leaving out stations that opened later. Census 2020 describes 2020 travel; whether it reflects travel in other years was not examined.
- **Coarse targets.** The commuter matrix is observed only at region x planning-area level; subzone-level flows are the model's.
- **No feedback.** Mode choice uses free-flow car times, and distribution uses distance, so congestion does not feed back into destination or mode choice; the JRL does not change where people work in the model.
- **Weak time coefficient.** See the profile above: the scenario's mode shift is uncertain by a factor of about five.
- **PT skims are generalised times built from assumptions** (speeds, waits, weights, transfer penalty), not timetables.
- **Tengah at full build-out by 2030** is an upper bound; all other land use is frozen at 2020.
- **Bus rides are not journeys.** The bus sub-model and its validation describe rides; they say nothing direct about whole PT journeys.
- **Junction analysis** uses link-level assignment and Furness-estimated turns, not junction modelling software, and assumed phasing and saturation flows.

## How to run

Python 3.11.

```bash
python -m venv .venv
. .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/run_all.py         # model, figures, README.md and docs/validation_report.md (offline, a few minutes)
python scripts/fetch_data.py --only sioux_falls   # test network (needs internet), then:
pytest                            # tests (offline)
python mutation/run_mutants.py    # optional: mutation test of the test suite
```

`scripts/run_all.py` rewrites everything under `results/` from the committed inputs in `data/inputs/`; numbers are deterministic. Two files are exceptions: `results/sioux_falls_check.json` is rewritten only when the Sioux Falls files have been downloaded, and `results/mutation_report.json` only by `mutation/run_mutants.py`. To rebuild the inputs from the raw sources: `pip install -r requirements-tools.txt`, `python scripts/fetch_data.py` (keyless downloads), then `python scripts/prepare_inputs.py --datamall-dir <folder>` with the DataMall files downloaded with your own DataMall AccountKey (none is stored here).

## Tests and mutation testing

{{tests}} tests (one of them, the full re-run of the three assignments, runs only with `STM_FULL=1`). The formula tests compare against numbers worked out by hand in the test file (Furness balancing, deterrence functions, coincidence ratio, GEH, logit shares, BPR time, integral and derivative, relative gap and line search on a two-link network, a Braess-type network, Webster's cycle and delay, Furness turning flows), parameter-recovery tests for the three calibration routines, the Sioux Falls check, and a rebuild of the model from the committed inputs compared with the committed results and this README. In that rebuild the three saved equilibria are not solved again: each is re-checked independently against its saved demand with one all-or-nothing load, and the base year is solved again from scratch to {{cfg_rgap_ref}} and compared with the saved flows. The suite, including the opt-in re-run, also passes on Linux (a one-off check on Ubuntu 24.04 with Python 3.11 from a clean export of the repository; not repeated by any script here). There the three assignments took different numbers of iterations and ended within 16 pcu/h of the saved flows on every link, with no link differing by 0.05 in V/C.

`mutation/run_mutants.py` copies the repository, plants one deliberate bug at a time in the core logic and runs the suite. **{{mut_killed}} of {{mut_total}} mutants killed** ({{mut_killed_ns}} of {{mut_total}} also with the snapshot tests switched off, i.e. by the hand-worked and property tests alone; the snapshot tests compare a fresh run with the committed results and README). Survivors: {{mutation_survivors}}. Details: `results/mutation_report.json`.

## Licence

Code: MIT (see [LICENSE](LICENSE)). Data: the derived inputs in `data/inputs/` stay under their sources' terms: Singapore Open Data Licence v1.0 for URA, SingStat, LTA and LTA DataMall data, and the Open Database Licence for data derived from OpenStreetMap ((c) OpenStreetMap contributors). See [DATA_SOURCES.md](DATA_SOURCES.md).
