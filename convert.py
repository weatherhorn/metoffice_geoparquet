"""Convert Met Office land observations (obs_raw.json) to a GeoParquet file with KNMI parameter names.

Usage: python convert.py [-o web/obs.parquet]

One row per station, same layout as the KNMI GeoParquet of https://github.com/bertt/knmi_zarr
(station_id, station_name, source, wsi, time, lat, lon, height, geometry, bbox + KNMI-named float32
columns), Z-order sorted. The Met Office -> KNMI mapping is documented in README.md.
"""
import json, sys
import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROW_GROUP = 512
MAX_AGE_HOURS = 2  # a value missing in the newest record may be taken from a record at most this much older

COMPASS = {n: i * 22.5 for i, n in enumerate(
    "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split())}

# Met Office significant weather code -> nearest KNMI ww (WMO 4680 style present weather); None = no significant weather
WW = {5: 10, 6: 45, 11: 51, 12: 61, 15: 65, 9: 80, 10: 80, 13: 82, 14: 82, 16: 83, 17: 83, 18: 68,
      19: 87, 20: 87, 21: 89, 22: 85, 23: 85, 24: 71, 25: 86, 26: 86, 27: 75, 28: 95, 29: 95, 30: 95}
# Met Office significant weather code -> total cloud cover n (okta); only for cloud related codes
N = {0: 0, 1: 0, 2: 4, 3: 4, 7: 7, 8: 8}

# KNMI name -> (long name, units, CF standard name)
VARIABLES = {
    "ta": ("Air temperature, hourly value", "degrees Celsius", "air_temperature"),
    "td": ("Dew point temperature (derived from ta and rh)", "degrees Celsius", "dew_point_temperature"),
    "rh": ("Relative humidity", "%", "relative_humidity"),
    "dd": ("Wind direction", "degree", "wind_from_direction"),
    "ff": ("Wind speed at 10 m", "m s-1", "wind_speed"),
    "gff": ("Wind gust at 10 m", "m s-1", "wind_speed_of_gust"),
    "fx": ("Wind gust at 10 m, maximum in the last interval", "m s-1", "wind_speed_of_gust"),
    "pp": ("Air pressure at mean sea level", "hPa", "air_pressure_at_mean_sea_level"),
    "qnh": ("QNH (approximated by air pressure at mean sea level)", "hPa", "air_pressure_at_mean_sea_level"),
    "vv": ("Horizontal visibility", "m", "visibility_in_air"),
    "ww": ("Present weather code (converted from Met Office code)", "code", ""),
    "n": ("Total cloud cover (approximated from Met Office weather code)", "okta", "cloud_area_fraction"),
}


def magnus_dewpoint(t, rh):
    a, b = 17.62, 243.12
    g = np.log(np.clip(rh, 1, 100) / 100) + a * t / (b + t)
    return b * g / (a - g)


def morton(lon, lat):
    x = np.clip((np.asarray(lon) + 180) / 360 * 65535, 0, 65535).astype(np.uint64)
    y = np.clip((np.asarray(lat) + 90) / 180 * 65535, 0, 65535).astype(np.uint64)
    key = np.zeros(len(x), dtype=np.uint64)
    for b in range(16):
        key |= ((x >> np.uint64(b)) & np.uint64(1)) << np.uint64(2 * b)
        key |= ((y >> np.uint64(b)) & np.uint64(1)) << np.uint64(2 * b + 1)
    return key


def latest_values(records):
    """Newest record, with missing fields filled from records at most MAX_AGE_HOURS older."""
    recs = sorted(records, key=lambda r: r["datetime"], reverse=True)
    newest = pd.Timestamp(recs[0]["datetime"])
    out = {"datetime": recs[0]["datetime"]}
    for r in recs:
        if newest - pd.Timestamp(r["datetime"]) > pd.Timedelta(hours=MAX_AGE_HOURS):
            break
        for k, v in r.items():
            if v is not None and k not in out:
                out[k] = v
    return out


args = sys.argv[1:]
out = args[args.index("-o") + 1] if "-o" in args else "web/obs.parquet"

stations = {s["geohash"]: s for s in json.load(open("stations.json", encoding="utf-8"))}
raw = json.load(open("obs_raw.json"))

rows = []
for gh, records in raw.items():
    if not records or gh not in stations:
        continue
    st, o = stations[gh], latest_values(records)
    if "temperature" not in o:
        continue
    code = o.get("weather_code")
    rows.append({
        "station_id": gh, "station_name": st["area"], "source": "MetOffice", "wsi": None,
        "time": pd.Timestamp(o["datetime"]).tz_convert("UTC").floor("ms"),
        "lat": st["lat"], "lon": st["lon"], "height": np.nan,
        "ta": o["temperature"], "rh": o.get("humidity", np.nan),
        "dd": COMPASS.get(o.get("wind_direction"), np.nan),
        "ff": o.get("wind_speed", np.nan), "gff": o.get("wind_gust", np.nan), "fx": o.get("wind_gust", np.nan),
        "pp": o.get("mslp", np.nan), "qnh": o.get("mslp", np.nan),
        "vv": o.get("visibility", np.nan),
        "ww": WW.get(code, np.nan) if code is not None else np.nan,
        "n": N.get(code, np.nan) if code is not None else np.nan,
    })
df = pd.DataFrame(rows)
df["td"] = np.where(df["rh"].notna(), magnus_dewpoint(df["ta"], df["rh"]), np.nan)
for v in VARIABLES:
    df[v] = df[v].astype("float32")
df["height"] = df["height"].astype("float32")
df = df.dropna(axis=1, how="all")  # drop parameters without any value
df = df.iloc[np.argsort(morton(df["lon"], df["lat"]), kind="stable")].reset_index(drop=True)

gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs="EPSG:4326")
gdf.to_parquet(out, index=False, schema_version="1.1.0", write_covering_bbox=True, compression="snappy")

used = {v: dict(zip(("long_name", "units", "standard_name"), m)) for v, m in VARIABLES.items() if v in df}
table = pq.read_table(out)
meta = dict(table.schema.metadata or {})
meta[b"knmi:variables"] = json.dumps(used, ensure_ascii=False).encode()
meta[b"knmi:dataset"] = json.dumps({
    "title": "Met Office land observations (hourly) with KNMI parameter names",
    "institution": "Met Office",
    "source": "Met Office Weather DataHub, Land Observations API (observation-land/1)",
    "references": "https://datahub.metoffice.gov.uk/",
    "license": "Contains Met Office data © Crown copyright",
    "Conventions": "CF-1.12",
}, ensure_ascii=False).encode()
pq.write_table(table.replace_schema_metadata(meta), out, row_group_size=ROW_GROUP, compression="snappy", write_statistics=True)

print(len(used), "parameters,", len(df), "stations ->", out)
for v in used:
    print(f"  {v}: {int(df[v].notna().sum())} stations")
