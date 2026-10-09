import hmac
import json
import random
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db import models, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from . import sim
from .models import Alert, Animal, Fence, Reading

FRONTEND_DIST = settings.BASE_DIR / "frontend" / "dist"
SIM_CENTER = (27.671239, 85.440312)  # field-test point from the report


def _int(v):
    return int(v) if v not in (None, "") else None


def api_login_required(view):
    """Like login_required, but answers 401 JSON instead of redirecting (for the React app)."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "login required"}, status=401)
        return view(request, *args, **kwargs)
    return wrapper


def _simulated(request):
    return request.GET.get("mode") == "sim"


# ---------- station ----------

@csrf_exempt
@require_POST
def ingest(request):
    """Monitoring station uploads one packet: form-encoded id, lat, lon[, sats, rssi, seq].

    Plain-text responses so the SIM808 can log them easily.
    """
    key = request.headers.get("X-API-Key", "")
    if not hmac.compare_digest(key, settings.STATION_API_KEY):
        return HttpResponse("ERR key", status=401)

    p = request.POST
    try:
        lat, lon = float(p["lat"]), float(p["lon"])
        extra = {"sats": _int(p.get("sats")), "rssi": _int(p.get("rssi")), "seq": _int(p.get("seq"))}
    except (KeyError, ValueError):
        return HttpResponse("ERR bad fields", status=400)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return HttpResponse("ERR bad coords", status=400)

    animal = Animal.objects.select_related("fence").filter(tag=p.get("id", "")).first()
    if not animal:
        return HttpResponse("ERR unknown id, register it in admin", status=404)

    r = animal.record(lat, lon, **extra)
    return HttpResponse("OK IN" if r.inside else "OK OUT")


# ---------- auth for the React app ----------

@ensure_csrf_cookie
def me(request):
    u = request.user
    return JsonResponse({"user": u.username if u.is_authenticated else None})


@require_POST
def login_view(request):
    try:
        data = json.loads(request.body or "{}")
    except ValueError:
        data = {}
    user = authenticate(request, username=data.get("username", ""), password=data.get("password", ""))
    if not user:
        return JsonResponse({"error": "Invalid username or password"}, status=400)
    login(request, user)
    return JsonResponse({"user": user.username})


@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({"user": None})


# ---------- dashboard data (?mode=live | sim) ----------

@api_login_required
def latest(request):
    # ponytail: one query per animal, fine for a herd of tens; annotate with Subquery if it grows.
    out = []
    for a in Animal.objects.select_related("fence").filter(simulated=_simulated(request)).order_by("tag"):
        r = a.readings.first()
        f = a.fence
        out.append({
            "tag": a.tag,
            "name": str(a),
            "fence": {"id": f.id, "name": f.name, "lat": f.center_lat, "lon": f.center_lon, "radius_m": f.radius_m},
            "alert": a.alerts.filter(ended_at=None).exists(),
            "reading": r and {
                "lat": r.lat, "lon": r.lon, "distance_m": round(r.distance_m, 1), "inside": r.inside,
                "sats": r.sats, "rssi": r.rssi, "seq": r.seq, "at": r.received_at.isoformat(),
            },
        })
    return JsonResponse({"animals": out, "server_time": timezone.now().isoformat()})


@api_login_required
def track(request, tag):
    animal = get_object_or_404(Animal, tag=tag)
    try:
        hours = min(float(request.GET.get("hours", 6)), 24 * 30)
    except ValueError:
        hours = 6
    since = timezone.now() - timedelta(hours=hours)
    pts = animal.readings.filter(received_at__gte=since).order_by("received_at").values_list("lat", "lon")
    return JsonResponse({"tag": tag, "points": list(pts)})


@api_login_required
def alerts(request):
    rows = Alert.objects.select_related("animal").filter(animal__simulated=_simulated(request))[:100]
    return JsonResponse({"alerts": [{
        "id": a.id, "tag": a.animal.tag, "name": str(a.animal), "lat": a.lat, "lon": a.lon,
        "started_at": a.started_at.isoformat(), "ended_at": a.ended_at and a.ended_at.isoformat(),
    } for a in rows]})


# ---------- fences drawn on the map ----------

def _json(request):
    try:
        data = json.loads(request.body or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _clean_polygon(raw):
    """[[lat, lon], ...] with 3..500 valid points, or None."""
    # ponytail: no self-intersection check here; Geoman refuses to draw one in the UI.
    try:
        poly = [[float(lat), float(lon)] for lat, lon in raw]
    except (TypeError, ValueError):
        return None
    if not 3 <= len(poly) <= 500 or not all(-90 <= a <= 90 and -180 <= b <= 180 for a, b in poly):
        return None
    return poly


def _fence_json(f):
    return {"id": f.id, "name": f.name, "lat": f.center_lat, "lon": f.center_lon, "radius_m": f.radius_m,
            "polygon": f.polygon, "animals": f.n}


def _fences_qs():
    return Fence.objects.annotate(n=models.Count("animals"))


@api_login_required
@require_http_methods(["GET", "POST"])
def fences(request):
    if request.method == "GET":
        # A fence belongs to simulation mode if simulated animals use it; new, empty fences show in live mode.
        qs = _fences_qs()
        qs = qs.filter(animals__simulated=True) if _simulated(request) else qs.exclude(animals__simulated=True)
        return JsonResponse({"fences": [_fence_json(f) for f in qs.distinct().order_by("name")]})

    data = _json(request)
    name, poly = str(data.get("name", "")).strip()[:100], _clean_polygon(data.get("polygon"))
    if not name or not poly:
        return JsonResponse({"error": "Give the fence a name and at least 3 points"}, status=400)
    f = Fence(name=name)
    f.set_polygon(poly)
    f.save()
    return JsonResponse({"fence": _fence_json(_fences_qs().get(pk=f.pk))}, status=201)


@api_login_required
@require_http_methods(["PATCH", "DELETE"])
def fence_detail(request, pk):
    f = get_object_or_404(Fence, pk=pk)
    if request.method == "DELETE":
        if f.animals.exists():
            return JsonResponse({"error": "Move its animals to another fence first"}, status=400)
        f.delete()
        return JsonResponse({"ok": True})

    data = _json(request)
    if "name" in data:
        f.name = str(data["name"]).strip()[:100] or f.name
    if "polygon" in data:
        poly = _clean_polygon(data["polygon"])
        if not poly:
            return JsonResponse({"error": "A boundary needs at least 3 valid points"}, status=400)
        f.set_polygon(poly)
    f.save()
    # Readings already stored keep the inside/outside they had; the next packet uses the new shape.
    return JsonResponse({"fence": _fence_json(_fences_qs().get(pk=f.pk))})


@api_login_required
@require_http_methods(["PATCH"])
def animal_detail(request, tag):
    a = get_object_or_404(Animal, tag=tag)
    fence = Fence.objects.filter(pk=_json(request).get("fence")).first()
    if not fence:
        return JsonResponse({"error": "Unknown fence"}, status=400)
    a.fence = fence
    a.save(update_fields=["fence"])
    return JsonResponse({"ok": True})


# ---------- simulation (driven by the browser, one step per call) ----------

@api_login_required
@require_POST
def sim_tick(request):
    # ponytail: two open tabs both ticking = double speed; add a server-side clock if that matters.
    with transaction.atomic():
        fence, _ = Fence.objects.get_or_create(
            name="Simulation pasture", defaults={"center_lat": SIM_CENTER[0], "center_lon": SIM_CENTER[1], "radius_m": 50})
        for p in sim.PROFILES:
            a, _ = Animal.objects.get_or_create(
                tag=p["tag"], defaults={"name": p["name"], "fence": fence, "simulated": True})
            f = a.fence
            last = a.readings.first()
            step = last.seq + 1 if last and last.seq is not None else 0
            lat, lon, _ = sim.position(f.center_lat, f.center_lon, p["reach"] * f.radius_m, p["period"], p["bearing"], step)
            a.record(lat, lon, sats=random.randint(6, 11), rssi=random.randint(-105, -60), seq=step)
    return JsonResponse({"ok": True})


@api_login_required
@require_POST
def sim_reset(request):
    Alert.objects.filter(animal__simulated=True).delete()
    Reading.objects.filter(animal__simulated=True).delete()
    return JsonResponse({"ok": True})


# ---------- built React app ----------

def frontend(request):
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        return HttpResponse("Frontend not built. Run `npm run build` in frontend/, or use `npm run dev` (port 5173).",
                            content_type="text/plain")
    return HttpResponse(index.read_bytes(), content_type="text/html")
