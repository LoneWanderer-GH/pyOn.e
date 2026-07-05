"""
one_ble.py — Bibliothèque BLE Python 3 pour le module One (WA Conception)
==========================================================================

Gère :
  - scan des dispositifs One (mode utilisation ou mode appairage)
  - appairage (bouton sur le module + lecture shared_key + handshake AES)
  - connexion (reconnexion avec shared_key stockée)
  - lecture / notification du statut (pompe + éclairage)

Protocole extrait du code JS décompilé (Hermes/React Native).

Dépendances : bleak, pycryptodome (Crypto.Cipher.AES)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from Crypto.Cipher import AES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# UUIDs BLE
# ---------------------------------------------------------------------------

# -- Service système (auth, commun à tous les produits One) --
SVC_SYSTEM_UUID      = "fbde0000-4c7b-4e67-8292-a9b8e686cf87"
CHR_RANDOM_KEY_UUID  = "fbde0001-4c7b-4e67-8292-a9b8e686cf87"
CHR_SHARED_KEY_UUID  = "fbde0002-4c7b-4e67-8292-a9b8e686cf87"
CHR_ENCRYPT_KEY_UUID = "fbde0003-4c7b-4e67-8292-a9b8e686cf87"

# -- Service infos périphérique (GATT standard) --
SVC_DEVINFO_UUID     = "0000180a-0000-1000-8000-00805f9b34fb"
CHR_MODEL_UUID       = "00002a24-0000-1000-8000-00805f9b34fb"
CHR_SERIAL_UUID      = "00002a25-0000-1000-8000-00805f9b34fb"
CHR_FIRMWARE_UUID    = "00002a26-0000-1000-8000-00805f9b34fb"

# -- Service heure (GATT standard) --
SVC_TIME_UUID        = "00001805-0000-1000-8000-00805f9b34fb"
CHR_DATETIME_UUID    = "00002a08-0000-1000-8000-00805f9b34fb"
CHR_DAYOFWEEK_UUID   = "00002a09-0000-1000-8000-00805f9b34fb"

# -- Service One (pompe + éclairage) --
SVC_ONE_UUID         = "fbde0100-4c7b-4e67-8292-a9b8e686cf87"
CHR_CONTROLE_UUID    = "fbde0101-4c7b-4e67-8292-a9b8e686cf87"
CHR_FILTRATION_UUID  = "fbde0102-4c7b-4e67-8292-a9b8e686cf87"
CHR_ECLAIRAGE_UUID   = "fbde0103-4c7b-4e67-8292-a9b8e686cf87"
CHR_STATUS_UUID      = "fbde0104-4c7b-4e67-8292-a9b8e686cf87"

# UUID de service annoncé par le module selon son mode :
#   FBDE0100 → mode appairage (bouton pressé)
#   FBDE0000 → mode utilisation normale
ADV_UUID_PAIR = "fbde0100-4c7b-4e67-8292-a9b8e686cf87"
ADV_UUID_USE  = "fbde0000-4c7b-4e67-8292-a9b8e686cf87"

# Clé privée fixe (extraite du binaire JS)
PRIVATE_KEY = bytes.fromhex("1141a80537444a6a85888d84115f2811")

# ---------------------------------------------------------------------------
# Modèle de données
# ---------------------------------------------------------------------------

FILTRATION_MODES = {0: "Manuel", 1: "Horloge", 2: "Auto"}
ECLAIRAGE_MODES  = {0: "Manuel", 1: "Horloge", 2: "Auto"}


@dataclass
class OneStatus:
    """État instantané pompe + éclairage."""
    filtration_mode:  int = 0   # 0=Manuel 1=Horloge 2=Auto
    filtration_state: int = 0   # 0=arrêté 1=en marche
    eclairage_mode:   int = 0   # 0=Manuel 1=Horloge 2=Auto
    eclairage_state:  int = 0   # 0=éteint 1=allumé
    eclairage_type:   int = 0   # 0/1 selon type d'éclairage installé

    @classmethod
    def from_byte(cls, b: int) -> "OneStatus":
        return cls(
            filtration_mode  = b & 0x03,
            filtration_state = (b >> 2) & 0x01,
            eclairage_mode   = (b >> 3) & 0x03,
            eclairage_state  = (b >> 5) & 0x01,
            eclairage_type   = (b >> 6) & 0x01,
        )

    def as_dict(self) -> dict:
        return {
            "filtration_mode":       self.filtration_mode,
            "filtration_mode_label": FILTRATION_MODES.get(self.filtration_mode, "?"),
            "filtration_state":      self.filtration_state,
            "eclairage_mode":        self.eclairage_mode,
            "eclairage_mode_label":  ECLAIRAGE_MODES.get(self.eclairage_mode, "?"),
            "eclairage_state":       self.eclairage_state,
            "eclairage_type":        self.eclairage_type,
        }


@dataclass
class OnePairingResult:
    """Résultat d'un appairage réussi — à sauvegarder pour reconnexion future."""
    address:    str
    model:      str
    serial:     str
    firmware:   str
    shared_key: bytes   # 16 octets, à persister (hex ou b64)


# ---------------------------------------------------------------------------
# Helpers auth
# ---------------------------------------------------------------------------

def _aes_encrypt(shared_key: bytes, random_key: bytes) -> bytes:
    """Calcule la réponse au challenge d'authentification.

    Protocole :
      plaintext  = shared_key(16) + random_key(16)  → 32 octets
      ciphertext = AES-ECB(PRIVATE_KEY, plaintext)
      réponse    = reversed(ciphertext)
    """
    plaintext  = shared_key + random_key
    cipher     = AES.new(PRIVATE_KEY, AES.MODE_ECB)
    ciphertext = cipher.encrypt(plaintext)
    return bytes(reversed(ciphertext))


def _encode_datetime(dt: datetime) -> bytes:
    """Encode une datetime au format attendu par le module One (6 octets).

    Format JS (f5754) : [2-digit-year, month, day, hour, minute, second]
    — chaque champ sur 1 octet, année sur 2 chiffres (ex: 26 pour 2026).
    NB : différent du GATT 2A08 standard (uint16 pour l'année).
    """
    return bytes([
        dt.year % 100,  # 2-digit year
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
    ])


def _day_of_week_byte(dt: datetime) -> bytes:
    """Jour de la semaine au format JS : 0=Lundi … 6=Dimanche.

    JS (f5754) : (moment().day() + 6) % 7  où day() est 0=Dim…6=Sam.
    isoweekday() Python : 1=Lun…7=Dim → (isoweekday() - 1) % 7 → 0=Lun…6=Dim.
    """
    return bytes([(dt.isoweekday() - 1) % 7])


# ---------------------------------------------------------------------------
# Classe principale
# ---------------------------------------------------------------------------

class OneBLEClient:
    """Client BLE asynchrone pour le module One WA Conception.

    Cycle de vie normal :
        client = OneBLEClient(address, shared_key)
        await client.connect_and_auth()   # connexion + auth + sync RTC
        await client.subscribe_status(callback)
        status = await client.read_status()
        ...
        await client.disconnect()

    Pour un premier appairage (bouton sur le module) :
        device, result = await OneBLEClient.pair(address_or_ble_device)
        # sauvegarder result.shared_key.hex() pour reconnexion
    """

    def __init__(self, address: str, shared_key: bytes):
        self.address    = address
        self.shared_key = shared_key
        self._client: Optional[BleakClient] = None

    # ---------------------------------------------------------------- scan

    @staticmethod
    async def scan_for_use(timeout: float = 10.0) -> list[BLEDevice]:
        """Scan les modules One en mode utilisation normale (ADV_UUID_USE)."""
        found: list[BLEDevice] = []
        found_event = asyncio.Event()

        def _cb(device: BLEDevice, ad_data):
            uuids = [u.lower() for u in (ad_data.service_uuids or [])]
            if ADV_UUID_USE in uuids and device not in found:
                found.append(device)
                logger.debug("Trouvé (use): %s %s", device.address, device.name)
                found_event.set()

        async with BleakScanner(detection_callback=_cb):
            try:
                await asyncio.wait_for(found_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass

        return found

    @staticmethod
    async def scan_for_pairing(timeout: float = 30.0) -> list[BLEDevice]:
        """Scan les modules One en mode appairage (ADV_UUID_PAIR).

        S'arrête dès le premier module trouvé (comme le JS resetAndStopScan).
        Le bouton sur le module doit être pressé au préalable.
        """
        found: list[BLEDevice] = []
        found_event = asyncio.Event()

        def _cb(device: BLEDevice, ad_data):
            uuids = [u.lower() for u in (ad_data.service_uuids or [])]
            if ADV_UUID_PAIR in uuids and device not in found:
                found.append(device)
                logger.info("Module en mode appairage: %s %s", device.address, device.name)
                found_event.set()  # Arrêt immédiat dès le premier trouvé

        async with BleakScanner(detection_callback=_cb):
            try:
                await asyncio.wait_for(found_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass  # Aucun module dans le délai

        return found

    # ---------------------------------------------------------------- appairage

    @classmethod
    async def pair(cls, address: str) -> tuple["OneBLEClient", OnePairingResult]:
        """Appaire un module One vierge (ou réinitialisé).

        Pré-requis : le bouton d'appairage du module doit être pressé
        (module en mode association, advertising FBDE0100).

        Séquence JS complète (connectWithAssociation) :
          1. connectProcess   — connexion + MTU + service discovery
          2. identificationProcess — modèle / série / firmware
          3. associationProcess    — lecture shared_key FBDE0002
          4. authorisationProcess  — AES auth → écriture FBDE0003
          5. syncRTCProcess        — sync horloge
          6. utilisationProcess    — subscribe STATUS + read STATUS ← CRITIQUE !
             En mode association, le module accepte ces lectures.
             C'est cette étape qui "finalise" la session auth.

        Retourne (client_authentifié, OnePairingResult).
        Persister result.shared_key.hex() dans la config pour les reconnexions.
        """
        logger.info("Démarrage appairage avec %s", address)
        client = cls.__new__(cls)
        client.address    = address
        client.shared_key = b""
        client._client    = BleakClient(address, timeout=15.0)
        await client._client.connect()
        logger.info("Connecté (appairage)")

        # 1+2. Identification
        model    = (await client._client.read_gatt_char(CHR_MODEL_UUID)).decode().strip("\x00")
        serial   = (await client._client.read_gatt_char(CHR_SERIAL_UUID)).decode().strip("\x00")
        firmware = (await client._client.read_gatt_char(CHR_FIRMWARE_UUID)).decode().strip("\x00")
        logger.info("Modèle=%s  Série=%s  FW=%s", model, serial, firmware)

        # 3. Lecture shared_key (FBDE0002) — octets inversés (JS f5731)
        raw_shared        = await client._client.read_gatt_char(CHR_SHARED_KEY_UUID)
        client.shared_key = bytes(reversed(raw_shared))
        logger.info("Shared key lu depuis FBDE0002: %s (%d bytes)", client.shared_key.hex(), len(client.shared_key))

        # 4. Auth AES applicative (JS f5738)
        await client._authenticate()

        # 5. Sync RTC (JS f5754)
        await client._sync_rtc()

        # 6. utilisationProcess (JS) — subscribe + read STATUS
        #    En mode association, le module est permissif et accepte ces opérations.
        #    Cette étape finalise la session auth côté module.
        logger.info("utilisationProcess — subscribe + read STATUS (mode association)")
        try:
            def _dummy_cb(status: "OneStatus") -> None:
                logger.info("Notification STATUS reçue (appairage): %s", status)

            await client.subscribe_status(_dummy_cb)

            # Re-lecture FBDE0002 APRÈS auth : certains modules génèrent
            # une nouvelle shared_key à ce moment-là
            raw_shared2 = await client._client.read_gatt_char(CHR_SHARED_KEY_UUID)
            if raw_shared2 != raw_shared:
                client.shared_key = bytes(reversed(raw_shared2))
                logger.info("FBDE0002 mis à jour après auth: %s", client.shared_key.hex())

            # Lecture initiale STATUS (utilisationProcess JS)
            try:
                status = await client.read_status()
                logger.info("STATUS lu (appairage): %s", status)
            except Exception as e:
                logger.debug("read_status ignoré (appairage): %s", e)

        except Exception as e:
            logger.warning("utilisationProcess partiel (appairage): %s", e)

        result = OnePairingResult(
            address=address,
            model=model,
            serial=serial,
            firmware=firmware,
            shared_key=client.shared_key,
        )
        return client, result

    # ---------------------------------------------------------------- connexion normale

    async def connect_and_auth(self) -> None:
        """Connexion + auth AES + bonding BLE + sync RTC.

        Séquence corrigée (Fix #1 + Fix #2) :
          1. Connexion BLE.
          2. Auth AES applicative (FBDE0001 → FBDE0003) — fonctionne sans chiffrement.
          3. Re-lecture FBDE0002 post-auth : détection rotation de shared_key (Fix #1).
          4. Bonding BLE (SMP pair()) — APRÈS l'AES auth (Fix #2).
             Le module exige un lien chiffré pour 2A08 (RTC) et FBDE0104 (STATUS).
             Android/iOS gèrent le bonding de façon transparente (OS); BlueZ requiert
             un appel explicite. pair() est appelé APRÈS l'AES auth car l'ordre
             inverse provoque un AuthenticationFailed.
          5. Sync RTC (best-effort, non bloquant).

        Fix #1 (2026-07-05) : re-lecture FBDE0002 post-auth, détection rotation clé.
        Fix #2 (2026-07-05) : ajout pair() post-AES-auth pour lien BLE chiffré.
        """
        logger.info("Connexion à %s", self.address)
        self._client = BleakClient(self.address)
        await self._client.connect()
        logger.info("Connecté")
        await self._authenticate()

        # Fix #1 — re-lecture FBDE0002 post-auth (détection rotation shared_key)
        # Référence : docs/diagrams/python/04_diff_analysis.md — Fix #1
        try:
            raw_shared2 = await self._client.read_gatt_char(CHR_SHARED_KEY_UUID)
            new_shared_key = bytes(reversed(raw_shared2))
            if new_shared_key != self.shared_key:
                logger.warning(
                    "FBDE0002 a changé après auth — rotation de shared_key détectée: %s → %s",
                    self.shared_key.hex(), new_shared_key.hex(),
                )
                self.shared_key = new_shared_key
                # Rejouer l'auth avec la nouvelle clé
                await self._authenticate()
                logger.info("Re-auth avec nouvelle shared_key OK")
            else:
                logger.debug("FBDE0002 stable après auth: %s", self.shared_key.hex())
        except Exception as e:
            # Non bloquant : certains firmwares refusent la lecture de FBDE0002 en
            # mode connexion normale (uniquement accessible en mode appairage)
            logger.debug("Re-lecture FBDE0002 post-auth ignorée: %s", e)

        # Fix #2 — Bonding BLE (SMP) après AES auth
        # Le module répond NotAuthorized sur 2A08 et FBDE0104 sans lien chiffré.
        # Android/iOS déclenchent le SMP automatiquement ; BlueZ requiert pair().
        # L'ordre est critique : pair() APRÈS _authenticate(), pas avant.
        # Référence : docs/diagrams/python/04_diff_analysis.md — Check #2
        try:
            logger.debug("Tentative bonding BLE (SMP pair)…")
            await self._client.pair()
            logger.info("Bonding BLE établi")
        except Exception as e:
            # Ignoré : si le bond existe déjà en cache BlueZ, pair() peut
            # retourner une erreur bénigne. On continue dans tous les cas.
            logger.warning("pair() ignoré (bond peut-être déjà actif): %s", e)

        await self._sync_rtc()
        logger.info("Auth + RTC OK")

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    # ---------------------------------------------------------------- statut

    async def read_status(self) -> OneStatus:
        """Lit le statut courant (pompe + éclairage) en une seule lecture GATT."""
        data = await self._client.read_gatt_char(CHR_STATUS_UUID)
        status = OneStatus.from_byte(data[0])
        logger.debug("Status lu: %s", status)
        return status

    async def subscribe_status(self, callback: Callable[[OneStatus], None]) -> None:
        """S'abonne aux notifications de statut.

        callback(status: OneStatus) est appelé à chaque changement.
        """
        def _handler(_, data: bytearray):
            status = OneStatus.from_byte(data[0])
            logger.debug("Notification status: %s", status)
            callback(status)

        await self._client.start_notify(CHR_STATUS_UUID, _handler)
        logger.debug("Abonné aux notifications STATUS")

    async def unsubscribe_status(self) -> None:
        await self._client.stop_notify(CHR_STATUS_UUID)

    # ---------------------------------------------------------------- interne auth

    async def _authenticate(self) -> None:
        """Handshake AES d'autorisation.

        Séquence :
          1. read  CHR_RANDOM  → random_key (inversé)
          2. AES-ECB(PRIVATE_KEY, shared_key + random_key) inversé
          3. write CHR_ENCRYPT → réponse chiffrée
        """
        raw_random = await self._client.read_gatt_char(CHR_RANDOM_KEY_UUID)
        random_key = bytes(reversed(raw_random[:16]))
        logger.debug("Random key: %s", random_key.hex())

        response = _aes_encrypt(self.shared_key, random_key)
        logger.debug("Auth response: %s", response.hex())

        await self._client.write_gatt_char(CHR_ENCRYPT_KEY_UUID, response, response=True)
        logger.info("Authentification réussie")

    async def _sync_rtc(self) -> None:
        """Synchronise l'horloge du module avec l'heure locale."""
        now = datetime.now()
        try:
            await self._client.write_gatt_char(
                CHR_DATETIME_UUID, _encode_datetime(now), response=True
            )
            await self._client.write_gatt_char(
                CHR_DAYOFWEEK_UUID, _day_of_week_byte(now), response=True
            )
            logger.debug("RTC synchronisée: %s", now.isoformat())
        except Exception as e:
            # Non bloquant — certains firmwares ignorent l'écriture RTC
            logger.warning("Sync RTC ignorée: %s", e)
