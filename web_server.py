#!/usr/bin/env python3
"""
one_web_server.py — Serveur web One Pool (WA Conception)
=========================================================
Pont ZMQ → HTTP + Server-Sent Events (SSE). Lecture seule.

Usage :
    python one_web_server.py --daemon-host 192.168.0.16
    python one_web_server.py --daemon-host 192.168.0.16 --http-port 8081

Variables d'environnement (alternative aux arguments CLI) :
    ONE_HOST          IP du Raspberry Pi exécutant one_daemon.py
    ONE_PUB_PORT      Port ZMQ PUB du daemon (défaut : 5560)
    ONE_WEB_PORT      Port HTTP du serveur web (défaut : 8081)
    ONE_LOG_LEVEL     DEBUG | INFO | WARNING (défaut : INFO)

Routes :
    GET /             → dashboard HTML
    GET /api/state    → snapshot JSON de l'état courant
    GET /api/stream   → SSE (text/event-stream) — mises à jour live

Compatible Python 3.9+, sans Qt. Dépendances : flask, pyzmq.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator

import zmq
from flask import Flask, Response, jsonify, render_template, stream_with_context

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# État partagé (mis à jour par le thread ZMQ, lu par Flask)
# ---------------------------------------------------------------------------
_state_lock = threading.Lock()
_state: Dict[str, Any] = {
    "connection": {
        "connected": False,
        "address": None,
        "last_seen": None,
    },
    "pump": {
        "mode":        None,   # 0=Manuel 1=Horloge 2=Auto
        "mode_label":  "—",
        "state":       None,   # 0=arrêté 1=en marche
        "state_label": "—",
    },
    "light": {
        "mode":        None,
        "mode_label":  "—",
        "state":       None,   # 0=éteint 1=allumé
        "state_label": "—",
        "type":        None,
    },
}

# File d'attente SSE : chaque client SSE a sa propre queue
_sse_clients: list[queue.Queue] = []
_sse_lock = threading.Lock()

# Libellés
_PUMP_MODES  = {0: "Manuel", 1: "Horloge", 2: "Auto"}
_LIGHT_MODES = {0: "Manuel", 1: "Horloge", 2: "Auto"}


def _state_snapshot() -> dict:
    with _state_lock:
        import copy
        return copy.deepcopy(_state)


def _broadcast(event_type: str, data: dict) -> None:
    """Envoie un événement SSE à tous les clients connectés."""
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)


# ---------------------------------------------------------------------------
# Thread ZMQ — subscribe aux topics one/
# ---------------------------------------------------------------------------

class ZmqSubscriberThread(threading.Thread):

    def __init__(self, host: str, pub_port: int):
        super().__init__(daemon=True, name="zmq-sub")
        self.host     = host
        self.pub_port = pub_port

    def run(self) -> None:
        ctx  = zmq.Context()
        sock = ctx.socket(zmq.SUB)
        addr = f"tcp://{self.host}:{self.pub_port}"
        sock.connect(addr)
        sock.setsockopt_string(zmq.SUBSCRIBE, "one/")
        sock.setsockopt(zmq.RCVTIMEO, 2000)  # 2 s timeout pour pouvoir relancer
        logger.info("ZMQ SUB connecté à %s", addr)

        while True:
            try:
                # Le daemon publie en send_multipart([topic_bytes, json_bytes])
                frames = sock.recv_multipart()
            except zmq.Again:
                continue
            except zmq.ZMQError as exc:
                logger.error("ZMQ error: %s", exc)
                time.sleep(2)
                continue

            if len(frames) < 2:
                continue
            topic = frames[0].decode()
            try:
                payload = json.loads(frames[1].decode())
            except json.JSONDecodeError:
                logger.warning("JSON invalide sur topic %s", topic)
                continue

            self._handle(topic, payload)

    def _handle(self, topic: str, payload: dict) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with _state_lock:
            if topic == "one/connection":
                _state["connection"]["connected"] = payload.get("connected", False)
                _state["connection"]["address"]   = payload.get("address")
                _state["connection"]["last_seen"]  = now
                _broadcast("connection", _state["connection"])

            elif topic == "one/status":
                # Mise à jour complète pompe + éclairage depuis le snapshot
                pm = payload.get("filtration_mode")
                ps = payload.get("filtration_state")
                lm = payload.get("eclairage_mode")
                ls = payload.get("eclairage_state")
                lt = payload.get("eclairage_type")
                _state["pump"]["mode"]        = pm
                _state["pump"]["mode_label"]  = _PUMP_MODES.get(pm, "—") if pm is not None else "—"
                _state["pump"]["state"]       = ps
                _state["pump"]["state_label"] = "En marche" if ps else "Arrêtée"
                _state["light"]["mode"]       = lm
                _state["light"]["mode_label"] = _LIGHT_MODES.get(lm, "—") if lm is not None else "—"
                _state["light"]["state"]      = ls
                _state["light"]["state_label"]= "Allumé" if ls else "Éteint"
                _state["light"]["type"]       = lt
                _state["connection"]["last_seen"] = now
                _broadcast("status", {
                    "pump":  _state["pump"],
                    "light": _state["light"],
                    "ts":    now,
                })

            elif topic == "one/pump/mode":
                pm = payload.get("value")
                _state["pump"]["mode"]       = pm
                _state["pump"]["mode_label"] = _PUMP_MODES.get(pm, "—") if pm is not None else "—"
                _broadcast("pump_mode", _state["pump"])

            elif topic == "one/pump/state":
                ps = payload.get("value")
                _state["pump"]["state"]       = ps
                _state["pump"]["state_label"] = "En marche" if ps else "Arrêtée"
                _broadcast("pump_state", _state["pump"])

            elif topic == "one/light/mode":
                lm = payload.get("value")
                _state["light"]["mode"]       = lm
                _state["light"]["mode_label"] = _LIGHT_MODES.get(lm, "—") if lm is not None else "—"
                _broadcast("light_mode", _state["light"])

            elif topic == "one/light/state":
                ls = payload.get("value")
                _state["light"]["state"]       = ls
                _state["light"]["state_label"] = "Allumé" if ls else "Éteint"
                _broadcast("light_state", _state["light"])


# ---------------------------------------------------------------------------
# Application Flask
# ---------------------------------------------------------------------------

app = Flask(
    __name__,
    template_folder=str(_HERE / "one" / "web" / "templates"),
    static_folder=None,
)
app.config["JSON_SORT_KEYS"] = False


@app.route("/")
def index():
    return render_template("one_index.html")


@app.route("/api/state")
def api_state():
    return jsonify(_state_snapshot())


@app.route("/api/stream")
def api_stream():
    """Server-Sent Events — mises à jour live pour le dashboard."""
    q: queue.Queue = queue.Queue(maxsize=50)
    with _sse_lock:
        _sse_clients.append(q)

    def _generate() -> Iterator[str]:
        # Envoie le snapshot initial
        snap = _state_snapshot()
        yield f"event: init\ndata: {json.dumps(snap)}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=20)
                    yield msg
                except queue.Empty:
                    # keepalive
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                if q in _sse_clients:
                    _sse_clients.remove(q)

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="One Web Server — tableau de bord lecture seule")
    p.add_argument("--daemon-host", default=os.environ.get("ONE_HOST", "127.0.0.1"),
                   help="IP du Raspberry Pi exécutant one_daemon.py (défaut : 127.0.0.1)")
    p.add_argument("--pub-port", type=int,
                   default=int(os.environ.get("ONE_PUB_PORT", 5560)),
                   help="Port ZMQ PUB du daemon (défaut : 5560)")
    p.add_argument("--http-port", type=int,
                   default=int(os.environ.get("ONE_WEB_PORT", 8081)),
                   help="Port HTTP du serveur web (défaut : 8081)")
    p.add_argument("--log-level",
                   default=os.environ.get("ONE_LOG_LEVEL", "INFO"),
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    # Démarrage du thread subscriber ZMQ
    sub = ZmqSubscriberThread(host=args.daemon_host, pub_port=args.pub_port)
    sub.start()
    logger.info("ZMQ subscriber démarré → %s:%d", args.daemon_host, args.pub_port)

    # Démarrage Flask (threaded pour SSE)
    logger.info("Serveur web → http://0.0.0.0:%d", args.http_port)
    app.run(
        host="0.0.0.0",
        port=args.http_port,
        threaded=True,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
