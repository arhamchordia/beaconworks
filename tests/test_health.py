import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server import app

with app.test_client() as client:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}

print("test_health.py: OK")
