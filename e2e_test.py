"""End-to-end check against a running server (Postgres-backed), over real HTTP.

Flow: admin logs in -> registers a fence + two animals via the admin forms ->
"station" forwards LoRa packets (C1,lat,lon,status,sats,seq) as form POSTs ->
dashboard APIs show positions, track and alert lifecycle.

Usage: set -a; . ./.env.example; set +a; python e2e_test.py [--url http://127.0.0.1:8001]
"""
import argparse
import http.cookiejar
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8001")
URL = ap.parse_args().url
KEY = os.environ["STATION_API_KEY"]
LAT, LON = 27.671239, 85.440312  # fence center, from the report's field test
RUN = str(int(time.time()) % 100000)  # unique tags so the script can be re-run

jar = http.cookiejar.CookieJar()
browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def req(opener, path, data=None, headers=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    try:
        with opener.open(urllib.request.Request(URL + path, data=body, headers=headers or {})) as r:
            return r.status, r.read().decode(), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), path


def csrf():
    return next(c.value for c in jar if c.name == "csrftoken")


def admin_add(model, fields):
    req(browser, f"/admin/tracker/{model}/add/")
    status, html, final = req(browser, f"/admin/tracker/{model}/add/", {**fields, "csrfmiddlewaretoken": csrf(), "_save": "Save"})
    assert final.endswith(f"/admin/tracker/{model}/"), f"admin add {model} failed: {status} {final}"
    return max(int(i) for i in re.findall(rf"/admin/tracker/{model}/(\d+)/change/", html))


# --- station side: what the monitoring-station ESP32 does with each LoRa packet ---
station = urllib.request.build_opener()


def station_forward(packet, rssi=-90, key=KEY):
    tag, lat, lon, _status, sats, seq = packet.split(",")
    return req(station, "/api/readings", {"id": tag, "lat": lat, "lon": lon, "sats": sats, "rssi": rssi, "seq": seq},
               {"X-API-Key": key})


def cattle_packet(tag, meters_north, seq):
    """What the cattle unit sends over LoRa (device-side status is informational only)."""
    lat = LAT + meters_north / 111_195
    return f"{tag},{lat:.6f},{LON:.6f},{int(meters_north > 50)},8,{seq}"


def step(msg):
    print(f"[ok] {msg}")


# 1. Dashboard is private
assert req(browser, "/api/latest")[0] == 401
assert req(browser, "/api/sim/tick", {})[0] in (401, 403)
step("dashboard + simulation APIs refuse signed-out requests")

# 2. Admin logs in and registers fence + animals
req(browser, "/admin/login/")
_, _, final = req(browser, "/admin/login/?next=/admin/", {
    "username": os.environ["DJANGO_SUPERUSER_USERNAME"], "password": os.environ["DJANGO_SUPERUSER_PASSWORD"],
    "csrfmiddlewaretoken": csrf(), "next": "/admin/"})
assert final.endswith("/admin/"), f"login failed: {final}"
step("admin login")

fence_id = admin_add("fence", {"name": f"Pasture {RUN}", "center_lat": LAT, "center_lon": LON, "radius_m": 50})
C1, C2 = f"C1-{RUN}", f"C2-{RUN}"
admin_add("animal", {"tag": C1, "name": f"Cow 1 ({RUN})", "fence": fence_id})
admin_add("animal", {"tag": C2, "name": f"Cow 2 ({RUN})", "fence": fence_id})
step(f"registered fence #{fence_id} and animals {C1}, {C2} via admin forms")

# 3. Station rejects bad input
assert station_forward(cattle_packet(C1, 0, 0), key="wrong")[0] == 401
assert station_forward(cattle_packet(f"X-{RUN}", 0, 0))[0] == 404
assert req(station, "/api/readings", {"id": C1, "lat": "abc", "lon": LON}, {"X-API-Key": KEY})[0] == 400
step("bad key -> 401, unknown tag -> 404, malformed -> 400")


def latest(tag):
    return next(a for a in json.loads(req(browser, "/api/latest")[1])["animals"] if a["tag"] == tag)


# 4. C1 grazes, jitters at the edge, wanders out, comes back. C2 stays put.
seq = 0
def send(tag, meters, expect):
    global seq
    seq += 1
    status, body, _ = station_forward(cattle_packet(tag, meters, seq))
    assert (status, body) == (200, expect), (tag, meters, status, body)

for m in (5, 20, 35):
    send(C1, m, "OK IN"); send(C2, 10, "OK IN")
assert not latest(C1)["alert"]
step("C1 + C2 inside the fence")

for m in (55, 60, 45, 58, 62, 40):  # boundary jitter: never 3 outside in a row
    send(C1, m, "OK OUT" if m > 50 else "OK IN")
assert not latest(C1)["alert"]
step("boundary jitter did not raise an alert")

for m in (70, 85, 110):
    send(C1, m, "OK OUT")
a = latest(C1)
assert a["alert"] and not a["reading"]["inside"] and a["reading"]["distance_m"] > 100, a
assert not latest(C2)["alert"]
step(f"C1 left the fence -> alert open, last seen {a['reading']['distance_m']} m from center")

for m in (90, 30, 15):
    send(C1, m, "OK OUT" if m > 50 else "OK IN")
assert latest(C1)["alert"], "alert closed after only 2 inside readings"
send(C1, 10, "OK IN")
assert not latest(C1)["alert"]
step("C1 back inside for 3 readings -> alert closed")

# 5. History + alert log
pts = json.loads(req(browser, f"/api/track/{C1}?hours=1")[1])["points"]
assert len(pts) == 3 + 6 + 3 + 4, len(pts)
alerts = [x for x in json.loads(req(browser, "/api/alerts")[1])["alerts"] if x["tag"] == C1]
assert len(alerts) == 1 and alerts[0]["ended_at"], alerts
status, html, _ = req(browser, "/")
assert status == 200 and '<div id="root">' in html, html[:200]
step(f"track has {len(pts)} points, 1 closed alert logged, React app served at /")

# 6. Simulation mode: browser-driven ticks, kept apart from live data
browser_post = lambda path: req(browser, path, {}, {"X-CSRFToken": csrf()})
assert browser_post("/api/sim/reset")[0] == 200
for _ in range(70):
    assert browser_post("/api/sim/tick")[0] == 200
sim = json.loads(req(browser, "/api/latest?mode=sim")[1])["animals"]
live_tags = [a["tag"] for a in json.loads(req(browser, "/api/latest")[1])["animals"]]
sim_alerts = json.loads(req(browser, "/api/alerts?mode=sim")[1])["alerts"]
assert [a["tag"] for a in sim] == ["SIM-1", "SIM-2", "SIM-3"] and all(a["reading"]["seq"] == 69 for a in sim), sim
assert not any(t.startswith("SIM-") for t in live_tags) and C1 in live_tags
assert sim_alerts and {a["tag"] for a in sim_alerts} <= {"SIM-1", "SIM-3"}, sim_alerts
step(f"70 sim ticks: {len(sim_alerts)} sim alerts (SIM-2 never left), live view untouched")

print(f"\nE2E PASSED  (run id {RUN}, fence #{fence_id})")
