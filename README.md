# metoffice_geoparquet

Met Office UK land observations → **GeoParquet** with **KNMI parameter names**, refreshed every 3 hours by GitHub Actions and published on GitHub Pages.

- 🌍 Viewer: <https://weatherhorn.github.io/metoffice_geoparquet/>
- 📦 Data: <https://weatherhorn.github.io/metoffice_geoparquet/obs.parquet>

The file has the same layout as the KNMI GeoParquet of [bertt/knmi_zarr](https://github.com/bertt/knmi_zarr), so tools and web pages that read that file (for example its cycling-weather page) can read this one as well.

## Data source and licence

- **Source:** [Met Office Weather DataHub](https://datahub.metoffice.gov.uk/), product *Land Observations* (API `observation-land/1`), hourly observations of UK land stations.
- **Copyright:** Contains Met Office data © Crown copyright. Met Office data is Crown copyright; the Met Office states that hourly UK land observations are free of licence fee.
- **Licence:** data obtained with a DataHub API key is covered by the [Met Office Weather DataHub terms and conditions](https://datahub.metoffice.gov.uk/) (and, where it applies, the [UK Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)). **Check these terms before reusing or redistributing the data**; this repository does not grant any rights to Met Office data.
- This is **not an official Met Office product**. The conversion, derived values (dew point, cloud cover, weather code) and station coordinates are approximations made by this project.
- The attribution is also stored in the file metadata (key `knmi:dataset`) and in the viewer footer.
- The code in this repository is provided as is.

## Data overview

| | |
|---|---|
| Stations | at most 40, spread over the UK (selected from a coarse grid, see [Station list](#station-list)); stations without a temperature are left out |
| Parameters | 12 KNMI-named columns: `ta td rh dd ff gff fx pp qnh vv ww n` (a column without any value is not written) |
| Time step | hourly (KNMI itself is 10-minute); one row per station = the latest observation |
| Refresh | every 3 hours (`10 */3 * * *`) |
| Format | GeoParquet 1.1, snappy, Z-order sorted, bbox covering column |

Number of stations that report each parameter (the viewer shows the same numbers per parameter; varies per run):

| Parameter | Stations |
|---|---|
| `ta`, `qnh`… | see the first lines of the `convert.py` log in the [Actions](../../actions) run summary, or open the viewer |

> The exact counts depend on the observation hour: some sites only report temperature and humidity (for example Greater London), most also report wind, visibility, pressure and weather code. `convert.py` prints `parameters, stations` and the number of stations per parameter on every run.

## Pipeline

```
stations.py ──► stations.json          (rarely; committed)
download.py ──► obs_raw.json           (every run; 1 API call per station)
convert.py  ──► web/obs.parquet        (every run)
GitHub Pages ─► index.html + obs.parquet
```

### Station list

The Met Office API has no list of stations. `stations.py` calls `/nearest` on a coarse lat/lon grid over the UK (about 120 calls), removes duplicates by geohash and keeps at most 40 stations that are spread evenly over the country (farthest-point sampling). The result is committed as `stations.json`. Station coordinates are the **centre of the 6-character geohash cell** (about ±0.6 km); the API does not return coordinates or station height (`height` is therefore empty).

### Free plan quota

The free plan allows **360 API calls per day**. `download.py` uses 1 call per station: 40 stations × 8 runs (every 3 hours) = 320 calls per day. Running `stations.py` once costs about 120 calls. When the quota is exceeded the API returns HTTP 429 and the scripts stop with an error (the previous deployment stays online).

## API requests

Base URL `https://data.hub.api.metoffice.gov.uk/observation-land/1`, header `apikey: <key>`.

1. **Nearest site**

   ```
   GET /nearest?lat=51.5&lon=-0.12
   ```

   ```json
   [{"geohash": "gcpvj0", "area": "Greater London", "region": "se", "country": "England", "olson_time_zone": "Europe/London"}]
   ```

2. **Observations of a site** (last 48 hours, hourly)

   ```
   GET /gcqr9c
   ```

   ```json
   [{"datetime": "2026-11-06T10:00:00Z", "temperature": 9.13, "humidity": 85, "wind_speed": 1.4,
     "wind_gust": 2.8, "wind_direction": "ENE", "visibility": 12550, "mslp": 1025,
     "pressure_tendency": "R", "weather_code": 8}, ...]
   ```

   Fields vary per site and hour; a missing field is simply absent. For every station the newest record is used; a field missing in it is taken from an older record of at most 2 hours earlier.

## Mapping Met Office → KNMI

`convert.py` writes the Met Office values under the KNMI variable name (see [VARIABLES.md in knmi_zarr](https://github.com/bertt/knmi_zarr/blob/main/VARIABLES.md)). If KNMI has no identical parameter, the most similar KNMI parameter is used; otherwise the value is left out.

| KNMI name | KNMI meaning | Met Office field | Match | Conversion |
|---|---|---|---|---|
| `ta` | Air temperature | `temperature` | direct | °C, none |
| `td` | Dew point temperature | – (`temperature` + `humidity`) | derived | Magnus formula |
| `rh` | Relative humidity | `humidity` | direct | %, none |
| `dd` | Wind direction | `wind_direction` (16-point compass, text) | direct | compass → degrees (N = 0, NNE = 22.5, …) |
| `ff` | Wind speed at 10 m | `wind_speed` | direct | m/s, none |
| `gff` | Wind gust at 10 m | `wind_gust` | direct | m/s, none |
| `fx` | Wind gust, maximum in last interval | `wind_gust` | similar | same value as `gff` |
| `pp` | Air pressure at mean sea level | `mslp` | direct | hPa, none |
| `qnh` | QNH | `mslp` | similar | same value as `pp` |
| `vv` | Horizontal visibility | `visibility` | direct | m, none |
| `ww` | WaWa present weather code | `weather_code` (0–30) | converted | lookup, see below |
| `n` | Total cloud cover (okta) | `weather_code` | approximated | clear/sunny 0 → 0, partly cloudy 2, 3 → 4, cloudy 7 → 7, overcast 8 → 8; other codes empty |
| – | – | `pressure_tendency` | – | no KNMI equivalent, left out |
| `qg`, `ss`, `rg`, `pg`, `R1H`, `R6H`, `R24H`, `tn`, `tx`, `p0`, … | radiation, sunshine, precipitation, … | not in the Met Office land observations | – | not in the file |

Met Office weather code → KNMI `ww` (nearest WMO 4680 style code; codes not listed, such as clear, sunny, partly cloudy, cloudy, overcast, give an empty `ww`):

| Met Office code | Meaning | `ww` |
|---|---|---|
| 5 / 6 | mist / fog | 10 / 45 |
| 11 | drizzle | 51 |
| 12 / 15 | light rain / heavy rain | 61 / 65 |
| 9, 10 / 13, 14 | light / heavy rain shower | 80 / 82 |
| 16, 17 / 18 | sleet shower / sleet | 83 / 68 |
| 19, 20 / 21 | hail shower / hail | 87 / 89 |
| 22, 23 / 24 | light snow shower / light snow | 85 / 71 |
| 25, 26 / 27 | heavy snow shower / heavy snow | 86 / 75 |
| 28, 29, 30 | thunder (shower) | 95 |

Descriptions (long name, units, CF `standard_name`) of the variables in the file are stored as JSON in the file metadata (key `knmi:variables`).

## Columns

`station_id` (geohash), `station_name` (area, e.g. *Cheshire East*), `source` (`MetOffice`), `wsi` (empty), `time` (UTC), `lat`, `lon`, `height` (empty), `geometry` (WKB point, EPSG:4326), `bbox` (GeoParquet covering) and the KNMI-named `float32` parameter columns (missing = null).

## Run it yourself

```powershell
$env:METOFFICE_API_KEY = "<your key>"      # https://datahub.metoffice.gov.uk/ (never commit it)
uv run --with requests --with numpy python stations.py          # only to rebuild stations.json
uv run --with requests python download.py
uv run --with pandas --with geopandas --with pyarrow --with numpy python convert.py
```

The result is `web/obs.parquet`; open `web/index.html` through a local web server to view it.

## GitHub Actions

`.github/workflows/refresh.yml` runs every 3 hours and on demand (`workflow_dispatch`): download → convert → deploy `web/` to GitHub Pages. Add the repository secret `METOFFICE_API_KEY` and set *Settings → Pages → Source* to *GitHub Actions*. GitHub disables scheduled workflows after 60 days without repository activity; start the workflow manually to re-enable it.

## Limitations

- Hourly data and few parameters: no precipitation, radiation, sunshine or ground temperature; `td`, `n` and `ww` are derived or approximated.
- Coordinates are geohash cell centres; there is no station height.
- Only a selection of the Met Office stations is included because of the 360 calls/day limit.
