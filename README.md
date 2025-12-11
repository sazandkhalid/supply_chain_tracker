# Iraq Logistics Simulation Platform

Real-Time Truck & Ship Simulation • DynamoDB Storage • WebSocket Streaming • Machine Learning Integration

**Frontend:** [https://sazdsan.georgetown.domains](https://sazdsan.georgetown.domains)
**Backend API:** [https://logistics-backend.fly.dev](https://logistics-backend.fly.dev)
**GitHub Repo:** [https://github.com/sazandkhalid/supply_chain_tracker](https://github.com/sazandkhalid/supply_chain_tracker)

---

## Project Overview

This platform simulates real-time logistics operations across Iraq by integrating backend simulation, cloud storage, real-time WebSocket streaming, geospatial visualization, and machine learning. The system models truck routes between major Iraqi hubs and stochastic ship movements near Basra Port. All movement is streamed live to a browser-based dashboard.

The project includes:

* **FastAPI simulation backend** (async, event-driven)
* **AWS DynamoDB** for persistent cloud storage
* **Leaflet.js real-time frontend** with custom markers, polylines, and analytics overlays
* **Unsupervised ML (KMeans)** for operational behavior clustering
* **Supervised ML (Logistic Regression)** for delay probability prediction
* **Quarto static site** deployed to cPanel
* **Backend container** deployed to Fly.io

---

# System Architecture

```
Frontend (Quarto + Leaflet + JS)
         │
         │  WebSocket (1 Hz updates)
         ▼
Backend API (FastAPI + asyncio)
         │
         │  CRUD operations
         ▼
AWS DynamoDB (Shipments Table)
         │
         │  Offline model training
         ▼
Machine Learning (KMeans + Logistic Regression)
```

---

# Features

### Real-Time Truck Simulation

* OSRM polyline routing
* Position updated every second
* ETA calculations and progress tracking

### Ship Movement Simulation

* Stochastic maritime drift around Basra Port
* Real-time visualization

### Cloud Data Storage (AWS DynamoDB)

* Full persistence of:

  * Truck states
  * Ship states
  * Route polylines
  * Cumulative distances
  * ETA and status

### WebSockets

* Backend streams JSON updates to the browser each second
* Frontend automatically updates markers and popups

### Machine Learning Integration

* **KMeans clustering** → categorizes trucks by operational behavior
* **Logistic Regression** → predicts real-time delay likelihood
* Results displayed directly on map popups

---

# Repository Structure

```
supply_chain_tracker/
│
├── server.py                # FastAPI backend simulation engine
├── models/
│     ├── kmeans_speed_cluster.pkl
│     └── delay_model.pkl
├── simulate.js              # Frontend WebSocket + Leaflet logic
├── index.qmd                # Quarto frontend
├── requirements.txt
└── README.md
```

---

# Deployment

### Backend (Fly.io)

```
flyctl deploy
```

Backend must listen on `0.0.0.0:8080`.

Backend URL:
**[https://logistics-backend.fly.dev](https://logistics-backend.fly.dev)**

### Frontend (cPanel via Quarto)

```
quarto render
cp -R _site/* ~/public_html/
```

Frontend URL:
**[https://sazdsan.georgetown.domains](https://sazdsan.georgetown.domains)**

---

# Data Collection & Reproducibility

### Data Source

Data is **fully simulated** by the backend. No external datasets are used.

### How Data Is Generated

1. User starts simulation from frontend.
2. Backend initializes trucks and ships.
3. OSRM generates polyline routes.
4. Each second:

   * Trucks move forward along route
   * Ships drift randomly
   * ML predictions are computed
   * DynamoDB saves state
   * WebSocket streams state

### Exporting Data

```
aws dynamodb scan --table-name Shipments > export.json
```

### Transparency & Reproducibility

Although the DynamoDB table is private, **all data can be regenerated** using:

1. The backend code in this repository
2. The ML training scripts
3. The frontend simulation UI

Everything needed to replicate the system is included.

---

# 🛠 Setup Instructions

### Install Dependencies

```
pip install -r requirements.txt
```

### Run Backend

```
uvicorn server:app --reload --host 0.0.0.0 --port 8080
```

### Run Frontend (Quarto)

```
quarto render
```

Open `_site/index.html`.

---

# Environment Configuration

You must set:

```
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=eu-north-1
DYNAMODB_TABLE_NAME=Shipments
```

For Fly.io, configure via:

```
flyctl secrets set AWS_ACCESS_KEY_ID=...
flyctl secrets set AWS_SECRET_ACCESS_KEY=...
```

---

# Script Explanations

### `server.py`

* Simulation engine
* Routing + geospatial calculations
* DynamoDB persistence
* WebSocket data broadcaster
* ML inference integration

### `simulate.js`

* Real-time WebSocket client
* Leaflet map initialization
* Marker updates + popups
* Visualization of ML results

### `models/`

Contains trained ML models used for inference.

---

# Deployment Instructions

1. Build backend container:

```
flyctl deploy
```

2. Render and upload frontend:

```
quarto render
cp -R _site/* ~/public_html/
```

3. Visit:

* Frontend → **[https://sazdsan.georgetown.domains](https://sazdsan.georgetown.domains)**
* Backend → **[https://logistics-backend.fly.dev](https://logistics-backend.fly.dev)**

---

# Project Status

✔ Fully functioning real-time logistics simulator
✔ Live WebSocket updates
✔ Persistent cloud storage
✔ Machine learning integrated end-to-end
✔ Frontend + backend deployed publicly
