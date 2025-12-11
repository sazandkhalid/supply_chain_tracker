import streamlit as st
import boto3
import os
import folium
from streamlit_folium import st_folium
import requests
import random
from datetime import datetime, timedelta
import math
from decimal import Decimal

# ======================================================
# SESSION STATE (for UI, not required for data)
# ======================================================
if "initialized" not in st.session_state:
    st.session_state.initialized = False

# ======================================================
# HELPERS
# ======================================================
def serialize_route(route):
    """Convert list of (lat, lon) to DynamoDB-friendly list of dicts with Decimals."""
    return [
        {
            "lat": Decimal(str(p[0])),
            "lon": Decimal(str(p[1]))
        }
        for p in route
    ]

# ======================================================
# MAP HUBS
# ======================================================
MAJOR_HUBS = [
    ("Basra Port", 30.5081, 47.7835),
    ("Baghdad Depot", 33.3152, 44.3661),
    ("Mosul", 36.34, 43.12),
    ("Erbil", 36.19, 44.01),
    ("Kirkuk", 35.47, 44.39),
]

# ======================================================
# OSRM ROUTING
# ======================================================
def osrm_route(lat1, lon1, lat2, lon2):
    url = (
        f"https://router.project-osrm.org/route/v1/driving/"
        f"{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
    )
    r = requests.get(url).json()
    coords = r["routes"][0]["geometry"]["coordinates"]
    # OSRM gives [lon, lat]; convert to (lat, lon)
    return [(c[1], c[0]) for c in coords]

# ======================================================
# HAVERSINE DISTANCE
# ======================================================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

# ======================================================
# ETA CALCULATION
# ======================================================
def estimate_eta(route):
    """route is list of (lat, lon) tuples."""
    if len(route) < 2:
        return datetime.utcnow().isoformat() + "Z"

    total_dist = 0
    for i in range(len(route) - 1):
        lat1, lon1 = route[i]
        lat2, lon2 = route[i + 1]
        total_dist += haversine(lat1, lon1, lat2, lon2)

    avg_speed = 80  # km/h
    hours = total_dist / avg_speed if avg_speed > 0 else 0
    return (datetime.utcnow() + timedelta(hours=hours)).isoformat() + "Z"

# ======================================================
# CREATE NEW TRUCK ROUTE
# ======================================================
def create_truck_route(table, truck_id):
    start_name, s_lat, s_lon = random.choice(MAJOR_HUBS)
    end_name, e_lat, e_lon = random.choice(MAJOR_HUBS)

    while end_name == start_name:
        end_name, e_lat, e_lon = random.choice(MAJOR_HUBS)

    route = osrm_route(s_lat, s_lon, e_lat, e_lon)

    item = {
        "truckId": truck_id,
        "start": start_name,
        "end": end_name,
        "lat": Decimal(str(route[0][0])),
        "lon": Decimal(str(route[0][1])),
        "route": serialize_route(route),
        "idx": 0,
        "status": "IN_TRANSIT",
        "eta": estimate_eta(route),
    }

    table.put_item(Item=item)
    return item

# ======================================================
# MOVE TRUCK ALONG ROUTE
# ======================================================
def update_truck_position(table, truck):
    route = truck["route"]
    idx = int(truck["idx"])  # may be Decimal

    # if already arrived or at end
    if truck.get("status") == "ARRIVED" or idx >= len(route) - 1:
        truck["status"] = "ARRIVED"
        return truck

    idx += 1
    point = route[idx]

    # route element may be dict or tuple
    if isinstance(point, dict):
        lat = float(point["lat"])
        lon = float(point["lon"])
    else:
        lat = float(point[0])
        lon = float(point[1])

    truck["idx"] = idx
    truck["lat"] = lat
    truck["lon"] = lon

    # remaining route for ETA calculation (convert to tuples)
    remaining = []
    for p in route[idx:]:
        if isinstance(p, dict):
            remaining.append((float(p["lat"]), float(p["lon"])))
        else:
            remaining.append((float(p[0]), float(p[1])))

    truck["eta"] = estimate_eta(remaining)

    table.update_item(
        Key={"truckId": truck["truckId"]},
        UpdateExpression="SET lat=:a, lon=:b, idx=:c, eta=:d, #s=:e",
        ExpressionAttributeValues={
            ":a": Decimal(str(lat)),
            ":b": Decimal(str(lon)),
            ":c": idx,
            ":d": truck["eta"],
            ":e": truck["status"],
        },
        ExpressionAttributeNames={"#s": "status"},
    )

    return truck

# ======================================================
# STREAMLIT UI
# ======================================================
st.title("🇮🇶 Iraq Supply Chain – Live Truck Tracker")

# DynamoDB
# Use environment variables with fallback defaults
AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "eu-north-1"))
DYNAMODB_TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "Shipments")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE_NAME)

TRUCKS = ["TRUCK-1", "TRUCK-2", "TRUCK-3"]

# Initialize routes if not exist
for t_id in TRUCKS:
    resp = table.get_item(Key={"truckId": t_id})
    if "Item" not in resp:
        create_truck_route(table, t_id)

# Fetch current truck states
resp = table.scan()
trucks = resp["Items"]

# --- Controls ---
st.subheader("Simulation Control")
col1, col2 = st.columns(2)
with col1:
    step_clicked = st.button("🚚 Advance trucks by 1 step")
with col2:
    reload_clicked = st.button("🔄 Reload positions")

# If step button clicked: advance each truck one waypoint
if step_clicked:
    # re-fetch latest before updating
    resp = table.scan()
    trucks = resp["Items"]
    updated = []
    for t in trucks:
        updated.append(update_truck_position(table, t))
    trucks = updated  # use updated list for map

elif reload_clicked:
    # just re-fetch without moving
    resp = table.scan()
    trucks = resp["Items"]

# ======================================================
# DRAW MAP
# ======================================================
# If there are no trucks (shouldn't happen), center on Iraq
if trucks:
    first = trucks[0]
    center_lat = float(first["lat"])
    center_lon = float(first["lon"])
else:
    center_lat, center_lon = 33.0, 44.0

m = folium.Map(location=[center_lat, center_lon], zoom_start=6)

for t in trucks:
    lat = float(t["lat"])
    lon = float(t["lon"])

    # marker
    folium.Marker(
        location=[lat, lon],
        tooltip=(
            f"{t['truckId']} → {t['end']} — "
            f"{t['status']} ETA: {t['eta']}"
        ),
        icon=folium.Icon(
            color="green" if t["status"] == "ARRIVED" else "red"
        ),
    ).add_to(m)

    # route polyline
    route_points = []
    for p in t["route"]:
        if isinstance(p, dict):
            route_points.append((float(p["lat"]), float(p["lon"])))
        else:
            route_points.append((float(p[0]), float(p[1])))

    folium.PolyLine(
        locations=route_points,
        color="blue",
        weight=2,
        opacity=0.8,
    ).add_to(m)

st_folium(m, width=900, height=600)
