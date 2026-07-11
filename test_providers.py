"""Test providers individually."""
import base64
import json
import struct
import zlib
import requests


def make_png():
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    raw = zlib.compress(b'\x00\xff\x00\x00')
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', raw) + chunk(b'IEND', b'')


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
If GSTIN is not visible, set to empty string.
Return ONLY the JSON object."""

img = make_png()
b64 = base64.b64encode(img).decode()
data_url = f'data:image/png;base64,{b64}'

payload = {
    'model': 'meta-llama/llama-3.2-11b-vision-instruct',
    'messages': [{
        'role': 'user',
        'content': [
            {'type': 'text', 'text': EXTRACT_PROMPT},
            {'type': 'image_url', 'image_url': {'url': data_url}},
        ]
    }],
    'max_tokens': 4096,
    'temperature': 0.1,
}

# Test OpenRouter
print("=== OpenRouter ===")
resp = requests.post(
    'https://openrouter.ai/api/v1/chat/completions',
    headers={'Authorization': 'Bearer sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', 'Content-Type': 'application/json'},
    json=payload,
    timeout=60,
)
print(f'Status: {resp.status_code}')
body = resp.json()
if 'choices' in body and len(body['choices']) > 0:
    print('OK - has choices')
    content = body['choices'][0]['message']['content']
    print(f'Content preview: {content[:200]}')
else:
    print(f'No choices key. Body: {json.dumps(body, indent=2)[:1000]}')

# Test NVIDIA
print("\n=== NVIDIA ===")
resp2 = requests.post(
    'https://integrate.api.nvidia.com/v1/chat/completions',
    headers={'Authorization': 'Bearer nvapi-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', 'Content-Type': 'application/json'},
    json=payload,
    timeout=60,
)
print(f'Status: {resp2.status_code}')
if resp2.status_code != 200:
    print(f'Error: {resp2.text[:500]}')
else:
    body2 = resp2.json()
    if 'choices' in body2 and len(body2['choices']) > 0:
        print('OK - has choices')
        content2 = body2['choices'][0]['message']['content']
        print(f'Content preview: {content2[:200]}')
    else:
        print(f'No choices. Body: {json.dumps(body2, indent=2)[:1000]}')
