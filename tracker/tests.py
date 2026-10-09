import json

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from .models import Animal, Fence, distance_m

KEY = {"HTTP_X_API_KEY": "test-key"}
LAT, LON = 27.671239, 85.440312
DEG_PER_M = 1 / 111_195  # latitude degrees per meter


@override_settings(STATION_API_KEY="test-key", BREACH_CONFIRM_READINGS=3)
class IngestTests(TestCase):
    def setUp(self):
        fence = Fence.objects.create(name="Pasture", center_lat=LAT, center_lon=LON, radius_m=50)
        self.cow = Animal.objects.create(tag="C1", fence=fence)

    def post(self, meters_north, **kw):
        return self.client.post("/api/readings", {"id": "C1", "lat": LAT + meters_north * DEG_PER_M, "lon": LON, **kw}, **KEY)

    def test_distance_matches_tinygps(self):
        # Report fig 4.2: device printed 12543.53 m from this point to the code's default center.
        self.assertAlmostEqual(distance_m(27.671239, 85.440312, 27.7172, 85.3240), 12543.5, delta=1)

    def test_rejects_bad_key_and_input(self):
        self.assertEqual(self.client.post("/api/readings", {"id": "C1", "lat": LAT, "lon": LON}).status_code, 401)
        self.assertEqual(self.client.post("/api/readings", {"id": "C1", "lat": "x", "lon": LON}, **KEY).status_code, 400)
        self.assertEqual(self.client.post("/api/readings", {"id": "C1", "lat": 0, "lon": 0}, **KEY).status_code, 400)
        self.assertEqual(self.client.post("/api/readings", {"id": "C9", "lat": LAT, "lon": LON}, **KEY).status_code, 404)

    def test_inside_outside(self):
        self.assertEqual(self.post(10, sats=7, seq=1).content, b"OK IN")
        self.assertEqual(self.post(80).content, b"OK OUT")
        r = self.cow.readings.order_by("id").first()
        self.assertEqual((r.sats, r.seq), (7, 1))

    def test_alert_needs_consecutive_readings_and_closes(self):
        for m in (60, 60, 40, 60, 60):  # jitter: never 3 outside in a row
            self.post(m)
        self.assertFalse(self.cow.alerts.exists())

        self.post(70)  # third consecutive outside
        alert = self.cow.alerts.get()
        self.assertIsNone(alert.ended_at)

        self.post(70)  # still outside: no duplicate alert
        self.post(10); self.post(10)
        alert.refresh_from_db(); self.assertIsNone(alert.ended_at)
        self.post(10)
        alert.refresh_from_db(); self.assertIsNotNone(alert.ended_at)
        self.assertEqual(self.cow.alerts.count(), 1)

    def test_dashboard_api_requires_login(self):
        self.post(80)
        self.assertEqual(self.client.get("/api/latest").status_code, 401)
        self.client.force_login(User.objects.create_user("farmer"))
        data = self.client.get("/api/latest").json()["animals"][0]
        self.assertFalse(data["reading"]["inside"])
        self.assertEqual(len(self.client.get("/api/track/C1").json()["points"]), 1)


class FrontendApiTests(TestCase):
    def setUp(self):
        User.objects.create_user("farmer", password="pw-for-tests")

    def test_login_flow_with_csrf(self):
        c = Client(enforce_csrf_checks=True)
        self.assertIsNone(c.get("/api/me").json()["user"])
        token = c.cookies["csrftoken"].value
        self.assertEqual(c.post("/api/login", '{"username":"farmer","password":"pw-for-tests"}',
                                content_type="application/json").status_code, 403)  # no CSRF header
        bad = c.post("/api/login", '{"username":"farmer","password":"nope"}',
                     content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(bad.status_code, 400)
        ok = c.post("/api/login", '{"username":"farmer","password":"pw-for-tests"}',
                    content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(ok.json()["user"], "farmer")
        self.assertEqual(c.get("/api/me").json()["user"], "farmer")

    def test_sim_is_separate_from_live(self):
        self.client.login(username="farmer", password="pw-for-tests")
        live_fence = Fence.objects.create(name="Real", center_lat=LAT, center_lon=LON)
        Animal.objects.create(tag="C1", fence=live_fence)

        for _ in range(70):  # > one full SIM-1 cycle, which reaches 1.8x radius
            self.assertEqual(self.client.post("/api/sim/tick").status_code, 200)

        sim = self.client.get("/api/latest?mode=sim").json()["animals"]
        live = self.client.get("/api/latest").json()["animals"]
        self.assertEqual([a["tag"] for a in sim], ["SIM-1", "SIM-2", "SIM-3"])
        self.assertEqual([a["tag"] for a in live], ["C1"])
        self.assertEqual(sim[0]["reading"]["seq"], 69)

        sim_alerts = self.client.get("/api/alerts?mode=sim").json()["alerts"]
        self.assertTrue(sim_alerts and all(a["tag"] in ("SIM-1", "SIM-3") for a in sim_alerts))  # SIM-2 never leaves
        self.assertEqual(self.client.get("/api/alerts").json()["alerts"], [])

        self.client.post("/api/sim/reset")
        self.assertIsNone(self.client.get("/api/latest?mode=sim").json()["animals"][0]["reading"])
        self.assertEqual(self.client.get("/api/alerts?mode=sim").json()["alerts"], [])

    def test_sim_requires_login(self):
        self.assertEqual(self.client.post("/api/sim/tick").status_code, 401)


@override_settings(STATION_API_KEY="test-key", BREACH_CONFIRM_READINGS=1)
class PolygonFenceTests(TestCase):
    # L-shaped pasture, ~100 m per side: the notch at the top-right is outside.
    M = DEG_PER_M
    L_SHAPE = [[LAT, LON], [LAT, LON + 100 * M], [LAT + 50 * M, LON + 100 * M],
               [LAT + 50 * M, LON + 50 * M], [LAT + 100 * M, LON + 50 * M], [LAT + 100 * M, LON]]

    def setUp(self):
        self.client.force_login(User.objects.create_user("farmer"))

    def json(self, method, url, data):
        return getattr(self.client, method)(url, json.dumps(data), content_type="application/json")

    def test_draw_fence_then_station_uses_it(self):
        r = self.json("post", "/api/fences", {"name": "Back field", "polygon": self.L_SHAPE})
        self.assertEqual(r.status_code, 201)
        fid = r.json()["fence"]["id"]
        Animal.objects.create(tag="C1", fence=Fence.objects.create(name="Old", center_lat=LAT, center_lon=LON))
        self.assertEqual(self.json("patch", "/api/animals/C1", {"fence": fid}).status_code, 200)

        def send(m_north, m_east):
            return self.client.post("/api/readings", {"id": "C1", "lat": LAT + m_north * self.M,
                                                      "lon": LON + m_east * self.M / 0.886}, **KEY).content
        self.assertEqual(send(25, 75), b"OK IN")    # bottom arm
        self.assertEqual(send(75, 25), b"OK IN")    # left arm
        self.assertEqual(send(75, 75), b"OK OUT")   # the notch: inside a circle, outside the drawn shape
        r = Animal.objects.get(tag="C1").readings.first()
        self.assertAlmostEqual(r.distance_m, 25, delta=1.5)  # nearest edge
        self.assertTrue(Animal.objects.get(tag="C1").alerts.filter(ended_at=None).exists())

    def test_edit_and_delete_rules(self):
        fid = self.json("post", "/api/fences", {"name": "F", "polygon": self.L_SHAPE}).json()["fence"]["id"]
        self.assertEqual(self.json("post", "/api/fences", {"name": "Bad", "polygon": [[1, 2], [3, 4]]}).status_code, 400)
        self.assertEqual(self.json("patch", f"/api/fences/{fid}", {"polygon": [["x", 1]] * 3}).status_code, 400)
        tri = self.L_SHAPE[:3]
        self.assertEqual(self.json("patch", f"/api/fences/{fid}", {"polygon": tri, "name": "Tri"}).json()["fence"]["polygon"], tri)
        Animal.objects.create(tag="C2", fence_id=fid)
        self.assertEqual(self.client.delete(f"/api/fences/{fid}").status_code, 400)  # has animals
        Animal.objects.all().delete()
        self.assertEqual(self.client.delete(f"/api/fences/{fid}").status_code, 200)
        self.client.logout()
        self.assertEqual(self.json("post", "/api/fences", {"name": "F", "polygon": tri}).status_code, 401)
