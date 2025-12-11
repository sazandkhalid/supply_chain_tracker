# ml/train_delay_model.py

import numpy as np
from sklearn.linear_model import LogisticRegression
import joblib
import os

np.random.seed(123)

N = 5000

# Features
speeds = np.random.uniform(20, 90, N)          # km/h
distances = np.random.uniform(5, 600, N)       # km remaining
stops = np.random.randint(0, 6, N)             # number of stops so far

# Simple synthetic "delay" rule:
# Delayed if slow & far & many stops
labels = (
    ((speeds < 45) & (distances > 250)) |
    (stops >= 3)
).astype(int)

X = np.column_stack([speeds, distances, stops])
y = labels

model = LogisticRegression()
model.fit(X, y)

os.makedirs("models", exist_ok=True)
joblib.dump(model, "models/delay_model.pkl")

print("Saved delay model to models/delay_model.pkl")
