const API_BASE = "https://tradeflow-backend-production.up.railway.app";

async function startSim() {
    const numTrucks = document.getElementById("numTrucks").value;
    const origin = document.getElementById("origin").value;
    const destination = document.getElementById("destination").value;
    const departure = document.getElementById("departure").value;

    const payload = { numTrucks, origin, destination, departure };

    const resp = await fetch(`${API_BASE}/start-sim`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });

    const result = await resp.json();
    if (result.ok) {
        window.location.href = "simulate.html";
    } else {
        alert(result.error);
    }
}