"""Direct test of providers vs through FastAPI."""
import base64
import requests

# Get the test image
r = requests.get(
    "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/invoice.png",
    timeout=10,
)
img_bytes = r.content
b64 = base64.b64encode(img_bytes).decode()
data_url = f"data:image/png;base64,{b64}"

EXTRACT_PROMPT = """Extract invoice data from this image and return ONLY valid JSON.
Schema: {"gstin":"","invoice_number":"","date":"","total_amount":0,"vendor_name":"","line_items":[],"confidence":0}
Return ONLY the JSON object."""

# Direct test OpenRouter
print("=== Direct OpenRouter ===")
payload = {
    "model": "meta-llama/llama-3.2-11b-vision-instruct",
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": EXTRACT_PROMPT},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]}],
    "max_tokens": 100,
}
resp = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={
        "Authorization": "Bearer sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "Content-Type": "application/json",
    },
    json=payload,
    timeout=60,
)
print(f"Status: {resp.status_code}")
print(resp.text[:500])

# Direct test NVIDIA
print("\n=== Direct NVIDIA ===")
payload2 = {
    "model": "meta/llama-3.2-11b-vision-instruct",
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": EXTRACT_PROMPT},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]}],
    "max_tokens": 100,
}
resp2 = requests.post(
    "https://integrate.api.nvidia.com/v1/chat/completions",
    headers={
        "Authorization": "Bearer nvapi-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "Content-Type": "application/json",
    },
    json=payload2,
    timeout=60,
)
print(f"Status: {resp2.status_code}")
print(resp2.text[:500])


