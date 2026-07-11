"""Test extraction with real image - full error output."""
import requests

r = requests.get(
    "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/invoice.png",
    timeout=10,
)
img_bytes = r.content
print(f"Downloaded {len(img_bytes)} bytes")

resp = requests.post(
    "http://localhost:8000/extract",
    files={"file": ("invoice.png", img_bytes, "image/png")},
    timeout=120,
)
print(f"Status: {resp.status_code}")
d = resp.json()
if resp.status_code == 200:
    print(f"Provider: {d.get('_provider')}, Conf: {d.get('confidence')}")
else:
    detail = d.get("detail", "")
    print(detail)
