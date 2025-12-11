# Debugging Guide - Trucks Not Showing on Map

I've added comprehensive debugging to help identify the issue. Follow these steps:

## Step 1: Check Backend Server Logs

When you start the server, you should see:
```
🔗 Connected to DynamoDB table 'Shipments' in region 'eu-north-1'
```

When you click "Start Simulation", look for:
```
[START] Simulation started with X trucks from Origin to Destination
[SIM] Starting simulation loop...
[SIM] First payload: X trucks, Y ships
[SIM] Connected clients: 1
[SIM] Sent initial payload to client
```

**What to check:**
- Are trucks being created? Look for the count in the log
- Are clients connected? Should be at least 1
- Any error messages?

## Step 2: Check Browser Console

Open your browser's Developer Tools (F12) and check the Console tab.

**Expected logs:**
```
[WS] Attempting to connect to ws://localhost:8000/ws
[WS] ✅ Connected to ws://localhost:8000/ws
[WS] 📨 Received message
[WS] Data - Trucks: 4 Ships: 2 Route points: 200
[MAP] Processing 4 trucks
[MAP] ➕ Creating marker for TRUCK-1 at 30.5081 47.7835
```

**What to check:**
- Is WebSocket connected? If not, check if server is running
- Are trucks in the data? Look for the count
- Are markers being created?

## Step 3: Common Issues

### Issue: WebSocket Not Connecting
**Symptoms:** Console shows `[WS] ❌ Error` or connection fails
**Solution:** 
- Make sure server is running: `uvicorn server:app --reload --port 8000`
- Check if port 8000 is available
- If using file:// protocol, start a local server instead

### Issue: No Trucks in Data
**Symptoms:** Console shows `[WS] Data - Trucks: 0 Ships: X`
**Solution:**
- Check backend logs - are trucks being created in DynamoDB?
- Verify DynamoDB table exists and is accessible
- Check AWS credentials

### Issue: Trucks in Data But Not on Map
**Symptoms:** Console shows trucks but no markers
**Solution:**
- Check for JavaScript errors in console
- Verify truck coordinates are valid numbers
- Check if Leaflet map is initialized (zoom to see if map loads)

### Issue: Simulation Loop Not Running
**Symptoms:** No logs after initial connection
**Solution:**
- The simulation loop should start automatically when you click "Start Simulation"
- Check backend logs for errors in `simulation_loop()`
- Verify the `/start-sim` endpoint was called successfully

## Step 4: Manual Testing

Test the endpoints directly:

```bash
# Test if server is running
curl http://localhost:8000/

# Test start simulation
curl -X POST http://localhost:8000/start-sim \
  -H "Content-Type: application/json" \
  -d '{"numTrucks": 2, "origin": "Basra Port", "destination": "Baghdad Depot", "departure": "2024-01-01T00:00:00"}'
```

## Step 5: Check DynamoDB

Verify data is actually in DynamoDB:

```bash
# List all items with TRUCK prefix
aws dynamodb scan \
  --table-name Shipments \
  --filter-expression "begins_with(truckId, :prefix)" \
  --expression-attribute-values '{":prefix":{"S":"TRUCK-"}}' \
  --region eu-north-1
```

You should see trucks with IDs like `TRUCK-1`, `TRUCK-2`, etc.

## Still Having Issues?

If trucks still don't show up:
1. Share the backend server logs
2. Share the browser console output
3. Check if there are any JavaScript errors in the console

The debugging output will help identify exactly where the issue is!

