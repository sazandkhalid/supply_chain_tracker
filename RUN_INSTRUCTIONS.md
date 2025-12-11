# How to Run the Supply Chain Tracker

This guide explains how to run both the backend API server and the frontend web application.

## Prerequisites

1. **Python 3.8+** installed
2. **AWS Account** with DynamoDB access
3. **AWS Credentials** configured (see AWS Setup below)

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. AWS Setup

You need AWS credentials configured to access DynamoDB. You can do this in one of these ways:

**Option A: AWS CLI Configuration**
```bash
aws configure
```
Enter your AWS Access Key ID, Secret Access Key, and region (`eu-north-1`).

**Option B: Environment Variables**
```bash
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=eu-north-1
```

**Option C: IAM Role** (if running on EC2/ECS/Lambda)

### 3. Configure DynamoDB Settings

The code uses environment variables for DynamoDB configuration. If your table name or region is different, set these:

```bash
# Set your DynamoDB table name (default: "Shipments")
export DYNAMODB_TABLE_NAME=YourTableName

# Set your AWS region (default: "eu-north-1")
export AWS_REGION=your-region
# OR
export AWS_DEFAULT_REGION=your-region
```

**Table Requirements:**
- **Primary Key**: `truckId` (String type)
- The code will work with your existing table if it has this primary key structure

If you need to create a new table:
```bash
aws dynamodb create-table \
    --table-name Shipments \
    --attribute-definitions AttributeName=truckId,AttributeType=S \
    --key-schema AttributeName=truckId,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region eu-north-1
```

## Running the Application

### Backend Server (FastAPI)

The backend provides the API and WebSocket endpoints for real-time updates.

```bash
# Using uvicorn directly
uvicorn server:app --host 0.0.0.0 --port 8000 --reload

# Or using Python with uvicorn
python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

The server will start on `http://localhost:8000`

**Available Endpoints:**
- `GET /` - Health check
- `POST /start-sim` - Start a new simulation
- `WS /ws` - WebSocket for real-time updates

### Frontend (HTML/JavaScript)

Open the HTML files in a web browser:

1. **Setup Page**: Open `_site/index.html` in your browser
   - Fill in the form to configure your simulation
   - Click "Start Simulation"

2. **Live Map**: After starting simulation, you'll be redirected to `_site/simulate.html`
   - This page connects to the WebSocket and displays real-time updates

**Note**: If you're opening HTML files directly (file://), you may need to run a local web server:

```bash
# Using Python's built-in server
cd _site
python -m http.server 8080

# Then open in browser: http://localhost:8080/index.html
```

### Streamlit Dashboard (Alternative Frontend)

If you prefer the Streamlit interface:

```bash
streamlit run app.py
```

This will open at `http://localhost:8501`

## Quick Start Example

1. **Terminal 1 - Start Backend:**
   ```bash
   uvicorn server:app --reload --port 8000
   ```

2. **Terminal 2 - Start Frontend Server (optional, for HTML files):**
   ```bash
   cd _site
   python -m http.server 8080
   ```

3. **Open Browser:**
   - Go to `http://localhost:8080/index.html` (or open `_site/index.html` directly)
   - Fill out the form:
     - Number of trucks: 4
     - Origin: Basra Port
     - Destination: Baghdad Depot
     - Departure time: (any datetime)
   - Click "Start Simulation"
   - You'll be redirected to the live map showing trucks moving in real-time

## Troubleshooting

### DynamoDB Connection Issues
- Verify AWS credentials are set correctly
- Check that the `Shipments` table exists in `eu-north-1` region
- Ensure your AWS user/role has DynamoDB read/write permissions

### Port Already in Use
If port 8000 is already in use, change it:
```bash
uvicorn server:app --port 8001
```
Then update the frontend JavaScript to use `http://localhost:8001` instead.

### WebSocket Connection Failed
- Make sure the backend server is running
- Check browser console for errors
- Verify CORS settings if accessing from a different origin

### Module Not Found Errors
Make sure all dependencies are installed:
```bash
pip install -r requirements.txt
```

## Production Deployment

For production, consider:
- Using environment variables for AWS credentials
- Setting up proper CORS origins instead of `["*"]`
- Using a production ASGI server like Gunicorn with uvicorn workers
- Setting up proper logging and monitoring

