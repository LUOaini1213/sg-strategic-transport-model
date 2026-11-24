# Household travel survey: design, and analysis on synthetic respondents

<!-- docs/survey_design.md is generated from docs/survey_design.template.md by scripts/run_all.py. -->

**No survey was carried out.** This note designs a household travel survey over the model's {{n_zones}} zones and then tests the analysis method on SYNTHETIC respondents drawn from the model's own population and trip tables. Because the respondents are simulated, the true answer is known, so the note can say how far each estimator is from it. Nothing here is an observation of real travel. Code: `stm/survey.py`; parameters: `config/survey.json`; outputs: `results/survey*.csv` and `results/survey.json`.

## 1. What the survey is for

Two quantities the strategic model needs and the Census cannot refresh between census years, for each of the five planning regions:

- the mode share of commuters (car, public transport, other), which the mode-choice model is calibrated to;
- the commuting trip rate (trips per resident per weekday), which trip generation rests on.

## 2. Sample size

Targets (ASSUMPTION): the car share of commuters in each region within +/- {{sv_margin_target}} percentage points, and the trip rate in each region within +/- {{sv_trip_target}} of itself, both at 95% confidence.

- A proportion p needs n = deff x z^2 p (1 - p) / e^2 commuters; a mean needs n = deff x (z x cv / e)^2 persons, with the finite population correction applied to the simple-random-sample size. The planning value of p is the Census 2020 car share of the region.
- People are sampled in households, so answers are clustered: deff = 1 + (m - 1) x rho, with rho = {{sv_rho}} (ASSUMPTION) and m the number of commuters (or persons) in the household of a sampled commuter (or person). Because households differ in size, that m is E[m^2] / E[m], which is larger than the plain average; it is computed from an assumed distribution of household sizes with a mean of {{sv_pph}} persons (ASSUMPTION).
- The larger of the two requirements sets the completed households of a region; dividing by the expected response rate of {{sv_rr_expected}} (ASSUMPTION) gives the households to issue.

{{sv_size_table}}

The binding requirement is the {{sv_binding}} in every region. The plan needs {{sv_completed}} completed households from {{sv_issued}} issued. Because each region must meet the same precision, the smaller regions are sampled more heavily (sampling fractions from {{sv_frac_min}} to {{sv_frac_max}}). Allocating the same total in proportion to households would leave the weakest region ({{sv_prop_region}}) at +/- {{sv_prop_worst}} points on the car share.

## 3. Sampling plan

- **Frame**: households by subzone, estimated as Census 2020 residents / {{sv_pph}}. A real survey would use an address register; none is public, so this frame is a stand-in.
- **Strata**: the five regions. Within a region every household has the same chance of selection, so a subzone's expected sample is proportional to its households (`results/survey_sampling_plan.csv`, one row per subzone).
- **Unit**: the household; every member aged 6 and over is interviewed about one assigned weekday. (The synthetic file keeps all members and records commuting only.)
- **Small zones**: {{sv_zones_under1}} of the {{sv_zones_res}} subzones with residents expect less than one issued household. They are still covered, because selection is by household and not by zone, but no estimate can be made for a single subzone. The saved synthetic file has respondents in {{sv_zones_saved}} subzones.

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
- [ ] Response rate tracked weekly by region and dwelling type against the {{sv_rr_expected}} planned; reserve sample released by stratum, never by convenience.
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

Each issued household is given a subzone (in proportion to households within its region), a dwelling type (private with the subzone's Census share of residents in condominiums and landed housing) and 1 to 6 members. Each member is of working age with the subzone's Census share aged 20-64; a working-age member commutes with the subzone's modelled commuters per resident aged 20-64, to a workplace drawn from the model's commuter matrix, by a mode drawn from the mode-choice model with the household's own dwelling type in place of the zone average. Commuters of one household share their mode draw with probability chosen to give a correlation of about {{sv_rho}}. A commuter travels on the survey day with the model's attendance factor ({{attendance}}), making two trips.

A household then responds with a probability that falls for private housing, for the Central Region, for households with nobody outside working age, and by {{sv_car_effect}} on the logit scale **for each member who commutes by car**. The last term makes non-response depend on the answer itself; no census margin describes it. All these parameters are invented (SYNTHETIC in `config/survey.json`).

The saved file (`results/survey_synthetic_respondents.csv`, seed {{sv_seed}}) has {{sv_persons}} persons in {{sv_resp_hh}} responding households ({{sv_rr_saved}} of issued), {{sv_commuters}} of them commuters. Before weighting, {{sv_priv_unw}} of its persons live in private housing against {{sv_priv_cen}} in the Census, and {{sv_age_unw}} are aged 20-64 against {{sv_age_cen}}.

## 7. Weighting and estimates

- **Design weight**: households in the frame / responding households, by region.
- **Raking** (iterative proportional fitting) of person weights to three Census 2020 margins that the repository already holds: residents by region, by dwelling type (public, private) and by age group (20-64, other). It converged in {{sv_rake_it}} rounds; the design effect of the raked weights is {{sv_deff_raked}} (design weights alone {{sv_deff_design}}); weights run from {{sv_wmin}} to {{sv_wmax}} persons per respondent.
- **Confidence intervals**: linearised variance of a ratio, regions as strata and households as clusters. The weights are treated as fixed, so the intervals describe sampling error only.

{{sv_est_table}}

In the saved file {{sv_inside}} of the {{sv_intervals}} raked intervals (three measures, whole island and five regions) contain the truth.

## 8. Does weighting recover the truth?

One file proves little, so the survey is drawn {{sv_R}} times with different seeds (mean response rate {{sv_rr_mean}}) and each estimator is compared with the truth (`results/survey_accuracy.csv`).

{{sv_acc_table}}

- **Raking helps, and is not enough for mode shares.** The raked estimate has a lower root mean square error than the unweighted one in {{sv_cells_better}} of {{sv_cells}} measure-by-area cells (exceptions: {{sv_worse_list}}), and lower than design weights alone in {{sv_cells_better_design}}.
- **Trip rate**: raking removes {{sv_trip_removed}} of the bias, because the missing households differ mainly by age composition, which is a raking margin. Its 95% interval covers the truth {{sv_trip_cov}} of the time, short of the nominal 95%.
- **Car share**: the unweighted sample understates it by {{sv_car_bias_unw_abs}} points (truth {{sv_car_truth}}). Raking to dwelling type removes {{sv_car_removed}} of that and leaves {{sv_car_bias_raked}} points, and the raked 95% interval covers the truth in {{sv_car_cov}} of the {{sv_R}} surveys. The remaining bias is the part of non-response that depends on car commuting itself. No reweighting to population margins can remove it: it needs data on the non-respondents (a follow-up sub-sample, or an outside control total such as vehicle registrations by area).
- **The intervals are too narrow.** They measure sampling error around a biased estimate. Coverage of the raked intervals across all cells ranges from {{sv_cov_min}} to {{sv_cov_max}}.
- **The precision target is met in {{sv_regions_meeting}} of 5 regions.** After non-response and weighting, the mean half-width of the regional car-share interval is {{sv_margin_lo}} to {{sv_margin_hi}} points against the target of {{sv_margin_target}}. The trip-rate target (+/- {{sv_trip_target}}) is met in {{sv_trip_regions_meeting}} of 5 regions (half-widths {{sv_trip_margin_lo}} to {{sv_trip_margin_hi}} of the truth). The sample-size formula allows for household clustering with one assumed correlation. It does not allow for the design effect of the weights ({{sv_deff_raked}} here), and in the synthetic population commuters of one household also share a housing type, which ties their modes together more than the assumed {{sv_rho}}. A real design should carry an allowance for weighting and take the correlation from a previous survey.

{{sv_margin_table}}

## 9. What this does not show

- It is not evidence about how Singapore residents travel or respond to surveys. The response model is invented; a different one would give different biases.
- The truth is the expected value of the generating process, which re-interprets the zone-level housing coefficient of the mode-choice model at household level. It is close to, but not the same as, the model's 2020 mode share.
- Only commuting is simulated. Real diaries cover all purposes, and trip under-reporting (short and non-home-based trips) is a larger problem there than here.
- Design effects, the response rate and the intra-household correlation are assumptions with no source.

## Parameters

{{sv_param_table}}

Methods: Cochran, W.G. (1977), *Sampling Techniques*, 3rd edition (sample size, stratification, ratio estimation); Kish, L. (1965), *Survey Sampling* (design effects); Deming, W.E. and Stephan, F.F. (1940), On a least squares adjustment of a sampled frequency table when the expected marginal totals are known, *Annals of Mathematical Statistics* 11(4), 427-444 (raking). Cited as standard references; not re-read for this note.
