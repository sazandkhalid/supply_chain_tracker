import asyncio
import json
import random
import requests
import math
import boto3
import os
from decimal import Decimal
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from boto3.dynamodb.conditions import Attr
import joblib

app = FastAPI()
connected_clients = set()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===============================
# DYNAMODB SETUP (lazy)
# ===============================
# Use environment variables with fallback defaults.  boto3 won't verify
# credentials until the first API call, so this import is always safe —
# but we wrap the resource creation in try/except so a misconfigured
# Railway environment (no AWS creds at all) still lets the rest of the
# unified app boot and serve compliance traffic.
AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "eu-north-1"))
DYNAMODB_TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "Shipments")

try:
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    print(f"🔗 Connected to DynamoDB table '{DYNAMODB_TABLE_NAME}' in region '{AWS_REGION}'")
except Exception as e:
    print(f"⚠️  DynamoDB init failed: {e}. Simulation endpoints that touch DynamoDB will return errors; the rest of the app still boots.")
    dynamodb = None
    table = None

kmeans_model = None
delay_model = None

try:
    kmeans_model = joblib.load("models/kmeans_speed_cluster.pkl")
    print("🤖 Loaded KMeans speed clustering model")
except Exception as e:
    print(f"⚠️ Could not load KMeans model: {e}")

try:
    delay_model = joblib.load("models/delay_model.pkl")
    print("🤖 Loaded delay risk model")
except Exception as e:
    print(f"⚠️ Could not load delay model: {e}")

# Helper to serialize route for DynamoDB
def serialize_route(route):
    """Convert list of (lat, lon) to DynamoDB-friendly list of dicts with Decimals."""
    return [
        {
            "lat": Decimal(str(p[0])),
            "lon": Decimal(str(p[1]))
        }
        for p in route
    ]

# Helper to deserialize route from DynamoDB
def deserialize_route(route_data):
    """Convert DynamoDB route (list of dicts) to list of (lat, lon) tuples."""
    if isinstance(route_data, list) and len(route_data) > 0:
        if isinstance(route_data[0], dict):
            return [(float(p["lat"]), float(p["lon"])) for p in route_data]
    return route_data  # fallback if already in tuple format

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
    try:
        # Clear old simulation data from DynamoDB
        # Delete all trucks (handle pagination)
        last_evaluated_key = None
        while True:
            if last_evaluated_key:
                scan_response = table.scan(
                    ProjectionExpression="truckId",
                    FilterExpression="begins_with(truckId, :prefix)",
                    ExpressionAttributeValues={":prefix": "TRUCK-"},
                    ExclusiveStartKey=last_evaluated_key
                )
            else:
                scan_response = table.scan(
                    ProjectionExpression="truckId",
                    FilterExpression="begins_with(truckId, :prefix)",
                    ExpressionAttributeValues={":prefix": "TRUCK-"}
                )
            
            for item in scan_response.get("Items", []):
                table.delete_item(Key={"truckId": item["truckId"]})
            
            last_evaluated_key = scan_response.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break
        
        # Delete all ships (handle pagination)
        last_evaluated_key = None
        while True:
            if last_evaluated_key:
                scan_response = table.scan(
                    ProjectionExpression="truckId",
                    FilterExpression="begins_with(truckId, :prefix)",
                    ExpressionAttributeValues={":prefix": "SHIP-"},
                    ExclusiveStartKey=last_evaluated_key
                )
            else:
                scan_response = table.scan(
                    ProjectionExpression="truckId",
                    FilterExpression="begins_with(truckId, :prefix)",
                    ExpressionAttributeValues={":prefix": "SHIP-"}
                )
            
            for item in scan_response.get("Items", []):
                table.delete_item(Key={"truckId": item["truckId"]})
            
            last_evaluated_key = scan_response.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break
        
        # Delete route config
        try:
            table.delete_item(Key={"truckId": "ROUTE_CONFIG"})
        except:
            pass

        num_trucks = int(data["numTrucks"])
        origin_name = data["origin"]
        dest_name = data["destination"]
        departure = data["departure"]

        print("START SIM:", num_trucks, origin_name, dest_name, departure)

        # look up coords
        hubs = {h[0]: (h[1], h[2]) for h in HUBS}
        
        if origin_name not in hubs:
            return {"ok": False, "error": f"Invalid origin: {origin_name}. Available: {list(hubs.keys())}"}
        if dest_name not in hubs:
            return {"ok": False, "error": f"Invalid destination: {dest_name}. Available: {list(hubs.keys())}"}
        if origin_name == dest_name:
            return {"ok": False, "error": "Origin and destination must be different"}
        if num_trucks < 1 or num_trucks > 20:
            return {"ok": False, "error": "Number of trucks must be between 1 and 20"}
        
        lat1, lon1 = hubs[origin_name]
        lat2, lon2 = hubs[dest_name]

        # compute fresh route
        route = osrm_route(lat1, lon1, lat2, lon2)
        route_points, cumdist, total_km = build_route_profile(route)

        # Save route polyline to DynamoDB
        route_config_item = {
            "truckId": "ROUTE_CONFIG",
            "routePolyline": serialize_route(route_points),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        table.put_item(Item=route_config_item)

        # create trucks and save to DynamoDB
        for i in range(num_trucks):
            tname = f"TRUCK-{i+1}"

            offset_idx = int(len(route_points) * (i * 0.05))
            offset_idx = min(offset_idx, len(route_points)-1)

            # Get current position
            current_pos = route_points[offset_idx]

            # compute ETA
            departed_at = datetime.utcnow()
            try:
                route_data = requests.get(
                    f"https://router.project-osrm.org/route/v1/driving/"
                    f"{lon1},{lat1};{lon2},{lat2}?overview=false",
                    timeout=5
                ).json()
                duration_sec = route_data["routes"][0]["duration"]
                planned_speed_kmh = 0.0
                try:
                    planned_speed_kmh = total_km / (duration_sec / 3600.0) if duration_sec > 0 else AVG_TRUCK_SPEED_KMH
                except Exception:
                    planned_speed_kmh = AVG_TRUCK_SPEED_KMH
                eta = departed_at + timedelta(seconds=duration_sec)
            except:
                # Fallback: estimate based on distance and average speed
                hours = total_km / AVG_TRUCK_SPEED_KMH if AVG_TRUCK_SPEED_KMH > 0 else 1
                eta = departed_at + timedelta(hours=hours)

            # Store cumulative distances as a list
            cumdist_serialized = [Decimal(str(d)) for d in cumdist]

            truck_item = {
                "truckId": tname,
                "start": origin_name,
                "end": dest_name,
                "lat": Decimal(str(current_pos[0])),
                "lon": Decimal(str(current_pos[1])),
                "route": serialize_route(route_points),
                "cumdist": cumdist_serialized,
                "total_km": Decimal(str(total_km)),
                "idx": offset_idx,
                "started_at": departed_at.isoformat() + "Z",
                "eta": eta.isoformat() + "Z",
                "status": "IN_TRANSIT",
                "plan_speed_kmh": Decimal(str(planned_speed_kmh)),
            }
            table.put_item(Item=truck_item)

        # initialize ships in DynamoDB
        ships = [
            {
                "truckId": "SHIP-1",
                "lat": Decimal(str(BASRA_PORT[1] + 0.05)),
                "lon": Decimal(str(BASRA_PORT[2] + 0.05)),
                "status": "Inbound",
                "entityType": "SHIP"
            },
            {
                "truckId": "SHIP-2",
                "lat": Decimal(str(BASRA_PORT[1] - 0.05)),
                "lon": Decimal(str(BASRA_PORT[2] - 0.04)),
                "status": "Anchored",
                "entityType": "SHIP"
            },
        ]
        for ship in ships:
            table.put_item(Item=ship)
        
        # Start simulation loop in background
        loop_task = asyncio.create_task(simulation_loop())
        print(f"[START] Simulation started with {num_trucks} trucks from {origin_name} to {dest_name}")
        return {"ok": True, "message": f"Simulation started with {num_trucks} trucks"}
    except Exception as e:
        print(f"Error starting simulation: {e}")
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


# =========================================
# STATE UPDATES
# =========================================
def update_trucks():
    # Fetch all trucks from DynamoDB (handle pagination)
    trucks = []
    last_evaluated_key = None
    while True:
        if last_evaluated_key:
            scan_response = table.scan(
                FilterExpression="begins_with(truckId, :prefix)",
                ExpressionAttributeValues={":prefix": "TRUCK-"},
                ExclusiveStartKey=last_evaluated_key
            )
        else:
            scan_response = table.scan(
                FilterExpression="begins_with(truckId, :prefix)",
                ExpressionAttributeValues={":prefix": "TRUCK-"}
            )
        
        trucks.extend(scan_response.get("Items", []))
        last_evaluated_key = scan_response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break
    
    for truck in trucks:
        if truck.get("status") == "ARRIVED":
            continue

        idx = int(truck["idx"])
        route = deserialize_route(truck["route"])
        
        if idx >= len(route) - 1:
            # Mark as arrived
            table.update_item(
                Key={"truckId": truck["truckId"]},
                UpdateExpression="SET #s = :status",
                ExpressionAttributeValues={":status": "ARRIVED"},
                ExpressionAttributeNames={"#s": "status"}
            )
            continue

        # Move to next point
        idx += 1
        new_pos = route[idx]
        
        # Update in DynamoDB
        if idx >= len(route) - 1:
            # Mark as arrived
            table.update_item(
                Key={"truckId": truck["truckId"]},
                UpdateExpression="SET idx = :idx, lat = :lat, lon = :lon, #s = :status",
                ExpressionAttributeValues={
                    ":idx": idx,
                    ":lat": Decimal(str(new_pos[0])),
                    ":lon": Decimal(str(new_pos[1])),
                    ":status": "ARRIVED"
                },
                ExpressionAttributeNames={"#s": "status"}
            )
        else:
            table.update_item(
                Key={"truckId": truck["truckId"]},
                UpdateExpression="SET idx = :idx, lat = :lat, lon = :lon",
                ExpressionAttributeValues={
                    ":idx": idx,
                    ":lat": Decimal(str(new_pos[0])),
                    ":lon": Decimal(str(new_pos[1]))
                }
            )


def update_ships():
    # Fetch all ships from DynamoDB (handle pagination)
    ships = []
    last_evaluated_key = None
    while True:
        if last_evaluated_key:
            scan_response = table.scan(
                FilterExpression="begins_with(truckId, :prefix)",
                ExpressionAttributeValues={":prefix": "SHIP-"},
                ExclusiveStartKey=last_evaluated_key
            )
        else:
            scan_response = table.scan(
                FilterExpression="begins_with(truckId, :prefix)",
                ExpressionAttributeValues={":prefix": "SHIP-"}
            )
        
        ships.extend(scan_response.get("Items", []))
        last_evaluated_key = scan_response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break
    
    for ship in ships:
        current_lat = float(ship["lat"])
        current_lon = float(ship["lon"])
        
        # Update position slightly
        new_lat = current_lat + (random.random() - 0.5) * 0.01
        new_lon = current_lon + (random.random() - 0.5) * 0.01
        
        # Update in DynamoDB
        table.update_item(
            Key={"truckId": ship["truckId"]},
            UpdateExpression="SET lat = :lat, lon = :lon",
            ExpressionAttributeValues={
                ":lat": Decimal(str(new_lat)),
                ":lon": Decimal(str(new_lon))
            }
        )


def build_payload():
    trucks_payload = {}
    ships_payload = {}
    route_polyline = []

    try:
        update_trucks()
        update_ships()

        # =========================
        # FETCH ALL TRUCKS
        # =========================
        trucks = []
        last_evaluated_key = None

        while True:
            if last_evaluated_key:
                scan_response = table.scan(
                    FilterExpression="begins_with(truckId, :prefix)",
                    ExpressionAttributeValues={":prefix": "TRUCK-"},
                    ExclusiveStartKey=last_evaluated_key
                )
            else:
                scan_response = table.scan(
                    FilterExpression="begins_with(truckId, :prefix)",
                    ExpressionAttributeValues={":prefix": "TRUCK-"}
                )

            trucks.extend(scan_response.get("Items", []))
            last_evaluated_key = scan_response.get("LastEvaluatedKey")

            if not last_evaluated_key:
                break

        # =========================
        # PROCESS TRUCKS (NOW OUTSIDE LOOP!)
        # =========================
        for truck in trucks:
            tid = truck["truckId"]
            idx = int(truck["idx"])
            route = deserialize_route(truck["route"])

            if idx < len(route):
                lat, lon = route[idx]
            else:
                lat = float(truck["lat"])
                lon = float(truck["lon"])

            cumdist = [float(d) for d in truck.get("cumdist", [])]
            total_km = float(truck.get("total_km", 0))

            if idx < len(cumdist) and total_km > 0:
                done = cumdist[idx]
                prog = done / total_km
            else:
                prog = 0.0

            # ML features
            plan_speed_kmh = float(truck.get("plan_speed_kmh", AVG_TRUCK_SPEED_KMH))
            dist_remaining = max(total_km - cumdist[idx], 0) if total_km > 0 and idx < len(cumdist) else 0

            cluster = None
            delay_risk = None

            if kmeans_model:
                try:
                    cluster = int(kmeans_model.predict([[plan_speed_kmh, dist_remaining]])[0])
                except Exception as e:
                    print(f"[ML] KMeans error for {tid}: {e}")

            if delay_model:
                try:
                    proba = delay_model.predict_proba([[plan_speed_kmh, dist_remaining, 0]])[0]
                    delay_risk = float(proba[1])
                except Exception as e:
                    print(f"[ML] Delay model error for {tid}: {e}")

            trucks_payload[tid] = {
                "id": tid,
                "lat": lat,
                "lon": lon,
                "eta": truck.get("eta", ""),
                "status": truck.get("status", "IN_TRANSIT"),
                "start": truck.get("start", ""),
                "end": truck.get("end", ""),
                "progress": prog,
                "planSpeedKmh": plan_speed_kmh,
                "distRemaining": dist_remaining,
                "cluster": cluster,
                "delayRisk": delay_risk,
            }

        # =========================
        # FETCH & PROCESS SHIPS
        # =========================
        ships = []
        last_evaluated_key = None

        while True:
            if last_evaluated_key:
                scan_response = table.scan(
                    FilterExpression="begins_with(truckId, :prefix)",
                    ExpressionAttributeValues={":prefix": "SHIP-"},
                    ExclusiveStartKey=last_evaluated_key
                )
            else:
                scan_response = table.scan(
                    FilterExpression="begins_with(truckId, :prefix)",
                    ExpressionAttributeValues={":prefix": "SHIP-"}
                )

            ships.extend(scan_response.get("Items", []))
            last_evaluated_key = scan_response.get("LastEvaluatedKey")

            if not last_evaluated_key:
                break

        for ship in ships:
            sid = ship["truckId"]
            ships_payload[sid] = {
                "id": sid,
                "lat": float(ship["lat"]),
                "lon": float(ship["lon"]),
                "status": ship.get("status", "Unknown"),
            }

        # =========================
        # ROUTE CONFIG
        # =========================
        route_config = table.get_item(Key={"truckId": "ROUTE_CONFIG"})
        if "Item" in route_config:
            route_polyline = deserialize_route(route_config["Item"]["routePolyline"])

    except Exception as e:
        print("[PAYLOAD] Error:", e)
        import traceback
        traceback.print_exc()

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "trucks": trucks_payload,
        "ships": ships_payload,
        "routePolyline": route_polyline,
        "ports": [{"name": BASRA_PORT[0], "lat": BASRA_PORT[1], "lon": BASRA_PORT[2]}],
        "depots": [
            {"name": BAGHDAD_DEPOT[0], "lat": BAGHDAD_DEPOT[1], "lon": BAGHDAD_DEPOT[2]},
            {"name": MOSUL_DEPOT[0], "lat": MOSUL_DEPOT[1], "lon": MOSUL_DEPOT[2]},
            {"name": ERBIL_DEPOT[0], "lat": ERBIL_DEPOT[1], "lon": ERBIL_DEPOT[2]},
            {"name": KIRKUK_DEPOT[0], "lat": KIRKUK_DEPOT[1], "lon": KIRKUK_DEPOT[2]},
        ],
    }
    # Initialize payloads early so they're always defined
    trucks_payload = {}
    ships_payload = {}
    route_polyline = []
    
    try:
        update_trucks()
        update_ships()

        # Fetch trucks from DynamoDB (handle pagination)
        trucks = []
        last_evaluated_key = None
        while True:
            if last_evaluated_key:
                scan_response = table.scan(
                    FilterExpression="begins_with(truckId, :prefix)",
                    ExpressionAttributeValues={":prefix": "TRUCK-"},
                    ExclusiveStartKey=last_evaluated_key
                )
            else:
                scan_response = table.scan(
                    FilterExpression="begins_with(truckId, :prefix)",
                    ExpressionAttributeValues={":prefix": "TRUCK-"}
                )
            
            trucks.extend(scan_response.get("Items", []))
            last_evaluated_key = scan_response.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break
        
        # Build trucks payload
        for truck in trucks:
            tid = truck["truckId"]
            idx = int(truck["idx"])
            route = deserialize_route(truck["route"])
            
            # Get current position from route
            if idx < len(route):
                lat, lon = route[idx]
            else:
                lat = float(truck["lat"])
                lon = float(truck["lon"])
            
            # Calculate progress
            cumdist = [float(d) for d in truck.get("cumdist", [])]
            total_km = float(truck.get("total_km", 0))
            if idx < len(cumdist) and total_km > 0:
                done = cumdist[idx]
                prog = done / total_km
            else:
                prog = 0.0

            # =============================
            # ML FEATURES (correct indentation!)
            # =============================
            plan_speed_kmh = float(truck.get("plan_speed_kmh", AVG_TRUCK_SPEED_KMH))

            dist_remaining = 0.0
            if total_km > 0 and idx < len(cumdist):
                dist_remaining = max(total_km - cumdist[idx], 0.0)

            # Defaults
            cluster = None
            delay_risk = None

            # Unsupervised: KMeans cluster
            if kmeans_model is not None:
                try:
                    cluster = int(kmeans_model.predict([[plan_speed_kmh, dist_remaining]])[0])
                except Exception as e:
                    print(f"[ML] KMeans error for {tid}: {e}")

            # Supervised: logistic regression delay risk
            stops_feature = 0
            if delay_model is not None:
                try:
                    proba = delay_model.predict_proba([[plan_speed_kmh, dist_remaining, stops_feature]])[0]
                    delay_risk = float(proba[1])
                except Exception as e:
                    print(f"[ML] Delay model error for {tid}: {e}")

            # =============================
            # FINAL TRUCK PAYLOAD
            # =============================
            trucks_payload[tid] = {
                "id": tid,
                "lat": lat,
                "lon": lon,
                "eta": truck.get("eta", ""),
                "status": truck.get("status", "IN_TRANSIT"),
                "start": truck.get("start", ""),
                "end": truck.get("end", ""),
                "progress": prog,
                "planSpeedKmh": plan_speed_kmh,
                "distRemaining": dist_remaining,
                "cluster": cluster,
                "delayRisk": delay_risk,
            }

        # Fetch ships from DynamoDB (handle pagination)
        ships = []
        last_evaluated_key = None
        while True:
            if last_evaluated_key:
                scan_response = table.scan(
                    FilterExpression="begins_with(truckId, :prefix)",
                    ExpressionAttributeValues={":prefix": "SHIP-"},
                    ExclusiveStartKey=last_evaluated_key
                )
            else:
                scan_response = table.scan(
                    FilterExpression="begins_with(truckId, :prefix)",
                    ExpressionAttributeValues={":prefix": "SHIP-"}
                )
            
            ships.extend(scan_response.get("Items", []))
            last_evaluated_key = scan_response.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break
        
        # Build ships payload
        for ship in ships:
            sid = ship["truckId"]
            ships_payload[sid] = {
                "id": sid,
                "lat": float(ship["lat"]),
                "lon": float(ship["lon"]),
                "status": ship.get("status", "Unknown"),
            }

        # Fetch route polyline from DynamoDB
        try:
            route_config = table.get_item(Key={"truckId": "ROUTE_CONFIG"})
            if "Item" in route_config:
                route_polyline = deserialize_route(route_config["Item"]["routePolyline"])
            else:
                route_polyline = []
        except Exception as e:
            print(f"[BUILD_PAYLOAD] Error fetching route: {e}")
            route_polyline = []

    except Exception as e:
        print(f"[BUILD_PAYLOAD] Error: {e}")
        import traceback
        traceback.print_exc()
        # Continue with empty payloads that were initialized above

    # Return payload (always has valid structure even if errors occurred)
    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "trucks": trucks_payload,
        "ships": ships_payload,
        "routePolyline": route_polyline,
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
    print("[SIM] Starting simulation loop...")
    try:
        first_payload = build_payload()
        print(f"[SIM] First payload: {len(first_payload.get('trucks', {}))} trucks, {len(first_payload.get('ships', {}))} ships")
        print(f"[SIM] Connected clients: {len(connected_clients)}")
        
        for ws in list(connected_clients):
            try:
                await ws.send_json(first_payload)
                print(f"[SIM] Sent initial payload to client")
            except Exception as e:
                print(f"[SIM] Error sending initial payload: {e}")
    except Exception as e:
        print(f"[SIM] Error building initial payload: {e}")
        import traceback
        traceback.print_exc()

    loop_count = 0
    while True:
        try:
            # build_payload() already calls update_trucks() and update_ships()
            payload = build_payload()
            loop_count += 1
            
            if loop_count % 10 == 0:  # Log every 10 iterations
                print(f"[SIM] Loop #{loop_count}: {len(payload.get('trucks', {}))} trucks, {len(payload.get('ships', {}))} ships, {len(connected_clients)} clients")

            dead = []
            for ws in list(connected_clients):
                try:
                    await ws.send_json(payload)
                except Exception as e:
                    print(f"[SIM] Error sending to client: {e}")
                    dead.append(ws)

            for ws in dead:
                connected_clients.remove(ws)

        except Exception as e:
            print(f"[SIM] Error in simulation loop: {e}")
            import traceback
            traceback.print_exc()

        await asyncio.sleep(1)

# =========================================
# WEBSOCKET STREAM
# =========================================
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.add(ws)
    print(f"[WS] Client connected. Total clients: {len(connected_clients)}")

    try:
        while True:
            await asyncio.sleep(1)  # just keep alive
    except Exception as e:
        print(f"[WS] Error in WebSocket: {e}")
    finally:
        connected_clients.remove(ws)
        print(f"[WS] Client disconnected. Remaining clients: {len(connected_clients)}")


@app.get("/")
async def root():
    return {"status": "Iraq logistics WebSocket server running"}
