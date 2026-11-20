import asyncio
import hashlib
import hmac
import io
import json
import os
import random
import time
from contextlib import asynccontextmanager
from typing import Dict, Set

import bleach
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class Settings(BaseSettings):
    DATABASE_URL: str
    SESSION_SECRET: str = Field(min_length=16)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
pool = ConnectionPool(conninfo=settings.DATABASE_URL, min_size=2, max_size=10, open=False)


def generate_webp_hero() -> bytes:
    img = Image.new("RGB", (1200, 500), color=(13, 43, 94))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 1160, 460], outline=(251, 191, 36), width=6)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=80)
    return buf.getvalue()


def generate_png_hero() -> bytes:
    # Intentionally large uncompressed PNG for Lab 9 Baseline vs Optimized comparison
    img = Image.new("RGB", (1800, 800), color=(13, 43, 94))
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=0)
    return buf.getvalue()


WEBP_HERO_BYTES = generate_webp_hero()
PNG_HERO_BYTES = generate_png_hero()


def sign_session(username: str) -> str:
    sig = hmac.new(settings.SESSION_SECRET.encode(), username.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{username}.{sig}"


def verify_session(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    username, sig = token.rsplit(".", 1)
    expected = hmac.new(settings.SESSION_SECRET.encode(), username.encode(), hashlib.sha256).hexdigest()[:24]
    return username if hmac.compare_digest(sig, expected) else None


class ChatFrame(BaseModel):
    message: str = Field(min_length=1, max_length=300)


class RoomConnectionManager:
    def __init__(self):
        self.rooms: Dict[int, Set[WebSocket]] = {}
        self.last_pong: Dict[WebSocket, float] = {}

    async def connect(self, ws: WebSocket, event_id: int):
        await ws.accept()
        self.rooms.setdefault(event_id, set()).add(ws)
        self.last_pong[ws] = time.monotonic()

    def disconnect(self, ws: WebSocket, event_id: int):
        if event_id in self.rooms:
            self.rooms[event_id].discard(ws)
        self.last_pong.pop(ws, None)

    async def broadcast(self, event_id: int, payload: dict):
        dead = []
        for ws in list(self.rooms.get(event_id, set())):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, event_id)


manager = RoomConnectionManager()


async def heartbeat_watchdog():
    """Lab 8 Task 3: Server-side Ping/Pong (0x9/0xA) monitoring & stale socket eviction."""
    while True:
        await asyncio.sleep(10)
        now = time.monotonic()
        for event_id, sockets in list(manager.rooms.items()):
            for ws in list(sockets):
                # Evict if no Pong received within 25s
                if now - manager.last_pong.get(ws, now) > 25:
                    print(f"[HEARTBEAT] Evicting stale socket in room {event_id}")
                    try:
                        await ws.close(code=1001)
                    except Exception:
                        pass
                    manager.disconnect(ws, event_id)
                else:
                    try:
                        await ws.send_json({"type": "ping", "ts": int(now)})
                    except Exception:
                        manager.disconnect(ws, event_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ws_messages (
                    id SERIAL PRIMARY KEY,
                    event_id INTEGER NOT NULL,
                    sender VARCHAR(60) NOT NULL,
                    body TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
        conn.commit()
    task = asyncio.create_task(heartbeat_watchdog())
    yield
    task.cancel()
    pool.close()


app = FastAPI(title="ICT461 Labs 8 & 9 Real-Time & Web Vitals App", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=400)


# --- AUTH ENDPOINT (Sets HttpOnly Cookie for WebSocket Handshake) ---
@app.post("/api/v1/login")
def login(username: str = "derrick"):
    token = sign_session(username)
    resp = JSONResponse({"status": "authenticated", "user": username})
    resp.set_cookie("session_token", token, httponly=True, samesite="lax", path="/")
    return resp


# --- LAB 8: AUTHENTICATED WEBSOCKET ENDPOINT ---
@app.websocket("/ws/events/{event_id}")
async def event_ws(websocket: WebSocket, event_id: int):
    # Support HttpOnly cookie (browser) or query token fallback (CLI test)
    raw_token = websocket.cookies.get("session_token") or websocket.query_params.get("token")
    user = verify_session(raw_token)
    if not user:
        # Reject unauthenticated HTTP Upgrade handshake before accept()
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, event_id)

    # Replay last 15 persisted messages from PostgreSQL on connect/reconnect
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, sender, body, to_char(created_at, 'HH24:MI:SS') AS time "
                "FROM ws_messages WHERE event_id = %s ORDER BY id DESC LIMIT 15;",
                (event_id,),
            )
            history = list(reversed(cur.fetchall()))
    await websocket.send_json({"type": "history", "messages": history})

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "pong":
                manager.last_pong[websocket] = time.monotonic()
                continue

            frame = ChatFrame.model_validate(data)
            clean_msg = bleach.clean(frame.message, tags=[], strip=True)

            with pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "INSERT INTO ws_messages (event_id, sender, body) "
                        "VALUES (%s, %s, %s) RETURNING id, sender, body, to_char(created_at, 'HH24:MI:SS') AS time;",
                        (event_id, user, clean_msg),
                    )
                    saved = cur.fetchone()
                conn.commit()

            await manager.broadcast(event_id, {"type": "chat", **saved})
    except WebSocketDisconnect:
        manager.disconnect(websocket, event_id)


# --- LAB 9: DIFFERENTIATED HTTP CACHE-CONTROL, ETAG (304) & STATIC ASSETS ---
JS_BUNDLE = """
let attempt = 0;
let ws = null;
function setStatus(txt, color) {
  const el = document.getElementById('ws-status');
  if (el) { el.textContent = txt; el.style.background = color; }
}
function appendMsg(m) {
  const box = document.getElementById('feed');
  if (!box) return;
  const p = document.createElement('div');
  p.textContent = `[${m.time || 'LIVE'}] ${m.sender}: ${m.body}`;
  box.appendChild(p);
}
async function initRealtime() {
  const user = new URLSearchParams(location.search).get('user') || 'Derrick';
  await fetch(`/api/v1/login?username=${encodeURIComponent(user)}`, { method: 'POST' });
  connectWS();
}
function connectWS() {
  setStatus('Reconnecting...', '#d97706');
  ws = new WebSocket(`ws://${location.host}/ws/events/1`);
  ws.onopen = () => { attempt = 0; setStatus('Connected (WS 101)', '#16a34a'); };
  ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.type === 'ping') { ws.send(JSON.stringify({ type: 'pong' })); return; }
    if (data.type === 'history') { document.getElementById('feed').innerHTML = ''; data.messages.forEach(appendMsg); }
    if (data.type === 'chat') appendMsg(data);
  };
  ws.onclose = () => {
    setStatus('Offline — Exponential Backoff', '#dc2626');
    const exp = Math.min(30000, 1000 * Math.pow(2, attempt));
    const jitter = Math.floor(Math.random() * 400);
    const delay = exp + jitter;
    console.warn(`[WS] Closed. Reconnecting attempt #${attempt + 1} in ${delay}ms`);
    attempt++;
    setTimeout(connectWS, delay);
  };
}
function sendChat() {
  const inp = document.getElementById('msg-input');
  if (ws && ws.readyState === WebSocket.OPEN && inp.value.trim()) {
    ws.send(JSON.stringify({ message: inp.value }));
    inp.value = '';
  }
}
window.addEventListener('DOMContentLoaded', initRealtime);
""".strip().encode()


@app.get("/static/app.v1.min.js")
def static_js():
    return Response(
        content=JS_BUNDLE,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/static/hero-campus.webp")
def static_webp():
    return Response(
        content=WEBP_HERO_BYTES,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=31536000, immutable", "Accept-Ranges": "bytes"},
    )


@app.get("/static/hero-unoptimized.png")
def static_png():
    return Response(content=PNG_HERO_BYTES, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/v1/catalog")
def catalog(request: Request):
    data = json.dumps([
        {"id": 1, "title": "ICT461 Web Engineering Summit", "seats": 42},
        {"id": 2, "title": "Mulungushi Tech Innovation Expo", "seats": 18},
    ]).encode()
    etag = f'"{hashlib.sha256(data).hexdigest()[:16]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "public, max-age=30, stale-while-revalidate=60"})
    return Response(
        content=data,
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "public, max-age=30, stale-while-revalidate=60"},
    )


# --- LAB 9: UNOPTIMIZED BASELINE VIEW (For Before Lighthouse Screenshot) ---
@app.get("/baseline", response_class=HTMLResponse)
def baseline_page():
    return """<!doctype html>
<html lang="en">
<head><title>Baseline Unoptimized View</title></head>
<body>
  <h1>Campus Events Hub (Baseline)</h1>
  <!-- Missing width/height causes CLS; huge PNG delays LCP -->
  <img src="/static/hero-unoptimized.png" alt="Hero">
  <script>
    // Synchronous main-thread blocking loop (>150ms) for baseline TBT/INP
    const end = Date.now() + 180; while (Date.now() < end) {}
  </script>
</body>
</html>"""


# --- LAB 8 & 9: OPTIMIZED & REAL-TIME VIEW ---
@app.get("/", response_class=HTMLResponse)
def optimized_page():
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Campus Events Hub — Real-Time & Optimized</title>
  <link rel="preload" as="image" href="/static/hero-campus.webp" type="image/webp" fetchpriority="high">
  <script src="/static/app.v1.min.js" defer></script>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 820px; margin: 24px auto; padding: 0 16px; color: #0f172a; }
    img { max-width: 100%; height: auto; border-radius: 8px; }
    #ws-status { display: inline-block; padding: 4px 10px; border-radius: 999px; color: #fff; font-size: 13px; font-weight: 600; }
    #feed { border: 1px solid #cbd5e1; border-radius: 8px; padding: 12px; height: 180px; overflow-y: auto; margin: 12px 0; background: #f8fafc; }
  </style>
</head>
<body>
  <header style="display:flex;justify-content:space-between;align-items:center;">
    <h1>Campus Events Hub</h1>
    <span id="ws-status" style="background:#64748b;">Initializing...</span>
  </header>
  <picture>
    <source srcset="/static/hero-campus.webp" type="image/webp">
    <img src="/static/hero-campus.webp" alt="Campus Events Banner" width="1200" height="500" fetchpriority="high">
  </picture>
  <h2>Live Event Room #1 (RFC 6455 WebSocket + PostgreSQL)</h2>
  <div id="feed"></div>
  <div style="display:flex;gap:8px;">
    <input id="msg-input" placeholder="Type live announcement..." style="flex:1;padding:8px;">
    <button onclick="sendChat()" style="padding:8px 16px;">Send Frame</button>
  </div>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)