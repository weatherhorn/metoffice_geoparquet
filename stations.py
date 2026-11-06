"""Build stations.json: a spread-out selection of Met Office land observation sites in the UK.

The API has no station list, so /nearest is queried on a coarse lat/lon grid and the
results are de-duplicated by geohash. The free plan allows 360 calls/day, so the grid
is kept to ~120 calls and at most MAX_STATIONS stations are kept (farthest-point
sampling, so they are spread evenly over the UK). Run rarely; stations.json is committed.

Usage: METOFFICE_API_KEY=... python stations.py [max_stations]
"""
import json, sys
import numpy as np
from common import BASE, get, geohash_decode, session

MAX_STATIONS = int(sys.argv[1]) if len(sys.argv) > 1 else 40
s = session()
found = {}
for lat in np.arange(50.0, 60.5, 0.9):
    for lon in np.arange(-7.5, 2.0, 1.0):
        res = get(s, f"{BASE}/nearest", {"lat": round(float(lat), 4), "lon": round(float(lon), 4)})
        for r in res or []:
            found.setdefault(r["geohash"], r)
    print(f"lat {lat:.1f}: {len(found)} stations", flush=True)

cand = []
for gh, r in sorted(found.items()):
    lat, lon = geohash_decode(gh)
    cand.append({"geohash": gh, "area": r.get("area"), "region": r.get("region"),
                 "country": r.get("country"), "lat": round(lat, 5), "lon": round(lon, 5)})

# farthest-point sampling (lon scaled by cos(lat) so distances are roughly isotropic)
xy = np.array([[c["lon"] * 0.6, c["lat"]] for c in cand])
chosen = [int(np.argmin(xy[:, 1]))]
dist = np.linalg.norm(xy - xy[chosen[0]], axis=1)
while len(chosen) < min(MAX_STATIONS, len(cand)):
    i = int(np.argmax(dist))
    chosen.append(i)
    dist = np.minimum(dist, np.linalg.norm(xy - xy[i], axis=1))
stations = sorted((cand[i] for i in chosen), key=lambda c: c["geohash"])

with open("stations.json", "w", encoding="utf-8") as f:
    json.dump(stations, f, indent=1, ensure_ascii=False)
print(len(cand), "found,", len(stations), "kept -> stations.json")
