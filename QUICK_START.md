# Quick Start Guide

## The Problem
If you're seeing CORS errors or WebSocket connection issues, you're likely opening the HTML file directly (`file://`). Browsers block local file access for security.

## Solution: Run a Local Web Server

### Option 1: Python's Built-in Server (Easiest)

```bash
# Navigate to the _site directory
cd _site

# Start a simple HTTP server
python3 -m http.server 8080
```

Then open your browser to: **http://localhost:8080/simulate.html**

### Option 2: Run Both Servers at Once

**Terminal 1 - Backend (FastAPI):**
```bash
# In the project root directory
uvicorn server:app --reload --port 8000
```

**Terminal 2 - Frontend (Web Server):**
```bash
# In the _site directory
cd _site
python3 -m http.server 8080
```

**Then:**
1. Open browser to: http://localhost:8080/index.html
2. Fill out the simulation form
3. Click "Start Simulation"
4. You'll be redirected to the live map

### Option 3: Using Streamlit (Alternative)

```bash
streamlit run app.py
```

This opens at http://localhost:8501

## Important Notes

- **Backend MUST be running** on port 8000 before starting simulation
- **Frontend MUST be served via HTTP** (not file://) for WebSocket to work
- The WebSocket will automatically connect to `ws://localhost:8000/ws` when running locally

## Troubleshooting

**WebSocket Connection Failed:**
- Make sure backend is running: `uvicorn server:app --reload --port 8000`
- Check browser console - it should show `Using WebSocket: ws://localhost:8000/ws`

**CORS Errors:**
- Don't open HTML files directly (file://)
- Use a local web server instead (python -m http.server)

**Trucks Not Showing:**
- Check backend terminal for logs
- Check browser console (F12) for errors
- Verify DynamoDB is accessible and has data

