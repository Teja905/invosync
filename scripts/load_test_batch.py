"""Load test for InvoSync batch endpoint.
Generates valid fake invoice images and fires them at the batch API.

Usage:
    python scripts/load_test_batch.py                          # 5 concurrent (default)
    python scripts/load_test_batch.py --concurrent 20          # spike test
    python scripts/load_test_batch.py --batch-size 3 --repeat 10  # 30 files total
    python scripts/load_test_batch.py --url http://localhost:8000 --client-id 1
"""
import argparse, asyncio, io, json, os, sys, time, uuid
from pathlib import Path

try:
    import aiohttp
except ImportError:
    print("Install aiohttp: pip install aiohttp")
    sys.exit(1)

BASE_URL = os.getenv("API_URL", "http://localhost:8000")
CLIENT_ID = int(os.getenv("CLIENT_ID", "1"))


def _make_dummy_jpeg(width: int = 800, height: int = 600) -> bytes:
    """Build a valid minimal JPEG with solid gray fill."""
    import struct
    def _seg(marker: int, payload: bytes = b"") -> bytes:
        return struct.pack(">H", marker) + struct.pack(">H", len(payload) + 2) + payload

    hdr = b"\xff\xd8"
    app0 = _seg(0xFFE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    dqt = _seg(0xFFDB, bytes([0] + [50] * 64))  # 50% quality table
    sof = _seg(0xFFC0, struct.pack(">BHHB", 8, height, width, 3) + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01")
    dht_y = _seg(0xFFC4, bytes([0x00]) + bytes(range(16)))
    sos = _seg(0xFFDA, b"\x01\x01\x00\x00?\x00")
    # minimal entropy-coded scan (gray fill)
    ecs = b"\xfe" * 64
    return hdr + app0 + dqt + sof + dht_y + sos + ecs + b"\xff\xd9"


def _make_dummy_pdf() -> bytes:
    """Build a minimal valid PDF with one blank page."""
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
    )
    return body


async def _send_batch(
    session: aiohttp.ClientSession,
    files: list[tuple[str, bytes]],
    batch_id: int,
    url: str,
    client_id: int,
) -> dict:
    start = time.monotonic()
    data = aiohttp.FormData()
    for fname, fbytes in files:
        data.add_field("files", fbytes, filename=fname, content_type="image/jpeg")
    data.add_field("client_id", str(client_id))
    try:
        async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            elapsed = time.monotonic() - start
            body = await resp.json()
            return {"batch_id": batch_id, "status": resp.status, "elapsed_s": round(elapsed, 2), **body}
    except Exception as e:
        return {"batch_id": batch_id, "status": 0, "elapsed_s": round(time.monotonic() - start, 2), "error": str(e)}


async def main(args: argparse.Namespace):
    url = f"{args.url}/api/v3/batch/extract?client_id={args.client_id}"
    total_files = args.batch_size * args.repeat
    print(f"Target: {url}")
    print(f"Batch: {args.batch_size} files x {args.repeat} rounds = {total_files} total")
    print(f"Concurrent batches: {args.concurrent}")
    print()

    batches = []
    for rep in range(args.repeat):
        files = []
        for i in range(args.batch_size):
            if i % 3 == 0:
                fbytes = _make_dummy_jpeg()
            elif i % 3 == 1:
                fbytes = _make_dummy_jpeg(1600, 1200)
            else:
                fbytes = _make_dummy_pdf()
            files.append((f"inv_{rep}_{i}.jpg", fbytes))
        batches.append(files)

    connector = aiohttp.TCPConnector(limit=args.concurrent, limit_per_host=args.concurrent)
    async with aiohttp.ClientSession(connector=connector) as session:
        sem = asyncio.Semaphore(args.concurrent)

        async def _run(batch_id: int, files: list) -> dict:
            async with sem:
                return await _send_batch(session, files, batch_id, url, args.client_id)

        tasks = [_run(i, b) for i, b in enumerate(batches)]
        t0 = time.monotonic()
        results = await asyncio.gather(*tasks)
        wall = time.monotonic() - t0

    print(f"{'BATCH':<6} {'STATUS':<7} {'FILES':<7} {'OK':<6} {'ERR':<6} {'TIME':<8}")
    print("-" * 50)
    ok_total = 0
    err_total = 0
    slowest = 0.0
    for r in results:
        ok = r.get("processed", 0)
        err = r.get("errors", 0)
        elapsed = r.get("elapsed_s", 0)
        ok_total += ok
        err_total += err
        slowest = max(slowest, elapsed)
        print(f"{r['batch_id']:<6} {r['status']:<7} {ok + err:<7} {ok:<6} {err:<6} {elapsed:<8}")

    print()
    print(f"Wall clock:  {wall:.2f}s")
    print(f"Files/sec:   {total_files / wall:.1f}")
    print(f"Slowest:     {slowest:.2f}s")
    print(f"Total OK:    {ok_total}")
    print(f"Total err:   {err_total}")
    print(f"Status:      {'PASS' if err_total == 0 else 'SOME FAILURES'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=BASE_URL)
    parser.add_argument("--client-id", type=int, default=CLIENT_ID)
    parser.add_argument("--batch-size", type=int, default=5, help="Files per batch call (max 50)")
    parser.add_argument("--repeat", type=int, default=4, help="How many batch calls to make")
    parser.add_argument("--concurrent", type=int, default=3, help="Max concurrent batch calls")
    args = parser.parse_args()
    asyncio.run(main(args))
