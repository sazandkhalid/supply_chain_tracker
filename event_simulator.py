import requests
import uuid
import random
import json
from datetime import datetime
import time

API_URL = "https://ug4px67fbj.execute-api.eu-north-1.amazonaws.com/deploy-API-supply"
NUM_BATCHES = 5
BATCH_SIZE = 200
DELAY_BETWEEN_BATCHES = 1  # seconds

def generate_event():
    return {
        "shipmentId": str(uuid.uuid4()),
        "location": {
            "lat": round(random.uniform(24.5, 25.5), 6),
            "lon": round(random.uniform(54.5, 55.5), 6)
        },
        "status": random.choice(["IN_TRANSIT", "DELIVERED", "LATE"]),
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

def send_batch(batch):
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(API_URL, json=batch, headers=headers)
        print(f"Status: {response.status_code}, Response: {response.text}")
    except Exception as e:
        print(f"Error sending batch: {e}")

if __name__ == "__main__":
    print(f"Sending {NUM_BATCHES} batches of {BATCH_SIZE} events to {API_URL}...\n")
    for i in range(NUM_BATCHES):
        batch = [generate_event() for _ in range(BATCH_SIZE)]
        print(f"Batch {i+1} generated with {len(batch)} events")
        send_batch(batch)
        time.sleep(DELAY_BETWEEN_BATCHES)

