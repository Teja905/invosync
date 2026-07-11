"""Test OpenRouter with short vs long prompts."""
import struct, zlib, requests, base64

def chunk(ctype, data):
    c = ctype + data
    return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
raw = zlib.compress(b'\x00\xff\x00\x00')
png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', raw) + chunk(b'IEND', b'')
b64 = base64.b64encode(png).decode()
data_url = f"data:image/png;base64,{b64}"

EXTRACT_PROMPT = """Extract invoice data from this image and return ONLY valid JSON (no markdown, no code fences).
Schema:
{
  "gstin": "vendor GSTIN or empty string if not found",
  "invoice_number": "invoice number",
  "date": "YYYY-MM-DD",
  "total_amount": number (total including tax),
  "vendor_name": "vendor/supplier name",
  "vendor_address": "vendor address or null",
  "line_items": [
    {
      "description": "item description",
      "quantity": number,
      "rate": number (unit rate),
      "taxable_value": number (value before tax for this item),
      "tax_rate": number (GST tax rate percentage, e.g. 18),
      "cgst": number or null,
      "sgst": number or null,
      "igst": number or null
    }
  ],
  "confidence": number between 0 and 1
}
If GSTIN is not visible on the invoice, set it to empty string.
If CGST/SGST/IGST is not applicable, set to null.
Return ONLY the JSON object."""

headers = {
    "Authorization": "Bearer sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "Content-Type": "application/json",
}

# Test 1: Short prompt
print("=== Short prompt ===")
resp = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers=headers,
    json={
        "model": "meta-llama/llama-3.2-11b-vision-instruct",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "what color is this image?"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
        "max_tokens": 20,
    },
    timeout=30,
)
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    body = resp.json()
    if "choices" in body and body["choices"]:
        print(f"OK: {body['choices'][0]['message']['content'][:100]}")
    else:
        print(f"No choices: {resp.text[:300]}")
else:
    print(f"Error: {resp.text[:300]}")

# Test 2: Full extraction prompt
print("\n=== Full EXTRACT_PROMPT ===")
resp2 = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers=headers,
    json={
        "model": "meta-llama/llama-3.2-11b-vision-instruct",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": EXTRACT_PROMPT},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
        "max_tokens": 500,
    },
    timeout=60,
)
print(f"Status: {resp2.status_code}")
if resp2.status_code == 200:
    body2 = resp2.json()
    if "choices" in body2 and body2["choices"]:
        print(f"OK: {body2['choices'][0]['message']['content'][:200]}")
    else:
        print(f"No choices: {resp2.text[:500]}")
else:
    print(f"Error: {resp2.text[:500]}")
