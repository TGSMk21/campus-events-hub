import asyncio
import json
import httpx
import websockets
from app import sign_session

BASE = "http://127.0.0.1:8000"
WS_BASE = "ws://127.0.0.1:8000"


async def main():
    print("=" * 60)
    print("LAB 8: WEBSOCKET HANDSHAKE AUTH, PERSISTENCE & PING/PONG")
    print("=" * 60)

    # 1. Unauthenticated handshake rejection test
    try:
        async with websockets.connect(f"{WS_BASE}/ws/events/1") as ws:
            await ws.recv()
    except Exception as e:
        print(f"[1] Unauthenticated WS Handshake Rejected: {type(e).__name__} ({e})")

    # 2. Authenticated handshake + live broadcast + PostgreSQL persistence
    token_alice = sign_session("Alice")
    token_bob = sign_session("Bob")
    async with websockets.connect(f"{WS_BASE}/ws/events/1?token={token_alice}") as ws_a, \
               websockets.connect(f"{WS_BASE}/ws/events/1?token={token_bob}") as ws_b:
        hist_a = json.loads(await ws_a.recv())
        hist_b = json.loads(await ws_b.recv())
        print(f"[2] Authenticated Handshake OK | Replayed History Count: {len(hist_a['messages'])}")

        await ws_a.send(json.dumps({"message": "Gate A is now open for badge scanning!"}))
        msg_a = json.loads(await ws_a.recv())
        msg_b = json.loads(await ws_b.recv())
        print(f"[3] Broadcast Received by Bob -> Sender: {msg_b['sender']}, Body: '{msg_b['body']}'")

    print("\n" + "=" * 60)
    print("LAB 9: HTTP CACHE-CONTROL, ETAG (304) & GZIP COMPRESSION")
    print("=" * 60)

    r_js = httpx.get(f"{BASE}/static/app.v1.min.js")
    print(f"[1] Static Asset Cache-Control: {r_js.headers.get('cache-control')}")

    r_cat1 = httpx.get(f"{BASE}/api/v1/catalog", headers={"Accept-Encoding": "gzip"})
    etag = r_cat1.headers.get("etag")
    print(f"[2] Catalog Initial -> Status: {r_cat1.status_code}, Content-Encoding: {r_cat1.headers.get('content-encoding')}, ETag: {etag}")

    r_cat2 = httpx.get(f"{BASE}/api/v1/catalog", headers={"If-None-Match": etag})
    print(f"[3] Catalog Conditional Request (If-None-Match) -> Status: {r_cat2.status_code} Not Modified")


if __name__ == "__main__":
    asyncio.run(main())