"""Lab 8: WebSocket live updates, authenticated chat, Origin checks."""
import pytest
from starlette.websockets import WebSocketDisconnect

from app import db

from .conftest import client_for, published_event


def _recv_until(ws, kind, limit=10):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"no {kind} message")


def test_live_channel_broadcasts_seat_changes(app, as_, users, venue):
    ev = published_event(users["org"]["id"], venue["id"], capacity=10)
    watcher = client_for(app)
    with watcher.websocket_connect("/ws/live") as ws:
        assert ws.receive_json()["type"] == "hello"
        assert as_("student").post(f"/api/v1/events/{ev['id']}/register").status_code == 201
        msg = _recv_until(ws, "capacity")
        assert msg == {"type": "capacity", "event_id": ev["id"], "tickets_sold": 1, "seats_left": 9}


def test_chat_rejects_unauthenticated_handshake(app, users, venue):
    ev = published_event(users["org"]["id"], venue["id"])
    with pytest.raises(WebSocketDisconnect) as exc:
        with client_for(app).websocket_connect(f"/ws/events/{ev['id']}/chat") as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_chat_rejects_foreign_origin(app, users, venue):
    ev = published_event(users["org"]["id"], venue["id"])
    c = client_for(app, "student@mu.ac.zm")
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/ws/events/{ev['id']}/chat",
                                 headers={"cookie": f"sid={c.cookies['sid']}", "origin": "https://evil.example"}) as ws:
            ws.receive_json()


def test_chat_broadcasts_persists_and_replays(app, users, venue):
    ev = published_event(users["org"]["id"], venue["id"])
    a, b = client_for(app, "student@mu.ac.zm"), client_for(app, "student2@mu.ac.zm")
    url = f"/ws/events/{ev['id']}/chat"
    with a.websocket_connect(url, headers={"cookie": f"sid={a.cookies['sid']}"}) as wa, \
         b.websocket_connect(url, headers={"cookie": f"sid={b.cookies['sid']}"}) as wb:
        assert wa.receive_json() == {"type": "history", "messages": []}
        wb.receive_json()
        wa.send_json({"message": "<b>Gate A</b> is open"})
        got = _recv_until(wb, "chat")
        assert got["sender"] == users["student"]["full_name"] and got["body"] == "<b>Gate A</b> is open"
        wa.send_json({"message": "x" * 301})
        assert _recv_until(wa, "error")["detail"].startswith("Messages must be")
    assert db.fetch_one("SELECT COUNT(*) AS n FROM chat_messages")["n"] == 1
    with a.websocket_connect(url, headers={"cookie": f"sid={a.cookies['sid']}"}) as again:
        assert [m["body"] for m in again.receive_json()["messages"]] == ["<b>Gate A</b> is open"]


def test_chat_flood_control(app, users, venue):
    ev = published_event(users["org"]["id"], venue["id"])
    a = client_for(app, "student@mu.ac.zm")
    with a.websocket_connect(f"/ws/events/{ev['id']}/chat", headers={"cookie": f"sid={a.cookies['sid']}"}) as ws:
        ws.receive_json()
        for i in range(6):
            ws.send_json({"message": f"spam {i}"})
        kinds = [ws.receive_json()["type"] for _ in range(6)]
    assert kinds.count("chat") == 5 and kinds.count("error") == 1
