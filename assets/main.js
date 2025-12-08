async function startSim() {
    const numTrucks = document.getElementById("numTrucks").value;
    const origin = document.getElementById("origin").value;
    const destination = document.getElementById("destination").value;
    const departure = document.getElementById("departure").value;

    const payload = {
        numTrucks,
        origin,
        destination,
        departure
    };

    console.log("Sending to backend:", payload);

    const resp = await fetch("http://localhost:8000/start-sim", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
    });

    if (!resp.ok) {
        alert("Failed to start simulation");
        return;
    }

    // After backend generates trucks → go to map
    window.location.href = "simulate.html";
}
