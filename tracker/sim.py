"""Fake GPS paths. Pure functions (no Django imports) so simulate.py can use them too."""
import math
import random

M_PER_DEG_LAT = 111_195

# Per simulated animal: how far it wanders (x fence radius), cycle length in steps, start bearing.
PROFILES = [
    {"tag": "SIM-1", "name": "Wanderer", "reach": 1.8, "period": 60, "bearing": 40},
    {"tag": "SIM-2", "name": "Homebody", "reach": 0.6, "period": 45, "bearing": 200},
    {"tag": "SIM-3", "name": "Edge grazer", "reach": 1.25, "period": 80, "bearing": 300},
]


def position(center_lat, center_lon, max_m, period, bearing_deg, step, jitter_m=5):
    """Distance swings 0 -> max_m -> 0 every `period` steps while slowly circling."""
    meters = max(0.0, max_m / 2 * (1 - math.cos(step * 2 * math.pi / period)) + random.uniform(-jitter_m, jitter_m))
    b = math.radians(bearing_deg + step * 2)
    lat = center_lat + meters * math.cos(b) / M_PER_DEG_LAT
    lon = center_lon + meters * math.sin(b) / (M_PER_DEG_LAT * math.cos(math.radians(center_lat)))
    return lat, lon, meters
