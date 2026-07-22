#!/usr/bin/env python3
"""
one_daemon.py — Démon BLE headless pour le module One (WA Conception)
======================================================================

Rôle : maintenir la connexion BLE avec un module One et publier l'état
(pompe + éclairage) sur des topics ZMQ/MQTT.

Similaire à ble_daemon.py (régulateur Corelec), mais spécifique au One.

Flux :
  BLE One ──notify──→ one_daemon ──ZMQ PUB──→ topics one/...

Topics publiés (JSON) :
  one/connection   → statut de connexion BLE
  one/status       → état pompe + éclairage (snapshot complet)
  one/pump/mode    → mode filtration (int)
  one/pump/state   → état marche/arrêt (int)
  one/light/mode   → mode éclairage (int)
  one/light/state  → état allumé/éteint (int)

Commandes acceptées (ZMQ PULL) :
  one/cmd/retry    → force une tentative de reconnexion
  one/cmd/pair     → déclenche un appairage (bouton module requis)

Stockage de la clé d'appairage :
  ~/.config/one_daemon.json  (ou --config)
  Format : {"address": "AA:BB:CC:DD:EE:FF", "shared_key": "hexstring"}

Usage :
    python one_daemon.py --address AA:BB:CC:DD:EE:FF [options]
    python one_daemon.py --pair   (scan + appairage, stocke la clé, puis démarre)

Variables d'environnement :
    ONE_ADDRESS       Adresse BLE du module
    ONE_PUB_PORT      Port ZMQ PUB  (défaut 5560)
    ONE_CMD_PORT      Port ZMQ PULL (défaut 5561)
    ONE_CONFIG        Chemin config JSON (défaut ~/.config/one_daemon.json)
    ONE_LOG_LEVEL     DEBUG / INFO / WARNING (défaut INFO)

Compatible Python 3.9+  —  sans Qt.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import zmq
import zmq.asyncio

# Assurons que le dossier parent est dans sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from one.one_ble import OneBLEClient, OnePairingResult, OneStatus

logger = logging.getLogger(__name__)

DEFAULT_PUB_PORT = 5560
DEFAULT_CMD_PORT = 5561
DEFAULT_CONFIG   = Path.home() / ".config" / "one_daemon.json"

# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

class Topic:
    CONNECTION  = "one/connection"
    STATUS      = "one/status"
    PUMP_MODE   = "one/pump/mode"
    PUMP_STATE  = "one/pump/state"
    LIGHT_MODE  = "one/light/mode"
    LIGHT_STATE = "one/light/state"

    CMD_RETRY = "one/cmd/retry"
    CMD_PAIR  = "one/cmd/pair"


# ---------------------------------------------------------------------------
# Config persistante (shared_key)
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.warning("Config illisible (%s): %s", path, e)
    return {}


def save_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    logger.info("Config sauvegardée: %s", path)


# ---------------------------------------------------------------------------
# Publisher ZMQ thread-safe
# ---------------------------------------------------------------------------

class ZmqPublisher:

    def __init__(self, port: int):
        self._ctx  = zmq.Context()
        self._sock = self._ctx.socket(zmq.PUB)
        self._sock.bind(f"tcp://*:{port}")
        self._lock = threading.Lock()
        logger.info("ZMQ PUB tcp://*:%d", port)

    def publish(self, topic: str, payload: dict) -> None:
        msg = json.dumps(payload, default=str).encode()
        with self._lock:
            self._sock.send_multipart([topic.encode(), msg])

    def close(self) -> None:
        self._sock.close()
        self._ctx.term()


# ---------------------------------------------------------------------------
# Listener de commandes ZMQ (PULL)
# ---------------------------------------------------------------------------

class ZmqCmdListener:

    def __init__(self, port: int, on_retry, on_pair):
        self._port     = port
        self._on_retry = on_retry
        self._on_pair  = on_pair
        self._running  = False

    async def run(self) -> None:
        ctx  = zmq.asyncio.Context()
        sock = ctx.socket(zmq.PULL)
        sock.bind(f"tcp://*:{self._port}")
        logger.info("ZMQ CMD PULL tcp://*:%d", self._port)
        self._running = True
        try:
            while self._running:
                try:
                    parts = await asyncio.wait_for(sock.recv_multipart(), timeout=1.0)
                    if parts:
                        cmd = parts[0].decode()
                        if cmd == Topic.CMD_RETRY:
                            self._on_retry()
                        elif cmd == Topic.CMD_PAIR:
                            self._on_pair()
                except asyncio.TimeoutError:
                    pass
        finally:
            sock.close()
            ctx.term()

    def stop(self) -> None:
        self._running = False


# ---------------------------------------------------------------------------
# Daemon principal
# ---------------------------------------------------------------------------

class OneDaemon:
    """Démon de connexion BLE → ZMQ pour le module One."""

    def __init__(
        self,
        address: str,
        shared_key: bytes,
        pub_port: int,
        cmd_port: int,
        config_path: Path,
        poll_interval_s: float = 5.0,
        adapter: str = "",
    ):
        self.address        = address
        self.shared_key     = shared_key
        self.config_path    = config_path
        self.poll_interval  = poll_interval_s
        self.adapter        = adapter
        self.pub            = ZmqPublisher(pub_port)
        self._stop          = False
        self._retry_event   = asyncio.Event()
        self._pair_event    = asyncio.Event()
        self._client: OneBLEClient | None = None

        self.cmd_listener = ZmqCmdListener(
            port=cmd_port,
            on_retry=lambda: self._retry_event.set(),
            on_pair=lambda: self._pair_event.set(),
        )

    # ------------------------------------------------------------------
    # Publication
    # ------------------------------------------------------------------

    def _pub_connection(self, state: str, message: str = "", retry: int = 0) -> None:
        self.pub.publish(Topic.CONNECTION, {
            "state":   state,
            "message": message,
            "retry":   retry,
            "ts":      datetime.now().isoformat(),
        })

    def _pub_status(self, status: OneStatus) -> None:
        d = status.as_dict()
        d["ts"] = datetime.now().isoformat()
        self.pub.publish(Topic.STATUS,      d)
        self.pub.publish(Topic.PUMP_MODE,   {"value": status.filtration_mode,  "ts": d["ts"]})
        self.pub.publish(Topic.PUMP_STATE,  {"value": status.filtration_state, "ts": d["ts"]})
        self.pub.publish(Topic.LIGHT_MODE,  {"value": status.eclairage_mode,   "ts": d["ts"]})
        self.pub.publish(Topic.LIGHT_STATE, {"value": status.eclairage_state,  "ts": d["ts"]})

    # ------------------------------------------------------------------
    # Appairage interactif
    # ------------------------------------------------------------------

    async def _do_pair(self) -> bool:
        """Scan + appairage (bouton sur le module requis)."""
        logger.info("Démarrage du scan d'appairage (30 s) — appuyez sur le bouton du module…")
        self._pub_connection("pairing", "Scan appairage en cours…")
        devices = await OneBLEClient.scan_for_pairing(timeout=30.0, adapter=self.adapter)

        if not devices:
            logger.warning("Aucun module en mode appairage trouvé")
            self._pub_connection("error", "Aucun module en mode appairage")
            return False

        # Prend le premier si adresse non spécifiée, ou filtre sur l'adresse connue
        device = next(
            (d for d in devices if not self.address or d.address.lower() == self.address.lower()),
            devices[0],
        )
        logger.info("Module trouvé: %s (%s)", device.address, device.name)

        try:
            client, result = await OneBLEClient.pair(device.address, adapter=self.adapter)
            self._client    = client
            self.address    = result.address
            self.shared_key = result.shared_key

            cfg = load_config(self.config_path)
            cfg["address"]    = result.address
            cfg["shared_key"] = result.shared_key.hex()
            cfg["model"]      = result.model
            cfg["serial"]     = result.serial
            save_config(self.config_path, cfg)

            logger.info("Appairage réussi — clé: %s", result.shared_key.hex())
            self._pub_connection("connected", f"Appairé avec {result.address}")
            return True
        except Exception as e:
            logger.error("Appairage échoué: %s", e)
            self._pub_connection("error", f"Appairage échoué: {e}")
            return False

    # ------------------------------------------------------------------
    # Boucle de connexion / reconnexion
    # ------------------------------------------------------------------

    async def _session(self, retry: int) -> None:
        """Une session BLE complète : connexion → auth → subscribe → boucle."""
        self._pub_connection("connecting", f"Connexion… essai {retry}", retry=retry)
        self._client = OneBLEClient(self.address, self.shared_key, adapter=self.adapter)

        await self._client.connect_and_auth()

        self._pub_connection("connected", self.address)
        logger.info("Connecté et authentifié (essai %d)", retry)

        # Abonnement aux notifications STATUS (subscribe CCCD ne requiert pas d'auth)
        await self._client.subscribe_status(self._pub_status)
        logger.info("Subscribe STATUS OK — notifications actives")

        # Lecture initiale best-effort : peut échouer avec NotAuthorized si l'auth
        # AES applicative n'est pas acceptée. Dans ce cas on attend les notifications.
        try:
            status = await self._client.read_status()
            self._pub_status(status)
        except Exception as e:
            logger.warning("Lecture initiale ignorée (%s) — état attendu par notification", e)

        # Boucle de maintien : les notifications alimentent _pub_status via callback.
        # Pas besoin de poll read_status() — on détecte la déconnexion via is_connected.
        while not self._stop and self._client.is_connected:
            self._retry_event.clear()
            try:
                await asyncio.wait_for(self._retry_event.wait(), timeout=self.poll_interval)
                # Retry demandé explicitement
                logger.info("Reconnexion forcée par commande")
                break
            except asyncio.TimeoutError:
                if not self._client.is_connected:
                    break
                # Connexion toujours active — les notifications continuent

    async def _acquisition_loop(self) -> None:
        retry = 0
        while not self._stop:
            # Appairage demandé ?
            if self._pair_event.is_set():
                self._pair_event.clear()
                await self._do_pair()
                if self._client and self._client.is_connected:
                    # Post-appairage : boucle de session directe
                    try:
                        status = await self._client.read_status()
                        self._pub_status(status)
                        await self._client.subscribe_status(self._pub_status)
                        while not self._stop and self._client.is_connected:
                            await asyncio.sleep(self.poll_interval)
                    except Exception as e:
                        logger.warning("Session post-appairage interrompue: %s", e)
                continue

            try:
                await self._session(retry)
            except Exception as e:
                logger.error("Session interrompue (essai %d): %s", retry, e)
                self._pub_connection("error", str(e), retry=retry)

            if self._client:
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
                self._client = None

            if self._stop:
                break

            retry += 1
            delay = min(3.0 + retry * 2.0, 60.0)
            logger.info("Reconnexion dans %.0f s (essai %d)…", delay, retry)
            self._pub_connection("disconnected", f"Attente reconnexion ({delay:.0f}s)", retry=retry)

            try:
                await asyncio.wait_for(
                    asyncio.shield(self._retry_event.wait()),
                    timeout=delay,
                )
                self._retry_event.clear()
                logger.info("Reconnexion anticipée")
            except asyncio.TimeoutError:
                pass

    async def _heartbeat_loop(self) -> None:
        while not self._stop:
            await asyncio.sleep(30)

    # ------------------------------------------------------------------

    async def run(self) -> None:
        tasks = [
            asyncio.create_task(self._acquisition_loop()),
            asyncio.create_task(self.cmd_listener.run()),
            asyncio.create_task(self._heartbeat_loop()),
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            for t in tasks:
                t.cancel()
            if self._client:
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
            self.pub.close()
            logger.info("Daemon One arrêté.")

    def stop(self) -> None:
        self._stop = True
        self.cmd_listener.stop()


# ---------------------------------------------------------------------------
# Mode appairage CLI (--pair)
# ---------------------------------------------------------------------------

async def _run_pair_cli(config_path: Path, address: str, adapter: str = "") -> OnePairingResult | None:
    """Appairage en ligne de commande (sans démarrer le démon)."""
    print("Appairage One — appuyez sur le bouton du module maintenant…")
    print(f"Scan pendant 30 secondes...")

    devices = await OneBLEClient.scan_for_pairing(timeout=30.0, adapter=adapter)
    if not devices:
        print("Aucun module en mode appairage trouvé.")
        return None

    if address:
        device = next((d for d in devices if d.address.lower() == address.lower()), None)
        if not device:
            print(f"Module {address} non trouvé en mode appairage.")
            return None
    else:
        if len(devices) > 1:
            print("Modules trouvés :")
            for i, d in enumerate(devices):
                print(f"  [{i}] {d.address}  {d.name or '—'}")
            idx = int(input("Choisir : "))
        else:
            idx = 0
        device = devices[idx]

    print(f"Appairage avec {device.address} …")
    pairing_client, result = await OneBLEClient.pair(device.address, adapter=adapter)
    # Déconnexion critique : libère la connexion BLE avant de fermer ce loop.
    # Sans ça, le module reste occupé et le daemon ne peut pas se reconnecter.
    # Supprime aussi les handlers WinRT NOTIFY pour éviter "Event loop is closed".
    await pairing_client.disconnect()

    cfg = load_config(config_path)
    cfg["address"]    = result.address
    cfg["shared_key"] = result.shared_key.hex()
    cfg["model"]      = result.model
    cfg["serial"]     = result.serial
    save_config(config_path, cfg)

    print(f"Appairage réussi !")
    print(f"  Adresse   : {result.address}")
    print(f"  Modèle    : {result.model}")
    print(f"  Série     : {result.serial}")
    print(f"  Firmware  : {result.firmware}")
    print(f"  Shared key: {result.shared_key.hex()}")
    print(f"Config sauvegardée: {config_path}")
    return result


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="One BLE daemon (headless)")
    p.add_argument("--address",
                   default=os.environ.get("ONE_ADDRESS", ""),
                   help="Adresse BLE du module One (ex: AA:BB:CC:DD:EE:FF)")
    p.add_argument("--pair", action="store_true",
                   help="Déclenche un appairage (bouton module requis) puis démarre le démon")
    p.add_argument("--pair-only", action="store_true",
                   help="Appairage uniquement, sans démarrer le démon")
    p.add_argument("--pub-port", type=int,
                   default=int(os.environ.get("ONE_PUB_PORT", DEFAULT_PUB_PORT)),
                   help=f"Port ZMQ PUB (défaut {DEFAULT_PUB_PORT})")
    p.add_argument("--cmd-port", type=int,
                   default=int(os.environ.get("ONE_CMD_PORT", DEFAULT_CMD_PORT)),
                   help=f"Port ZMQ CMD PULL (défaut {DEFAULT_CMD_PORT})")
    p.add_argument("--config",
                   default=os.environ.get("ONE_CONFIG", str(DEFAULT_CONFIG)),
                   help=f"Chemin config JSON (défaut {DEFAULT_CONFIG})")
    p.add_argument("--poll-interval", type=float,
                   default=float(os.environ.get("ONE_POLL_INTERVAL", "5.0")),
                   help="Intervalle poll BLE en secondes (défaut 5.0)")
    p.add_argument("--log-level",
                   default=os.environ.get("ONE_LOG_LEVEL", "INFO"),
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p.add_argument("--adapter",
                   default=os.environ.get("ONE_BT_ADAPTER", ""),
                   help="Adaptateur Bluetooth BlueZ (ex: hci1 pour dongle USB, défaut: hci0)")
    return p.parse_args()


def _make_event_loop() -> asyncio.AbstractEventLoop:
    """Crée un SelectorEventLoop sur Windows (requis par ZMQ — ProactorEventLoop
    n'implémente pas add_reader). Sur les autres OS, retourne le loop par défaut.
    Évite l'usage de WindowsSelectorEventLoopPolicy (deprecated Python 3.14+)."""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()


def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    config_path = Path(args.config)

    # ---- Appairage seul (--pair-only) ----
    if args.pair_only:
        loop = _make_event_loop()
        result = loop.run_until_complete(_run_pair_cli(config_path, args.address, adapter=args.adapter))
        loop.close()
        sys.exit(0 if result else 1)

    # ---- Chargement config ----
    cfg = load_config(config_path)

    address    = args.address or cfg.get("address", "")
    shared_hex = cfg.get("shared_key", "")
    shared_key = bytes.fromhex(shared_hex) if shared_hex else b""

    # ---- Appairage si demandé ou si pas de clé ----
    need_pair = args.pair or not shared_key or not address
    if need_pair:
        loop = _make_event_loop()
        result = loop.run_until_complete(_run_pair_cli(config_path, address, adapter=args.adapter))
        loop.close()
        if not result:
            sys.exit(1)
        address    = result.address
        shared_key = result.shared_key
        if args.pair_only:
            sys.exit(0)

    if not address:
        logger.error("Adresse BLE non spécifiée. Utilisez --address ou --pair.")
        sys.exit(1)
    if not shared_key:
        logger.error("Shared key absente. Utilisez --pair pour appaire le module.")
        sys.exit(1)

    loop = _make_event_loop()
    asyncio.set_event_loop(loop)

    daemon = OneDaemon(
        address=address,
        shared_key=shared_key,
        pub_port=args.pub_port,
        cmd_port=args.cmd_port,
        config_path=config_path,
        poll_interval_s=args.poll_interval,
        adapter=args.adapter,
    )

    def _sig_handler():
        logger.info("Signal reçu — arrêt…")
        daemon.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig_handler)
        except NotImplementedError:
            # Windows
            signal.signal(sig, lambda *_: _sig_handler())

    try:
        loop.run_until_complete(daemon.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
