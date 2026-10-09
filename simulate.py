"""Fake cattle unit + station: walks an animal out of its fence and back.

Usage: python simulate.py [--url http://127.0.0.1:8000] [--key dev-station-key] [--tag C1]
                          [--lat 27.671239 --lon 85.440312] [--interval 2]
The --lat/--lon should match the fence center you created in /admin.
"""
import argparse
import random
import time
import urllib.error
import urllib.parse
import urllib.request

from tracker.sim import position

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8000")
ap.add_argument("--key", default="dev-station-key")
ap.add_argument("--tag", default="C1")
ap.add_argument("--lat", type=float, default=27.671239)
ap.add_argument("--lon", type=float, default=85.440312)
ap.add_argument("--interval", type=float, default=2)
args = ap.parse_args()

seq = 0
while True:
    # Distance from center swings 0 -> 90 m -> 0 over 60 steps, with ~5 m GPS jitter.
    lat, lon, meters = position(args.lat, args.lon, 90, 60, 40, seq)
    body = urllib.parse.urlencode({"id": args.tag, "lat": f"{lat:.6f}", "lon": f"{lon:.6f}",
                                   "sats": random.randint(5, 10), "rssi": random.randint(-110, -60), "seq": seq}).encode()
    req = urllib.request.Request(args.url + "/api/readings", data=body, headers={"X-API-Key": args.key})
    try:
        with urllib.request.urlopen(req) as r:
            print(seq, f"{meters:5.1f} m", r.read().decode())
    except urllib.error.HTTPError as e:
        print(seq, e.code, e.read().decode())
    seq += 1
    time.sleep(args.interval)
