"""WebSocket hub (RFC 6455): live seat counts / venue availability and per-event chat.

* /ws/live              public, read-only stream of capacity and venue updates
* /ws/events/{id}/chat  requires a valid session cookie; history replayed on (re)connect

Heartbeat: the server sends {"type":"ping"} every 20 s and drops sockets that
have not answered with {"type":"pong"} for 45 s. The browser client reconnects
with exponential backoff + jitter (static/js/live.js).
"""
import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import db
from .config import get_settings
from .security import COOKIE_NAME, user_from_token

router = APIRouter()
PING_EVERY, EVICT_AFTER = 20, 45


class Hub:
    def __init__(self) -> None:
        self.rooms: dict[str, set[WebSocket]] = {}
        self.last_seen: dict[WebSocket, float] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def join(self, room: str, ws: WebSocket) -> None:
        self.rooms.setdefault(room, set()).add(ws)
        self.last_seen[ws] = time.monotonic()

    def leave(self, room: str, ws: WebSocket) -> None:
        self.rooms.get(room, set()).discard(ws)
        self.last_seen.pop(ws, None)

    def count(self, room: str) -> int:
        return len(self.rooms.get(room, ()))

    async def broadcast(self, room: str, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, default=str)
        for ws in list(self.rooms.get(room, ())):
            try:
                await ws.send_text(text)
            except Exception:
                self.leave(room, ws)

    def publish(self, room: str, payload: dict[str, Any]) -> None:
        """Fire-and-forget from synchronous route handlers (they run in a worker thread)."""
        if self.loop is None or self.loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self.loop.create_task(self.broadcast(room, payload))
        else:
            asyncio.run_coroutine_threadsafe(self.broadcast(room, payload), self.loop)

    async def heartbeat(self) -> None:
        while True:
            await asyncio.sleep(PING_EVERY)
            now = time.monotonic()
            for room, sockets in list(self.rooms.items()):
                for ws in list(sockets):
                    if now - self.last_seen.get(ws, now) > EVICT_AFTER:
                        self.leave(room, ws)
                        try:
                            await ws.close(code=1001)
                        except Exception:
                            pass
                    else:
                        try:
                            await ws.send_text(json.dumps({"type": "ping", "ts": int(time.time())}))
                        except Exception:
                            self.leave(room, ws)


hub = Hub()


def publish_capacity(event_id: int) -> None:
    row = db.fetch_one("SELECT id, capacity, tickets_sold FROM events WHERE id = %s", (event_id,))
    if row:
        hub.publish("live", {"type": "capacity", "event_id": row["id"], "tickets_sold": row["tickets_sold"],
                             "seats_left": row["capacity"] - row["tickets_sold"]})


def publish_venue(venue_id: int, reason: str) -> None:
    hub.publish("live", {"type": "venue", "venue_id": venue_id, "reason": reason})


def _origin_ok(ws: WebSocket) -> bool:
    """Cross-Site WebSocket Hijacking defence: browsers always send Origin on a WS handshake."""
    origin = ws.headers.get("origin")
    if origin is None:
        return True                                             # non-browser client (tests, CLI)
    host = ws.headers.get("host", "")
    return origin in {get_settings().PUBLIC_ORIGIN.rstrip("/"), f"https://{host}", f"http://{host}"}


async def _pump(ws: WebSocket, room: str, on_message=None) -> None:
    try:
        while True:
            raw = await ws.receive_text()
            hub.last_seen[ws] = time.monotonic()
            if len(raw) > 2000:
                await ws.close(code=1009)
                return
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(data, dict) or data.get("type") == "pong":
                continue
            if on_message:
                await on_message(data)
    except WebSocketDisconnect:
        pass
    finally:
        hub.leave(room, ws)


@router.websocket("/ws/live")
async def live(ws: WebSocket):
    if not _origin_ok(ws):
        await ws.close(code=1008)
        return
    await ws.accept()
    hub.join("live", ws)
    await ws.send_json({"type": "hello", "listeners": hub.count("live")})
    await _pump(ws, "live")


@router.websocket("/ws/events/{event_id}/chat")
async def chat(ws: WebSocket, event_id: int):
    user = await asyncio.to_thread(user_from_token, ws.cookies.get(COOKIE_NAME))
    event = await asyncio.to_thread(
        db.fetch_one, "SELECT id, status FROM events WHERE id = %s", (event_id,))
    if not _origin_ok(ws) or user is None or event is None or event["status"] != "published":
        await ws.close(code=1008)                               # policy violation: refuse before accept()
        return

    await ws.accept()
    room = f"chat:{event_id}"
    hub.join(room, ws)
    history = await asyncio.to_thread(db.fetch_all, """
        SELECT * FROM (
            SELECT m.id, m.body, m.created_at, u.full_name AS sender
            FROM chat_messages m JOIN users u ON u.id = m.user_id
            WHERE m.event_id = %s ORDER BY m.id DESC LIMIT 30) h
        ORDER BY id""", (event_id,))
    await ws.send_text(json.dumps({"type": "history", "messages": history}, default=str))

    recent: list[float] = []

    async def on_message(data: dict) -> None:
        body = str(data.get("message", "")).strip()
        if not body or len(body) > 300:
            await ws.send_json({"type": "error", "detail": "Messages must be 1-300 characters."})
            return
        now = time.monotonic()
        recent[:] = [t for t in recent if now - t < 10]
        if len(recent) >= 5:
            await ws.send_json({"type": "error", "detail": "Slow down: at most 5 messages per 10 seconds."})
            return
        recent.append(now)
        saved = await asyncio.to_thread(db.fetch_one, """
            INSERT INTO chat_messages (event_id, user_id, body) VALUES (%s, %s, %s)
            RETURNING id, body, created_at""", (event_id, user["id"], body))
        # Stored as plain text; the client renders it with textContent (context-aware output encoding).
        await hub.broadcast(room, {"type": "chat", "sender": user["full_name"], **saved})

    await _pump(ws, room, on_message)
