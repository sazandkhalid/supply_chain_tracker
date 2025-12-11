# ml/train_kmeans_speed.py
import numpy as np
from sklearn.cluster import KMeans
import joblib
import os

np.random.seed(42)

# Synthetic "speed" (km/h) and "distance remaining" (km)
# You can replace this later with real logs.
speeds = np.random.uniform(20, 90, 5000)          # 20–90 km/h
distances = np.random.uniform(5, 600, 5000)       # 5–600 km remaining

X = np.column_stack([speeds, distances])

# 3 clusters: fast, normal, slow/erratic etc.
kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
kmeans.fit(X)

os.makedirs("models", exist_ok=True)
joblib.dump(kmeans, "models/kmeans_speed_cluster.pkl")

print("Saved KMeans model to models/kmeans_speed_cluster.pkl")
