# Land use and transport together: how a new town moves through the model

<!-- docs/land_use_transport_note.md is generated from docs/land_use_transport_note.template.md by scripts/run_all.py. -->

Personal desk study, not an LTA or URA model. This note follows one land-use change, the build-out of Tengah, through each step of the model to the road network and to the economic appraisal of the Jurong Region Line (JRL). Every number is generated from `results/`. The assumptions behind them are in the README; the largest is that the whole town is occupied by 2030 and nothing else in Singapore changes.

## The chain

| Step | What the land-use change does | Number |
|---|---|---|
| Land use | HDB's planned homes are placed on Tengah's Master Plan 2019 residential parcels in proportion to floor area | 42,000 homes, 130,200 residents |
| Trip generation | residents x the West Region's 2020 commuters per resident (0.470); jobs on Tengah's own non-residential parcels | 61,215 new commuters (3.3% more island-wide), 3,892 jobs in Tengah |
| Distribution | the gravity model spreads the new commuters over workplaces with the 2020 deterrence function; at most 3,892 of them can work in the town, so most leave it every morning | 1,892,580 daily commuters in 2030 |
| Mode choice, no new line | Tengah residents' modes without the JRL | car 18.9%, public transport 70.0% |
| Road network, no new line | extra car trips in the AM peak hour, assigned to equilibrium | 3,758 more car trips/h (2.3% more); vehicle-hours up by 1,304 (3.0%); mean V/C in the West 0.166 -> 0.174; directed km above V/C 0.85 in the West 25.7 -> 30.8 |
| Junctions | approach flows at signalised junctions in the West | median growth factor 1.026, largest 2.22 |
| Transport response | the JRL shortens public-transport journeys in the West | Tengah residents' public-transport share 70.0% -> 70.4% (+0.39 points); -526 car trips/h; km above V/C 0.85 in the West 30.8 -> 29.3 |
| Appraisal | user benefits of the JRL by the rule of a half, discounted over 60 years | present value of benefits S$ 2,002 million |

## What the land-use change is worth to the transport scheme

The appraisal can be run with and without the new town. Public-transport user benefits of the JRL, the component that carries 99.2% of the total, are:

| Land use | Public-transport user benefit, S$ million a year | Present value, S$ million |
|---|---|---|
| 2030 with Tengah | 86.4 | 1,986 |
| 2020 land use, no Tengah | 77.3 | 1,776 |
| Difference | 9.1 | 210 |

So 10.6% of the line's public-transport user benefit exists because the town is there. Tengah's residents are 3.2% of 2030 commuters and receive 13.2% of the user benefit: S$ 187 per commuter a year against S$ 46 on average.

The road side of this comparison was not made. It would need a fourth equilibrium assignment (2020 land use with the line), which is not among the saved results.

## What this says about planning the two together

- **The town creates the demand the line serves, and the line does not remove the road traffic the town adds.** Tengah adds 3,758 car trips an hour; the JRL takes 526 off. In this model the line is a public-transport benefit for the West, not a congestion remedy.
- **Jobs in the town are the lever this study did not test.** With 61,215 commuters and 3,892 jobs, nearly every working resident crosses the town boundary. More employment land in or beside Tengah would shorten trips at the distribution step, before any mode shift. This was not tested here.
- **Timing changes the result.** The appraisal credits the line with the benefits of a town that is fully occupied in the opening year. If homes are occupied over a decade, the early-year benefits are nearer the "no Tengah" row.

## Limits

- Distribution is held fixed between the two 2030 runs, so the line does not change where people work, and no land-value or development response to the line is modelled. The interaction here runs one way: from land use to transport.
- Only resident commuters are modelled. Trips to school, shops and services in the new town are outside the model.
- The mode-choice time coefficient is weakly identified (see the README), so the mode shift, and with it the 526 car trips, is uncertain. The user benefit to existing public-transport passengers (97.0% of the public-transport benefit) does not depend on that coefficient; it depends on the assumed public-transport times.
