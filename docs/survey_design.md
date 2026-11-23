# Household travel survey: design, and analysis on synthetic respondents

<!-- docs/survey_design.md is generated from docs/survey_design.template.md by scripts/run_all.py. -->

**No survey was carried out.** This note designs a household travel survey over the model's 332 zones and then tests the analysis method on SYNTHETIC respondents drawn from the model's own population and trip tables. Because the respondents are simulated, the true answer is known, so the note can say how far each estimator is from it. Nothing here is an observation of real travel. Code: `stm/survey.py`; parameters: `config/survey.json`; outputs: `results/survey*.csv` and `results/survey.json`.

## 1. What the survey is for

Two quantities the strategic model needs and the Census cannot refresh between census years, for each of the five planning regions:

- the mode share of commuters (car, public transport, other), which the mode-choice model is calibrated to;
- the commuting trip rate (trips per resident per weekday), which trip generation rests on.

## 2. Sample size

Targets (ASSUMPTION): the car share of commuters in each region within +/- 2.5 percentage points, and the trip rate in each region within +/- 5% of itself, both at 95% confidence.

- A proportion p needs n = deff x z^2 p (1 - p) / e^2 commuters; a mean needs n = deff x (z x cv / e)^2 persons, with the finite population correction applied to the simple-random-sample size. The planning value of p is the Census 2020 car share of the region.
- People are sampled in households, so answers are clustered: deff = 1 + (m - 1) x rho, with rho = 0.3 (ASSUMPTION) and m the number of commuters (or persons) in the household of a sampled commuter (or person). Because households differ in size, that m is E[m^2] / E[m], which is larger than the plain average; it is computed from an assumed distribution of household sizes with a mean of 3.1 persons (ASSUMPTION).
- The larger of the two requirements sets the completed households of a region; dividing by the expected response rate of 55% (ASSUMPTION) gives the households to issue.

| Region | residents | Census car share | design effect (mode share) | households for mode share | design effect (trip rate) | households for trip rate | completed households | issued households | sampling fraction | mode-share margin if the total were allocated in proportion (points) |
|---|---|---|---|---|---|---|---|---|---|---|
| Central | 922,640 | 31.1% | 1.35 | 1,331 | 1.81 | 1,425 | 1,426 | 2,593 | 0.87% | 2.37 |
| East | 685,900 | 28.4% | 1.37 | 1,212 | 1.81 | 1,300 | 1,301 | 2,366 | 1.07% | 2.62 |
| North | 582,320 | 20.0% | 1.37 | 957 | 1.81 | 1,306 | 1,306 | 2,375 | 1.26% | 2.53 |
| North-East | 930,930 | 27.4% | 1.37 | 1,173 | 1.81 | 1,267 | 1,267 | 2,304 | 0.77% | 2.21 |
| West | 922,550 | 24.9% | 1.38 | 1,087 | 1.81 | 1,221 | 1,222 | 2,222 | 0.75% | 2.14 |
| **Total** | 4,044,340 |  |  |  |  |  | **6,522** | **11,860** |  |  |

The binding requirement is the trip rate in every region. The plan needs 6,522 completed households from 11,860 issued. Because each region must meet the same precision, the smaller regions are sampled more heavily (sampling fractions from 0.75% to 1.26%). Allocating the same total in proportion to households would leave the weakest region (East) at +/- 2.62 points on the car share.

## 3. Sampling plan

- **Frame**: households by subzone, estimated as Census 2020 residents / 3.1. A real survey would use an address register; none is public, so this frame is a stand-in.
- **Strata**: the five regions. Within a region every household has the same chance of selection, so a subzone's expected sample is proportional to its households (`results/survey_sampling_plan.csv`, one row per subzone).
- **Unit**: the household; every member aged 6 and over is interviewed about one assigned weekday. (The synthetic file keeps all members and records commuting only.)
- **Small zones**: 71 of the 286 subzones with residents expect less than one issued household. They are still covered, because selection is by household and not by zone, but no estimate can be made for a single subzone. The saved synthetic file has respondents in 209 subzones.

## 4. Questionnaire outline (one page)

| Section | Asked of | Items |
|---|---|---|
| A. Household | one adult | address (for the subzone), dwelling type, number of members, vehicles available (cars, motorcycles, bicycles), household income band |
| B. Person | every member | age band, sex, employment or student status, usual place of work or study (postal code), usual mode to work or school, concession or season pass, driving licence |
| C. Travel diary, assigned weekday | every member aged 6+ | for each trip: start time, origin, destination, purpose, each stage with its mode (walk, bus, MRT/LRT, car driver, car passenger, taxi or private hire, motorcycle, cycle, other), wait and walk time as recalled, fare or parking paid, who travelled together |
| D. No travel | members with no trip | reason (worked from home, leave, illness, no need) so that a true zero is told apart from a skipped diary |
| E. Check-back | the respondent | whether the day was typical; consent to a call-back |

Section D matters for the trip rate: without it, a skipped diary and a day at home look the same.

## 5. Fieldwork quality-control checklist

Before fieldwork
- [ ] Pilot of at least 50 households; time each section; fix every question that interviewers had to explain.
- [ ] Travel days assigned in advance and spread evenly over Monday to Friday and over the fieldwork weeks; school holidays and public holidays excluded or flagged.
- [ ] Interviewer briefing with worked examples of trip stages (a bus-MRT-bus journey is one trip with three stages) and of return trips.

During fieldwork
- [ ] Response rate tracked weekly by region and dwelling type against the 55% planned; reserve sample released by stratum, never by convenience.
- [ ] At least four contact attempts on different days and at different times, including one evening and one weekend, before a household is coded as non-contact.
- [ ] Non-response coded by reason (refusal, non-contact, vacant, language), and dwelling type recorded for every issued address, so that non-response can be described afterwards.
- [ ] Range and logic checks at entry: every trip has an origin, a destination and a mode; start times are in order; the day starts and ends at home unless stated; a commuter's diary on a working day contains a work trip or a reason in section D.
- [ ] Proxy reporting flagged (one member answering for another); trip rates compared between proxy and self-reports.
- [ ] 10% of completed households called back to confirm the interview took place and to re-ask three key items (household size, usual mode, number of trips).
- [ ] Interviewer-level indicators reviewed weekly: trips per person, share of zero-trip diaries, interview length. Outlying interviewers are re-briefed or their work re-contacted.

After fieldwork
- [ ] Geocoding rate of origins and destinations to subzone reported; ungeocoded trips kept and counted, not dropped silently.
- [ ] Sample compared with the Census on region, dwelling type, age and household size before weighting.
- [ ] Weights documented: design weight, non-response adjustment, raking margins, any trimming, and the design effect of the final weights.
- [ ] Weighted mode shares and trip rates compared with independent sources (Census mode shares; public-transport ridership) and the differences reported.

## 6. Synthetic respondents

Each issued household is given a subzone (in proportion to households within its region), a dwelling type (private with the subzone's Census share of residents in condominiums and landed housing) and 1 to 6 members. Each member is of working age with the subzone's Census share aged 20-64; a working-age member commutes with the subzone's modelled commuters per resident aged 20-64, to a workplace drawn from the model's commuter matrix, by a mode drawn from the mode-choice model with the household's own dwelling type in place of the zone average. Commuters of one household share their mode draw with probability chosen to give a correlation of about 0.3. A commuter travels on the survey day with the model's attendance factor (0.9), making two trips.

A household then responds with a probability that falls for private housing, for the Central Region, for households with nobody outside working age, and by -0.3 on the logit scale **for each member who commutes by car**. The last term makes non-response depend on the answer itself; no census margin describes it. All these parameters are invented (SYNTHETIC in `config/survey.json`).

The saved file (`results/survey_synthetic_respondents.csv`, seed 20261123) has 20,672 persons in 6,617 responding households (55.8% of issued), 8,912 of them commuters. Before weighting, 13.7% of its persons live in private housing against 21.2% in the Census, and 63.0% are aged 20-64 against 64.9%.

## 7. Weighting and estimates

- **Design weight**: households in the frame / responding households, by region.
- **Raking** (iterative proportional fitting) of person weights to three Census 2020 margins that the repository already holds: residents by region, by dwelling type (public, private) and by age group (20-64, other). It converged in 7 rounds; the design effect of the raked weights is 1.088 (design weights alone 1.042); weights run from 117 to 364 persons per respondent.
- **Confidence intervals**: linearised variance of a ratio, regions as strata and households as clusters. The weights are treated as fixed, so the intervals describe sampling error only.

| Whole island, saved file | truth | unweighted | design weights | raked weights (95% interval) |
|---|---|---|---|---|
| Car share of commuters | 28.0% | 20.7% | 20.9% | 23.6% (22.5% to 24.8%) |
| Public-transport share of commuters | 63.2% | 69.9% | 70.0% | 67.5% (66.3% to 68.7%) |
| Commuting trips per resident per weekday | 0.815 | 0.776 | 0.776 | 0.802 (0.788 to 0.816) |

In the saved file 6 of the 18 raked intervals (three measures, whole island and five regions) contain the truth.

## 8. Does weighting recover the truth?

One file proves little, so the survey is drawn 200 times with different seeds (mean response rate 56.4%) and each estimator is compared with the truth (`results/survey_accuracy.csv`).

| Whole island, 200 synthetic surveys | truth | bias: unweighted | bias: design weights | bias: raked | bias removed by raking | RMSE: unweighted | RMSE: raked | 95% interval coverage: raked |
|---|---|---|---|---|---|---|---|---|
| Car share of commuters | 28.0% | -6.3 pts | -6.2 pts | -3.5 pts | 44% | 0.0632 | 0.0354 | 0% |
| Public-transport share of commuters | 63.2% | +5.4 pts | +5.4 pts | +3.1 pts | 43% | 0.0543 | 0.0315 | 0% |
| Commuting trips per resident per weekday | 0.815 | -0.036 | -0.036 | -0.010 | 72% | 0.0367 | 0.0115 | 74% |

- **Raking helps, and is not enough for mode shares.** The raked estimate has a lower root mean square error than the unweighted one in 18 of 18 measure-by-area cells (exceptions: none), and lower than design weights alone in 18.
- **Trip rate**: raking removes 72% of the bias, because the missing households differ mainly by age composition, which is a raking margin. Its 95% interval covers the truth 74% of the time, short of the nominal 95%.
- **Car share**: the unweighted sample understates it by 6.3 points (truth 28.0%). Raking to dwelling type removes 44% of that and leaves -3.5 points, and the raked 95% interval covers the truth in 0% of the 200 surveys. The remaining bias is the part of non-response that depends on car commuting itself. No reweighting to population margins can remove it: it needs data on the non-respondents (a follow-up sub-sample, or an outside control total such as vehicle registrations by area).
- **The intervals are too narrow.** They measure sampling error around a biased estimate. Coverage of the raked intervals across all cells ranges from 0% to 95%.
- **The precision target is met in 2 of 5 regions.** After non-response and weighting, the mean half-width of the regional car-share interval is 2.3 to 2.8 points against the target of 2.5. The trip-rate target (+/- 5%) is met in 5 of 5 regions (half-widths 3.6% to 4.0% of the truth). The sample-size formula allows for household clustering with one assumed correlation. It does not allow for the design effect of the weights (1.088 here), and in the synthetic population commuters of one household also share a housing type, which ties their modes together more than the assumed 0.3. A real design should carry an allowance for weighting and take the correlation from a previous survey.

| Region | raked bias of the car share (points) | car share: mean half-width of the 95% interval (points) | target (points) | trip rate: mean half-width as a share of the truth | target |
|---|---|---|---|---|---|
| Central | -4.7 | 2.76 | 2.5 | 4.0% | 5% |
| East | -3.4 | 2.59 | 2.5 | 3.7% | 5% |
| North | -2.8 | 2.26 | 2.5 | 3.6% | 5% |
| North-East | -3.3 | 2.52 | 2.5 | 3.7% | 5% |
| West | -3.2 | 2.41 | 2.5 | 3.6% | 5% |

## 9. What this does not show

- It is not evidence about how Singapore residents travel or respond to surveys. The response model is invented; a different one would give different biases.
- The truth is the expected value of the generating process, which re-interprets the zone-level housing coefficient of the mode-choice model at household level. It is close to, but not the same as, the model's 2020 mode share.
- Only commuting is simulated. Real diaries cover all purposes, and trip under-reporting (short and non-home-based trips) is a larger problem there than here.
- Design effects, the response rate and the intra-household correlation are assumptions with no source.

## Parameters

| Parameter (config/survey.json) | Value | Status | Note |
|---|---|---|---|
| `design.confidence_z` | 1.96 | ASSUMPTION | two-sided 95% confidence |
| `design.target_margin_mode_share` | 0.025 | ASSUMPTION | half-width of the confidence interval of the car share of commuters in each region: 2.5 percentage points |
| `design.target_relative_margin_trip_rate` | 0.05 | ASSUMPTION | half-width of the confidence interval of commuting trips per resident per weekday in each region, as a share of the estimate |
| `design.strata` | the five URA planning regions | ASSUMPTION | households are drawn with equal probability within a region, so the expected sample of a subzone is proportional to its households |
| `design.persons_per_household` | 3.1 | ASSUMPTION | the same value as scenario_2030.persons_per_home in config/model.json; turns Census residents into a household frame |
| `design.household_size_distribution` | 0.14, 0.22, 0.24, 0.25, 0.1, 0.05 | ASSUMPTION | probabilities of households of 1 to 6 persons, mean 3.1; not taken from a Census table. Used for the design effect, where the cluster size that matters is E[m^2] / E[m], and to build the synthetic households |
| `design.intra_household_correlation` | 0.3 | ASSUMPTION | correlation of commuting mode between two commuters of one household, used in the design effect 1 + (m - 1) rho, also applied to the trip rate; no source |
| `design.expected_response_rate` | 0.55 | ASSUMPTION | share of issued households expected to complete the survey; no source |
| `design.allocation` | equal precision by region | ASSUMPTION | each region gets the sample that meets both precision targets; proportional allocation of the same total is reported for comparison |
| `synthetic.seed` | 20261123 | SYNTHETIC | seed of the saved respondent file; replicate r of the repeated-sampling check uses seed + r |
| `synthetic.replicates` | 200 | SYNTHETIC | independent synthetic surveys drawn to measure bias, root mean square error and confidence-interval coverage |
| `synthetic.mode_copy_probability` | 0.55 | SYNTHETIC | probability that a commuter's mode is drawn with the household's random number instead of the commuter's own; two commuters of one household then share their draw with probability 0.55 squared, about 0.30 |
| `synthetic.response_intercept` | 0.75 | SYNTHETIC | logit of a household's response probability: intercept |
| `synthetic.response_private_housing` | -0.7 | SYNTHETIC | added for households in condominiums and landed housing (harder to reach) |
| `synthetic.response_central_region` | -0.3 | SYNTHETIC | added for households in the Central Region |
| `synthetic.response_no_resident_outside_working_age` | -0.5 | SYNTHETIC | added when every member is aged 20-64 (nobody at home in the daytime) |
| `synthetic.response_per_car_commuter` | -0.3 | SYNTHETIC | added for each member who commutes by car. This is the part of non-response that depends on the answer itself and that no census margin describes |
| `weighting.margins` | region, dwelling type (public, private), age group (20-64, other) | REAL | Census of Population 2020 residents by subzone, age group and type of dwelling (SingStat Table Builder 17560 and 17562), already in data/inputs/ |
| `weighting.raking_tolerance` | 1e-10 | ASSUMPTION | largest relative difference between a weighted margin and its census total at which raking stops |

Methods: Cochran, W.G. (1977), *Sampling Techniques*, 3rd edition (sample size, stratification, ratio estimation); Kish, L. (1965), *Survey Sampling* (design effects); Deming, W.E. and Stephan, F.F. (1940), On a least squares adjustment of a sampled frequency table when the expected marginal totals are known, *Annals of Mathematical Statistics* 11(4), 427-444 (raking). Cited as standard references; not re-read for this note.
