FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements-deploy.txt .
RUN pip install --no-cache-dir -r requirements-deploy.txt

# Copy application code
COPY server.py main_unified.py ./
COPY backend/ backend/
COPY models/ models/

# Railway sets PORT dynamically
ENV PORT=8080
EXPOSE ${PORT}

CMD uvicorn main_unified:app --host 0.0.0.0 --port ${PORT}
