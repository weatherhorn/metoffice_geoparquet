"""Download the last 48 hourly observations for every station in stations.json.

Usage: METOFFICE_API_KEY=... python download.py   ->  obs_raw.json
"""
import json
from concurrent.futures import ThreadPoolExecutor
from common import BASE, get, session

s = session()
stations = json.load(open("stations.json", encoding="utf-8"))


def fetch(st):
    try:
        return st["geohash"], get(s, f"{BASE}/{st['geohash']}")
    except Exception as e:
        print("failed", st["geohash"], e)
        return st["geohash"], None


with ThreadPoolExecutor(6) as ex:
    raw = dict(ex.map(fetch, stations))
raw = {k: v for k, v in raw.items() if v}
if len(raw) < 0.5 * len(stations):
    raise SystemExit(f"Only {len(raw)}/{len(stations)} stations returned data; aborting")
json.dump(raw, open("obs_raw.json", "w"), separators=(",", ":"))
print(len(raw), "of", len(stations), "stations downloaded -> obs_raw.json")
