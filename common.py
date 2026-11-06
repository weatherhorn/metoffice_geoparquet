"""Shared helpers for the Met Office Land Observations API."""
import os, sys, time
import requests

BASE = "https://data.hub.api.metoffice.gov.uk/observation-land/1"
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def session():
    key = os.environ.get("METOFFICE_API_KEY")
    if not key:
        sys.exit("Set the METOFFICE_API_KEY environment variable")
    s = requests.Session()
    s.headers["apikey"] = key
    return s


def get(s, url, params=None, retries=4):
    """GET with retries on transient errors; returns parsed JSON or None for 404."""
    for attempt in range(retries):
        try:
            r = s.get(url, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:
            return None
        if r.status_code == 429:
            raise SystemExit(f"Daily quota reached: {r.text}")
        if r.status_code in (500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"GET {url} failed after {retries} attempts")


def geohash_decode(gh):
    """Returns (lat, lon) of the centre of a geohash cell."""
    lat, lon = [-90.0, 90.0], [-180.0, 180.0]
    even = True
    for c in gh:
        bits = _BASE32.index(c)
        for i in range(4, -1, -1):
            rng = lon if even else lat
            mid = (rng[0] + rng[1]) / 2
            rng[0 if (bits >> i) & 1 else 1] = mid
            even = not even
    return (lat[0] + lat[1]) / 2, (lon[0] + lon[1]) / 2
