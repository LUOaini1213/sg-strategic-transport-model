# Data sources, licences and attribution

Personal desk study. SHA-256 hashes of every raw file read are in `data/inputs/raw_sources.csv`, and of every committed input in `data/inputs/manifest.csv` (hashes of the LF-normalised bytes). Raw downloads live in `data/raw/` (git-ignored) and are fetched again by `scripts/fetch_data.py`; `scripts/prepare_inputs.py` turns them into the committed inputs in `data/inputs/`.

## Redistributed here as derived extracts (`data/inputs/`)

| Committed file(s) | Made from | Publisher, licence |
|---|---|---|
| `zones.csv`, `zones_geometry.json`, `landuse_subzone.csv`, `tengah_parcels.csv` | Master Plan 2019 Subzone Boundary (No Sea) `d_8594ae9ff96d0c708bc2af633048edfb`, Planning Area Boundary (No Sea) `d_4765db0e87b9c86336792efe8a1f7a66` and Land Use layer `d_90d86daa5bfaa371668b84fa5f01424f`; converted to SVY21, land-use parcels assigned to subzones by representative point and summed by land-use class; outlines simplified to 25 m for maps | Urban Redevelopment Authority, data.gov.sg, Singapore Open Data Licence v1.0 |
| `census2020_mode_residence_pa.csv`, `census2020_workplace_region_mode.csv` | Census of Population 2020 tables on data.gov.sg: "Employed Residents Aged 15 Years and Over by Planning Area of Residence and Usual Mode of Transport to Work" `d_1f8f5ec7201964e365c77551cab99503`; "Employed Residents Aged 15 Years and Over by Planning Area of Workplace, Usual Mode of Transport to Work and Planning Region of Residence" `d_5b38192e9c6f8d2c5f38c70939c76e71`; values as published, reshaped | Singapore Department of Statistics, data.gov.sg, Singapore Open Data Licence v1.0 |
| `census2020_population_subzone.csv`, `census2020_population_dwelling_subzone.csv` | SingStat Table Builder 17560 "Resident Population by Planning Area/Subzone of Residence, Age Group and Sex" and 17562 "Resident Population by Planning Area/Subzone of Residence and Type of Dwelling" (both Census of Population 2020); age groups summed | Singapore Department of Statistics. SingStat's Terms of Use (https://www.singstat.gov.sg/terms-of-use, read 2026-11-15) make use of its datasets subject to the Singapore Open Data Licence |
| `bus_od_202607.csv`, `bus_od_202608.csv`, `bus_hourly_*.csv`, `bus_stop_tld_*.csv` | LTA DataMall "Passenger Volume by Origin Destination Bus Stops" (July and August 2026) and "Bus Stops" (2026-09-26): weekday rides aggregated to subzone pairs for 07:00 and 08:00 tap-in hours, weekday totals by hour, and stop-to-stop distance histograms. **The stop-level files are not redistributed.** | Land Transport Authority. DataMall's API Terms of Service (https://datamall.lta.gov.sg/content/datamall/en/api-terms-of-service.html, read 2026-11-15), clause 1: use of the datasets is governed by the Singapore Open Data Licence |
| `lta_station_positions.csv` | LTA MRT Station Exit (GEOJSON) `d_b39d3a0871985372d7e1637193335da5`: mean position of each station's exits | Land Transport Authority, data.gov.sg, Singapore Open Data Licence v1.0 |
| `road_nodes.csv`, `road_links.csv`, `road_geometry.json`, `rail_stations_osm.csv`, `rail_station_names_osm.csv` | OpenStreetMap: ways tagged motorway to tertiary (and links), traffic-signal nodes, and rail station features with their `ref` codes, from BBBike's extract for Singapore (https://download.bbbike.org/osm/bbbike/Singapore/Singapore.osm.gz, file dated 2026-09-26) | (c) OpenStreetMap contributors. These files are a derived database and remain under the Open Database Licence 1.0 (https://opendatacommons.org/licenses/odbl/1-0/); see https://www.openstreetmap.org/copyright |

Attribution in the form the Singapore Open Data Licence asks for: *Contains information from Master Plan 2019 Subzone Boundary (No Sea), Master Plan 2019 Planning Area Boundary (No Sea), Master Plan 2019 Land Use layer, LTA MRT Station Exit and the two Census of Population 2020 tables listed above, accessed between 9 and 15 November 2026 from data.gov.sg; SingStat Table Builder tables 17560 and 17562, accessed on 15 November 2026 from tablebuilder.singstat.gov.sg; and LTA DataMall Passenger Volume by Origin Destination Bus Stops and Bus Stops, accessed on 26 September 2026 from datamall.lta.gov.sg, which are made available under the terms of the Singapore Open Data Licence version 1.0 (https://data.gov.sg/open-data-licence).*

Nothing here suggests that any analysis is endorsed by or attributed to the Government of Singapore or its agencies.

## Read, cited, not redistributed

| Source | Used for | Read |
|---|---|---|
| LTA, Jurong Region Line project page, https://www.lta.gov.sg/content/ltagov/en/upcoming_projects/rail_expansion/jurong_region_line.html (HTML retrieved 2026-11-15, SHA-256 `7faf58fa1bf59b5e12afe239847562b5fd3cce886d9c01aa8fc4a1280f32c56c`) | stages and station codes: Stage 1 (2028) JS1-JS8 excluding JS2A and JW1-JW2, Stage 2 (2028) JE1-JE7, Stage 3 (2029) JS9-JS12 and JW3-JW5; JS2A in-fill station mid-2030s; 25 stations, 24 km; interchanges at Choa Chu Kang, Boon Lay and Jurong East | 2026-11-15 |
| HDB, Annex B to the 2024 news release on four Tengah BTO projects and ABC Waters certification, https://www.hdb.gov.sg/-/media/hdb-pulse/news/2024/four-tengah-bto-projects-awarded-top-tier-active-beautiful-clean-waters-certification/Annex-B.pdf (SHA-256 `bfb41ef8c3abf1ffa09d4bc6bbab0ef4abc32e88f2a65119d6e120a9901c006b`) | Tengah "is estimated to provide about 42,000 new homes when fully developed"; HDB's Tengah Town Design Guide gives the same 42,000 dwelling units | 2026-11-15 |
| Ministry of Manpower, Public holidays, https://www.mom.gov.sg/employment-practices/public-holidays | National Day on Sunday 9 August 2026; Monday 10 August 2026 a public holiday if the rest day falls on 9 August (used for the weekday count; DataMall's own classification of that day was not verified) | 2026-11-15 |
| TransportationNetworks (bstabler), SiouxFalls, commit `977ee75c6906337c0c7d229a1336107c7cdb533e` | test network, demand and best-known flows (average excess cost 3.9e-15, objective 42.31335287107440). The repository's README says the data sets are "for academic research purposes only", so the files are downloaded for the test and never committed | 2026-11-15 |
| Bureau of Public Roads (1964), *Traffic Assignment Manual*, U.S. Department of Commerce | BPR link-performance function and its usual parameters 0.15 and 4 | cited |
| Mitradjieva, M. and Lindberg, P.O. (2013), The stiff is moving: conjugate direction Frank-Wolfe methods with applications to traffic assignment, *Transportation Science* 47(2), 280-293 | bi-conjugate Frank-Wolfe directions | cited |
| Webster, F.V. (1958), *Traffic Signal Settings*, Road Research Technical Paper 39 | optimum cycle and delay formula | cited |
| Transportation Research Board (2000), *Highway Capacity Manual 2000* | base saturation flow of 1,900 pc/h/ln, used here as an assumption | cited |

## Not used

- No traffic counts (none are published for Singapore roads).
- No LTA DataMall train origin-destination data, traffic speed bands or traffic images.
- No DataMall AccountKey is stored in this repository or used by its scripts.
