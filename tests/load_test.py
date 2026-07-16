"""Locust load test for InvoSync backend.

Run against a live backend:

    pip install locust
    locust -f tests/load_test.py --host https://invosync-backend-yjfa.onrender.com \
           --users 1000 --spawn-rate 50 --run-time 5m --headless -u 1000 -r 50

What it exercises (the realistic CA-firm traffic mix):
  - GET  /health                         (keepalive / monitoring)
  - GET  /api/v3/admin/metrics/live      (dashboard polling)
  - GET  /metrics                         (Prometheus scrape)
  - GET  /api/v3/admin/errors            (error feed)
  - POST /extract                         (document ingestion — tight rate limit)

No auth is sent (demo mode). Adjust the host and add auth headers if you
enable real authentication.
"""

from locust import HttpUser, task, between


class InvoSyncUser(HttpUser):
    wait_time = between(1, 4)

    @task(10)
    def health(self):
        self.client.get("/health", name="GET /health")

    @task(5)
    def metrics_live(self):
        self.client.get("/api/v3/admin/metrics/live", name="GET /metrics/live")

    @task(3)
    def prometheus(self):
        self.client.get("/metrics", name="GET /metrics")

    @task(2)
    def errors(self):
        self.client.get("/api/v3/admin/errors", name="GET /admin/errors")

    @task(1)
    def extract(self):
        # Extraction is rate-limited to 15/min/IP — keep this light.
        # Send a tiny 1x1 PNG so the endpoint accepts the upload shape.
        self.client.post(
            "/extract",
            files={"file": ("blank.png", b"\x89PNG\r\n\x1a\n", "image/png")},
            name="POST /extract",
        )
