from math import asin, cos, hypot, radians, sin, sqrt

from django.conf import settings
from django.db import models


def distance_m(lat1, lon1, lat2, lon2):
    """Haversine distance in meters (same formula as TinyGPSPlus::distanceBetween)."""
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6372795 * asin(sqrt(a))


def in_polygon(lat, lon, poly):
    """Ray casting on [[lat, lon], ...]. Treating degrees as flat is fine at pasture scale."""
    inside = False
    for (y1, x1), (y2, x2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def distance_to_edge_m(lat, lon, poly):
    """Meters from the point to the nearest polygon edge (flat projection around the point)."""
    ky, kx = 111_195, 111_195 * cos(radians(lat))
    pts = [((p[1] - lon) * kx, (p[0] - lat) * ky) for p in poly]  # point is at (0, 0)
    best = float("inf")
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        dx, dy = x2 - x1, y2 - y1
        t = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / (dx * dx + dy * dy or 1)))
        best = min(best, hypot(x1 + t * dx, y1 + t * dy))
    return best


class Fence(models.Model):
    name = models.CharField(max_length=100)
    center_lat = models.FloatField()
    center_lon = models.FloatField()
    radius_m = models.FloatField(default=50)
    # [[lat, lon], ...] drawn on the dashboard. When set it is the boundary; center/radius then
    # hold a rough enclosing circle for the cattle unit's own on-board check.
    polygon = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({len(self.polygon)}-point boundary)" if self.polygon else f"{self.name} ({self.radius_m:.0f} m)"

    def locate(self, lat, lon):
        """(inside, distance_m). Distance is from the edge for polygons, from the center for circles."""
        if self.polygon:
            return in_polygon(lat, lon, self.polygon), distance_to_edge_m(lat, lon, self.polygon)
        d = distance_m(lat, lon, self.center_lat, self.center_lon)
        return d <= self.radius_m, d

    def set_polygon(self, poly):
        self.polygon = poly
        self.center_lat = sum(p[0] for p in poly) / len(poly)
        self.center_lon = sum(p[1] for p in poly) / len(poly)
        self.radius_m = max(distance_m(self.center_lat, self.center_lon, *p) for p in poly)


class Animal(models.Model):
    tag = models.CharField(max_length=20, unique=True, help_text="ID the cattle unit sends over LoRa, e.g. C1")
    name = models.CharField(max_length=100, blank=True)
    fence = models.ForeignKey(Fence, on_delete=models.PROTECT, related_name="animals")
    simulated = models.BooleanField(default=False, help_text="Created by the dashboard's simulation mode")

    def __str__(self):
        return self.name or self.tag

    def record(self, lat, lon, **extra):
        """Store a reading and open/close alerts. Returns the reading."""
        inside, d = self.fence.locate(lat, lon)
        reading = self.readings.create(lat=lat, lon=lon, distance_m=d, inside=inside, **extra)

        # Require N consecutive readings on one side before flipping, so GPS jitter
        # at the boundary doesn't spam alerts.
        n = settings.BREACH_CONFIRM_READINGS
        recent = [r.inside for r in self.readings.order_by("-id")[:n]]
        open_alert = self.alerts.filter(ended_at=None).first()
        if len(recent) == n and not any(recent) and not open_alert:
            self.alerts.create(started_at=reading.received_at, lat=lat, lon=lon)
        elif len(recent) == n and all(recent) and open_alert:
            open_alert.ended_at = reading.received_at
            open_alert.save(update_fields=["ended_at"])
        return reading


class Reading(models.Model):
    animal = models.ForeignKey(Animal, on_delete=models.CASCADE, related_name="readings")
    lat = models.FloatField()
    lon = models.FloatField()
    distance_m = models.FloatField()
    inside = models.BooleanField()
    sats = models.PositiveSmallIntegerField(null=True, blank=True)
    rssi = models.SmallIntegerField(null=True, blank=True)
    seq = models.PositiveIntegerField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-received_at"]


class Alert(models.Model):
    animal = models.ForeignKey(Animal, on_delete=models.CASCADE, related_name="alerts")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    lat = models.FloatField()
    lon = models.FloatField()

    class Meta:
        ordering = ["-started_at"]
