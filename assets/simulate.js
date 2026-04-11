// ===================================================
// 1. WebSocket connection to Railway backend
// ===================================================

const ws = new WebSocket("wss://tradeflow-backend-production.up.railway.app/ws");

console.log("Connecting to WS:", ws.url);

ws.onopen = () => {
    console.log("WebSocket connected to backend");
};

ws.onerror = (e) => {
    console.error("WebSocket error:", e);
    alert("WebSocket could not connect. Backend may be unavailable.");
};

// ===================================================
// 2. Leaflet map setup
// ===================================================
const map = L.map('map').setView([33.3, 44.4], 6);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18
}).addTo(map);

// Storage for markers + route lines
const truckMarkers = {};
const shipMarkers = {};

let routeLine = null;

// Icon styles
const truckIcon = L.icon({
    iconUrl: 'https://cdn-icons-png.flaticon.com/512/741/741407.png',
    iconSize: [32, 32]
});

const shipIcon = L.icon({
    iconUrl: 'https://cdn-icons-png.flaticon.com/512/5362/5362721.png',
    iconSize: [32, 32]
});

// ===================================================
// 3. Incoming WebSocket packets from backend
// ===================================================
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    console.log("Incoming WS update:", data);

    // ---------------- ROUTE POLYLINE ----------------
    if (routeLine) map.removeLayer(routeLine);

    routeLine = L.polyline(data.routePolyline, { color: "blue" }).addTo(map);

    if (data.routePolyline.length > 0) {
        const bounds = L.latLngBounds(data.routePolyline);
        map.fitBounds(bounds);
    }

    // ---------------- TRUCKS ----------------
    Object.values(data.trucks).forEach(t => {
        const delayText =
            (t.delayRisk !== null && t.delayRisk !== undefined)
                ? `${(t.delayRisk * 100).toFixed(1)}%`
                : "N/A";

        const clusterText =
            (t.cluster !== null && t.cluster !== undefined)
                ? t.cluster
                : "N/A";

        const popupHtml = `
            <b>${t.id}</b><br>
            <b>Status:</b> ${t.status}<br>
            <b>Route:</b> ${t.start} → ${t.end}<br>
            <b>ETA:</b> ${t.eta}<br>
            <hr>
            <b>Cluster Profile:</b> ${clusterText}<br>
            <b>Delay Risk:</b> ${delayText}<br>
        `;

        if (!truckMarkers[t.id]) {
            truckMarkers[t.id] = L.marker([t.lat, t.lon], { icon: truckIcon })
                .bindPopup(popupHtml)
                .addTo(map);
        } else {
            truckMarkers[t.id]
                .setLatLng([t.lat, t.lon])
                .setPopupContent(popupHtml);
        }
    });

    // ---------------- SHIPS ----------------
    Object.values(data.ships).forEach(s => {
        if (!shipMarkers[s.id]) {
            shipMarkers[s.id] = L.marker([s.lat, s.lon], { icon: shipIcon })
                .bindPopup(`${s.id}<br>Status: ${s.status}`)
                .addTo(map);
        } else {
            shipMarkers[s.id]
                .setLatLng([s.lat, s.lon])
                .setPopupContent(`${s.id}<br>Status: ${s.status}`);
        }
    });
};
