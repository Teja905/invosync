"""Full end-to-end test through FastAPI."""
import struct, zlib, requests, json

def make_test_png():
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    ihdr = struct.pack('>IIBBBBB', 4, 4, 8, 2, 0, 0, 0)
    raw_data = b''
    for y in range(4):
        raw_data += b'\x00'  # filter byte
        for x in range(4):
            raw_data += b'\xff\x00\x00' if (x + y) % 2 == 0 else b'\x00\x00\xff'
    raw = zlib.compress(raw_data)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', raw) + chunk(b'IEND', b'')

test_png = make_test_png()
print(f"Test PNG: {len(test_png)} bytes, header: {test_png[:8]}")

# Also check if PIL can open it
try:
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(test_png))
    print(f"PIL: {img.size}, {img.mode}")
except ImportError:
    print("PIL not available")

# Test through API
resp = requests.post(
    "http://localhost:8000/extract",
    files={"file": ("invoice.png", test_png, "image/png")},
    timeout=120,
)
print(f"\nAPI Status: {resp.status_code}")
d = resp.json()
if resp.status_code == 200:
    print(f"Provider: {d.get('_provider')}, Model: {d.get('_model')}")
    print(f"Confidence: {d.get('confidence')}")
    print(f"Keys: {list(d.keys())}")
    print(f"Vendor: {d.get('vendor_name')}")
    print(f"Inv#: {d.get('invoice_number')}")
    print(f"Amount: {d.get('total_amount')}")
else:
    detail = d.get("detail", "")
    print(detail[:1000])
