# Land use and transport together: how a new town moves through the model

<!-- docs/land_use_transport_note.md is generated from docs/land_use_transport_note.template.md by scripts/run_all.py. -->

Personal desk study, not an LTA or URA model. This note follows one land-use change, the build-out of Tengah, through each step of the model to the road network and to the economic appraisal of the Jurong Region Line (JRL). Every number is generated from `results/`. The assumptions behind them are in the README; the largest is that the whole town is occupied by 2030 and nothing else in Singapore changes.

## The chain

| Step | What the land-use change does | Number |
|---|---|---|
| Land use | HDB's planned homes are placed on Tengah's Master Plan 2019 residential parcels in proportion to floor area | {{tg_homes}} homes, {{tg_pop}} residents |
| Trip generation | residents x the West Region's 2020 commuters per resident ({{tg_per_res}}); jobs on Tengah's own non-residential parcels | {{tg_comm}} new commuters ({{comm_growth_pct}} more island-wide), {{tg_jobs}} jobs in Tengah |
| Distribution | the gravity model spreads the new commuters over workplaces with the 2020 deterrence function; at most {{tg_jobs}} of them can work in the town, so most leave it every morning | {{comm_2030}} daily commuters in 2030 |
| Mode choice, no new line | Tengah residents' modes without the JRL | car {{ms_dm_tengah_car}}, public transport {{ms_dm_tengah_pt}} |
| Road network, no new line | extra car trips in the AM peak hour, assigned to equilibrium | {{tengah_car_trips}} more car trips/h ({{car_growth_pct}} more); vehicle-hours up by {{vht_dm_vs_base}} ({{vht_dm_vs_base_pct}}); mean V/C in the West {{west_vc_base}} -> {{west_vc_dm}}; directed km above V/C 0.85 in the West {{west_085_base}} -> {{west_085_dm}} |
| Junctions | approach flows at signalised junctions in the West | median growth factor {{jgf_med}}, largest {{jgf_max}} |
| Transport response | the JRL shortens public-transport journeys in the West | Tengah residents' public-transport share {{ms_dm_tengah_pt}} -> {{ms_ds_tengah_pt}} ({{jrl_tengah_pt_pts}} points); {{jrl_car_trips}} car trips/h; km above V/C 0.85 in the West {{west_085_dm}} -> {{west_085_ds}} |
| Appraisal | user benefits of the JRL by the rule of a half, discounted over {{ap_years}} years | present value of benefits S$ {{ap_pvb}} million |

## What the land-use change is worth to the transport scheme

The appraisal can be run with and without the new town. Public-transport user benefits of the JRL, the component that carries {{ap_pt_share}} of the total, are:

| Land use | Public-transport user benefit, S$ million a year | Present value, S$ million |
|---|---|---|
| 2030 with Tengah | {{ap_lu_with}} | {{ap_lu_pvb_with}} |
| 2020 land use, no Tengah | {{ap_lu_without}} | {{ap_lu_pvb_without}} |
| Difference | {{ap_lu_diff}} | {{ap_lu_pvb_diff}} |

So {{ap_lu_share}} of the line's public-transport user benefit exists because the town is there. Tengah's residents are {{ap_tengah_comm_share}} of 2030 commuters and receive {{ap_tengah_share}} of the user benefit: S$ {{ap_tengah_per}} per commuter a year against S$ {{ap_all_per}} on average.

The road side of this comparison was not made. It would need a fourth equilibrium assignment (2020 land use with the line), which is not among the saved results.

## What this says about planning the two together

- **The town creates the demand the line serves, and the line does not remove the road traffic the town adds.** Tengah adds {{tengah_car_trips}} car trips an hour; the JRL takes {{ap_dq}} off. In this model the line is a public-transport benefit for the West, not a congestion remedy.
- **Jobs in the town are the lever this study did not test.** With {{tg_comm}} commuters and {{tg_jobs}} jobs, nearly every working resident crosses the town boundary. More employment land in or beside Tengah would shorten trips at the distribution step, before any mode shift. This was not tested here.
- **Timing changes the result.** The appraisal credits the line with the benefits of a town that is fully occupied in the opening year. If homes are occupied over a decade, the early-year benefits are nearer the "no Tengah" row.

## Limits

- Distribution is held fixed between the two 2030 runs, so the line does not change where people work, and no land-value or development response to the line is modelled. The interaction here runs one way: from land use to transport.
- Only resident commuters are modelled. Trips to school, shops and services in the new town are outside the model.
- The mode-choice time coefficient is weakly identified (see the README), so the mode shift, and with it the {{ap_dq}} car trips, is uncertain. The user benefit to existing public-transport passengers ({{ap_pt_existing_share}} of the public-transport benefit) does not depend on that coefficient; it depends on the assumed public-transport times.
