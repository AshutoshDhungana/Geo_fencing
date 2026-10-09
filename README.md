# Herd Watch: Livestock Geo-Fence

Django + PostgreSQL backend and a Vite + React dashboard (OpenStreetMap) for the GPS geo-fencing project.

## Run locally

```sh
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on Linux/macOS
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py createsuperuser
.venv/Scripts/python manage.py runserver
```

1. Open http://127.0.0.1:8000/admin/. Add a **Fence** (center lat/lon and radius), then an **Animal** whose tag matches the cattle unit's ID (e.g. `C1`).
2. Start the frontend (see below) and sign in with your superuser.
3. Optionally run `.venv/Scripts/python simulate.py --lat <fence lat> --lon <fence lon>` to send fake *station* readings for a real animal.

Run the tests with `.venv/Scripts/python manage.py test tracker`.

Without `POSTGRES_DB` set, the app uses SQLite, which is fine for development.

## Frontend (`frontend/`, Vite + React + react-leaflet)

```sh
cd frontend
npm install
npm run dev        # http://localhost:5173; proxies /api and /admin to Django
npm run build      # writes frontend/dist; Django then serves the app at /
```

The dev proxy targets `http://127.0.0.1:8001` by default. Set `BACKEND_URL=http://127.0.0.1:8000 npm run dev` if Django runs on a different port.

The header has two modes:

- **Live data**: animals registered in admin, fed by the monitoring station through `POST /api/readings`. The Station card shows when the last packet arrived. An animal with no packet for 60 s is shown grey as "No signal".
- **Simulation**: three virtual cows (`SIM-1` wanders far out, `SIM-2` stays inside, `SIM-3` grazes near the edge) around a 50 m "Simulation pasture".
  - Start/Pause, speed and Reset controls.
  - Each step goes through the same geo-fence and alert code as real data, but simulated animals are flagged `simulated=True` and never appear in Live mode.
  - The browser drives the steps, so the simulation stops when the tab closes.

### Drawing fences

The **Fences** panel (Live mode) draws boundaries on the map with [Leaflet-Geoman](https://github.com/geoman-io/leaflet-geoman):

- **+ Draw fence**: click the map to place corners, click the first corner to close the shape, name it, **Save fence**.
- **Edit**: drag corners; drag a middle point to add one, right-click a corner to remove it. Editing a circle fence turns it into a 24-corner boundary.
- **Delete** asks for a second click and is refused while animals still use the fence.
- Select an animal to move it to another fence with the **Fence for…** dropdown.

A fence with a drawn boundary uses it for inside/outside, and the reading's distance is to the nearest **edge**. Old circle fences keep working, measured from the **center**. A new shape applies from the next packet on. Saving a boundary also stores an enclosing circle (center + radius) that the cattle unit can use as a rough on-board check.

Click an animal to see its 6-hour track. Click an alert to fly to where the breach happened.

## With PostgreSQL (Docker)

```sh
docker compose up -d --wait                # Postgres 17 on localhost:5433
set -a; . ./.env.example; set +a           # load DB + dev admin env vars (Git Bash)
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py createsuperuser --noinput
.venv/Scripts/python manage.py runserver 127.0.0.1:8001
.venv/Scripts/python e2e_test.py           # full flow over HTTP, in another shell with the same env
```

`e2e_test.py` does the following over real HTTP:
1. Logs in to admin.
2. Registers a fence and two animals through the admin forms.
3. Forwards cattle-unit LoRa packets (`C1,lat,lon,status,sats,seq`) the way the station will.
4. Checks rejected input, jitter handling, alert open/close, the movement history and the dashboard page.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | unset (SQLite) | Set `POSTGRES_DB` to use PostgreSQL |
| `STATION_API_KEY` | `dev-station-key` | **Change in production.** Must match the station firmware |
| `DJANGO_SECRET_KEY` | dev key | **Change in production** |
| `DJANGO_DEBUG` | `1` | Set to `0` in production |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated; add your server's domain/IP |
| `BREACH_CONFIRM_READINGS` | `3` | Consecutive outside (or inside) readings needed to open (or close) an alert |

## Station → server contract

```
POST /api/readings
X-API-Key: <STATION_API_KEY>
Content-Type: application/x-www-form-urlencoded

id=C1&lat=27.671239&lon=85.440312&sats=7&rssi=-92&seq=41
```

Only `id`, `lat` and `lon` are required. The response is plain text:

| Response | Meaning |
|---|---|
| `OK IN` / `OK OUT` | Reading stored. The server works out inside/outside itself from the fence in the database |
| `ERR key` (401) | Missing or wrong API key |
| `ERR bad fields` / `ERR bad coords` (400) | Missing or invalid fields, or coordinates out of range / 0,0 |
| `ERR unknown id` (404) | No animal with that tag; register it in admin |

SIM808 sketch:

```
AT+HTTPINIT
AT+HTTPPARA="CID",1
AT+HTTPPARA="URL","http://<server>/api/readings"
AT+HTTPPARA="CONTENT","application/x-www-form-urlencoded"
AT+HTTPPARA="USERDATA","X-API-Key: <key>"
AT+HTTPDATA=<len>,5000   -> send body
AT+HTTPACTION=1
AT+HTTPREAD
```

The SIM808 can't do modern TLS reliably, so this uses plain HTTP. The API key can be read off the network, so if the station has Wi-Fi, use HTTPS over the ESP32's Wi-Fi instead.

## Frontend API

Session auth. Signed-out requests get 401 JSON. POSTs need the `X-CSRFToken` header (read from the `csrftoken` cookie that `/api/me` sets).

| Method | Path | Returns |
|---|---|---|
| GET | `/api/me` | `{user}` (`null` when signed out); sets the CSRF cookie |
| POST | `/api/login`, `/api/logout` | JSON `{username, password}` / nothing |
| GET | `/api/latest?mode=live\|sim` | Each animal's fence, latest reading and whether an alert is open |
| GET | `/api/track/<tag>?hours=6` | `[lat, lon]` points |
| GET | `/api/alerts?mode=live\|sim` | Last 100 alerts |
| GET | `/api/fences?mode=live\|sim` | Fences with `polygon` (`[[lat, lon], ...]` or `null` for a circle) and animal count |
| POST | `/api/fences` | JSON `{name, polygon}`, 3–500 points |
| PATCH / DELETE | `/api/fences/<id>` | JSON `{name?, polygon?}` / delete (400 while animals use it) |
| PATCH | `/api/animals/<tag>` | JSON `{fence: id}` moves the animal to that fence |
| POST | `/api/sim/tick` | Advance every simulated animal one step (creates the sim herd on first call) |
| POST | `/api/sim/reset` | Delete simulated readings and alerts |
