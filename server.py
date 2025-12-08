import asyncio
import json
import random
import requests
import math
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
connected_clients = set()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===============================
# GLOBAL STATE (EMPTY AT START)
# ===============================
trucks_state = {}
current_route_polyline = []   # map route to show
ships_state = {}

# =========================================
# GEOGRAPHY / HUBS
# =========================================
BASRA_PORT = ("Basra Port", 30.5081, 47.7835)
BAGHDAD_DEPOT = ("Baghdad Depot", 33.3152, 44.3661)
MOSUL_DEPOT = ("Mosul Depot", 36.34, 43.12)
ERBIL_DEPOT = ("Erbil Depot", 36.19, 44.01)
KIRKUK_DEPOT = ("Kirkuk Depot", 35.47, 44.39)

HUBS = [BASRA_PORT, BAGHDAD_DEPOT, MOSUL_DEPOT, ERBIL_DEPOT, KIRKUK_DEPOT]

AVG_TRUCK_SPEED_KMH = 80.0


# =========================================
# ROUTING HELPERS
# =========================================
def osrm_route(lat1, lon1, lat2, lon2):
    """Query OSRM for full polyline route."""
    try:
        url = (
            f"https://router.project-osrm.org/route/v1/driving/"
            f"{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        coords = data["routes"][0]["geometry"]["coordinates"]
        return [(c[1], c[0]) for c in coords]  # convert lon/lat → lat/lon
    except:
        # fallback straight line
        steps = 200
        route = []
        for i in range(steps+1):
            t = i / steps
            lat = lat1 + t * (lat2 - lat1)
            lon = lon1 + t * (lon2 - lon1)
            route.append((lat, lon))
        return route


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon/2)**2)
    return 2 * R * math.asin(math.sqrt(a))


def build_route_profile(points):
    cumdist = [0.0]
    total = 0.0
    for i in range(1, len(points)):
        d = haversine_km(points[i-1][0], points[i-1][1],
                         points[i][0], points[i][1])
        total += d
        cumdist.append(total)
    return points, cumdist, total


# =========================================
# START SIMULATION
# =========================================
@app.post("/start-sim")
async def start_sim(data: dict):
    global trucks_state, current_route_polyline, ships_state

    # reset old simulation
    trucks_state = {}
    ships_state = {}

    num_trucks = int(data["numTrucks"])
    origin_name = data["origin"]
    dest_name = data["destination"]
    departure = data["departure"]

    print("START SIM:", num_trucks, origin_name, dest_name, departure)

    # look up coords
    hubs = {h[0]: (h[1], h[2]) for h in HUBS}
    lat1, lon1 = hubs[origin_name]
    lat2, lon2 = hubs[dest_name]

    # compute fresh route
    route = osrm_route(lat1, lon1, lat2, lon2)
    route_points, cumdist, total_km = build_route_profile(route)

    # save the route for display
    current_route_polyline = route_points.copy()

    # create trucks
    for i in range(num_trucks):
        tname = f"TRUCK-{i+1}"

        offset_idx = int(len(route_points) * (i * 0.05))
        offset_idx = min(offset_idx, len(route_points)-1)

        # compute ETA
        route_data = requests.get(
            f"https://router.project-osrm.org/route/v1/driving/"
            f"{lon1},{lat1};{lon2},{lat2}?overview=false"
        ).json()

        duration_sec = route_data["routes"][0]["duration"]
        departed_at = datetime.utcnow()
        eta = departed_at + timedelta(seconds=duration_sec)

        trucks_state[tname] = {
            "id": tname,
            "start_name": origin_name,
            "end_name": dest_name,
            "route": route_points,
            "cumdist": cumdist,
            "total_km": total_km,
            "idx": offset_idx,
            "started_at": departed_at.isoformat() + "Z",
            "eta": eta.isoformat() + "Z",
            "status": "IN_TRANSIT",
        }

    # initialize ships
    ships_state = {
        "SHIP-1": {
            "id": "SHIP-1",
            "lat": BASRA_PORT[1] + 0.05,
            "lon": BASRA_PORT[2] + 0.05,
            "status": "Inbound",
        },
        "SHIP-2": {
            "id": "SHIP-2",
            "lat": BASRA_PORT[1] - 0.05,
            "lon": BASRA_PORT[2] - 0.04,
            "status": "Anchored",
        },
    }
    asyncio.create_task(simulation_loop())
    return {"ok": True}


# =========================================
# STATE UPDATES
# =========================================
def update_trucks():
    for truck in trucks_state.values():
        if truck["status"] == "ARRIVED":
            continue

        idx = truck["idx"]
        if idx >= len(truck["route"]) - 1:
            truck["status"] = "ARRIVED"
            continue

        truck["idx"] += 1

        if truck["idx"] >= len(truck["route"]) - 1:
            truck["status"] = "ARRIVED"


def update_ships():
    for ship in ships_state.values():
        ship["lat"] += (random.random() - 0.5) * 0.01
        ship["lon"] += (random.random() - 0.5) * 0.01


def build_payload():
    update_trucks()
    update_ships()

    trucks_payload = {}
    for tid, tr in trucks_state.items():
        idx = tr["idx"]
        lat, lon = tr["route"][idx]
        done = tr["cumdist"][idx]
        prog = done / tr["total_km"] if tr["total_km"] > 0 else 0.0

        trucks_payload[tid] = {
            "id": tid,
            "lat": lat,
            "lon": lon,
            "eta": tr["eta"],
            "status": tr["status"],
            "start": tr["start_name"],
            "end": tr["end_name"],
            "progress": prog,
        }

    ships_payload = {
        sid: {
            "id": sid,
            "lat": s["lat"],
            "lon": s["lon"],
            "status": s["status"],
        }
        for sid, s in ships_state.items()
    }

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "trucks": trucks_payload,
        "ships": ships_payload,
        "routePolyline": current_route_polyline,
        "ports": [
            {"name": BASRA_PORT[0], "lat": BASRA_PORT[1], "lon": BASRA_PORT[2]}
        ],
        "depots": [
            {"name": BAGHDAD_DEPOT[0], "lat": BAGHDAD_DEPOT[1], "lon": BAGHDAD_DEPOT[2]},
            {"name": MOSUL_DEPOT[0], "lat": MOSUL_DEPOT[1], "lon": MOSUL_DEPOT[2]},
            {"name": ERBIL_DEPOT[0], "lat": ERBIL_DEPOT[1], "lon": ERBIL_DEPOT[2]},
            {"name": KIRKUK_DEPOT[0], "lat": KIRKUK_DEPOT[1], "lon": KIRKUK_DEPOT[2]},
        ],
    }

async def simulation_loop():
    global trucks_state
    first_payload = build_payload()
    for ws in list(connected_clients):
        try:
            await ws.send_json(first_payload)
        except:
            pass

    while True:
        update_trucks()
        update_ships()
        payload = build_payload()

        dead = []
        for ws in list(connected_clients):
            try:
                await ws.send_json(payload)
            except:
                dead.append(ws)

        for ws in dead:
            connected_clients.remove(ws)

        await asyncio.sleep(1)

# =========================================
# WEBSOCKET STREAM
# =========================================
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.add(ws)

    try:
        while True:
            await asyncio.sleep(1)  # just keep alive
    except:
        pass
    finally:
        connected_clients.remove(ws)
        print("[WS] disconnected")


@app.get("/")
async def root():
    return {"status": "Iraq logistics WebSocket server running"}
