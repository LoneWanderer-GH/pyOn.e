# Python — Séquence connexion normale (`connect_and_auth`)

> Source : `one/one_ble.py` — méthodes `connect_and_auth()`, `_authenticate()`, `_sync_rtc()`  
> Comparaison JS : [03_sequence_connection.md](../js/03_sequence_connection.md)  
> **Fix #1 appliqué le 2026-07-05** : re-lecture FBDE0002 post-auth.

```mermaid
sequenceDiagram
    participant D as OneDaemon._session()
    participant C as OneBLEClient
    participant BL as bleak BleakClient
    participant Dev as Module On.e
    participant ZMQ as ZMQ PUB :5560

    D->>ZMQ: one/connection {state: "connecting", retry: N}
    D->>C: OneBLEClient(address, shared_key)
    D->>C: connect_and_auth()

    rect rgb(220, 240, 255)
        Note over C,Dev: ── Connexion BLE ──
        C->>BL: BleakClient(address) [pas de timeout explicite]
        BL->>Dev: connect() [L2CAP / ATT]
        Note over Dev: ⚠️ Pas de requestMTU\nBlueZ négocie auto
        Dev-->>BL: connected
        BL-->>C: connected
    end

    rect rgb(255, 220, 220)
        Note over C,Dev: ── _authenticate() ── [✅ conforme JS authorisationProcess]
        C->>Dev: read_gatt_char(FBDE0001)
        Dev-->>C: raw[16]
        C->>C: random_key = bytes(reversed(raw[:16]))\nresponse = AES-ECB(PRIVATE_KEY,\n  shared_key+random_key) → reversed
        C->>Dev: write_gatt_char(FBDE0003, response[32B], response=True)
        Dev-->>C: ACK
    end

    rect rgb(255, 250, 180)
        Note over C,Dev: ── Fix #1 — re-lecture FBDE0002 post-auth ──
        C->>Dev: read_gatt_char(FBDE0002)
        Dev-->>C: raw2[16]
        C->>C: new_key = reversed(raw2)
        alt new_key ≠ self.shared_key (rotation détectée)
            C->>C: self.shared_key = new_key
            Note over C: WARNING: rotation shared_key détectée
            C->>Dev: read_gatt_char(FBDE0001) [re-auth avec nouvelle clé]
            Dev-->>C: raw3[16]
            C->>C: AES-ECB(PRIVATE_KEY, new_key+random_key3) → reversed
            C->>Dev: write_gatt_char(FBDE0003, response2[32B])
            Dev-->>C: ACK
        else new_key == self.shared_key (stable)
            Note over C: DEBUG: FBDE0002 stable
        end
        Note right of C: Exception ignorée si FBDE0002\nrefusé en mode normal
    end

    rect rgb(240, 220, 255)
        Note over C,Dev: ── _sync_rtc() ── [✅ conforme JS syncRTCProcess]
        C->>Dev: write_gatt_char(2A08, [year%100, month, day, h, m, s])
        C->>Dev: write_gatt_char(2A09, [(isoweekday-1)%7])
        Dev-->>C: ACK (exception ignorée si refus firmware)
    end

    Note over C: connect_and_auth() terminé

    D->>ZMQ: one/connection {state: "connected"}

    D->>C: subscribe_status(callback=_pub_status)
    rect rgb(200, 255, 240)
        Note over C,Dev: ── Subscribe NOTIFY ── [✅ conforme JS utilisationProcess]
        C->>Dev: start_notify(FBDE0104, _handler)
        Dev-->>C: CCCD activé
    end

    D->>C: read_status() [best-effort, erreur ignorée]
    rect rgb(200, 255, 240)
        C->>Dev: read_gatt_char(FBDE0104)
        Dev-->>C: status[1B]
        Note over Dev: ⚠️ Peut retourner NotAuthorized\nsi firmware exige bonding BLE
        C->>C: OneStatus.from_byte(data[0])
    end
    C-->>D: OneStatus (ou exception ignorée)
    D->>ZMQ: one/status + one/pump/* + one/light/*

    loop Boucle maintien (poll=5s)
        Dev-->>C: NOTIFY FBDE0104
        C->>C: OneStatus.from_byte(data[0])
        C-->>D: callback _pub_status
        D->>ZMQ: one/status\none/pump/mode, one/pump/state\none/light/mode, one/light/state
    end

    Note over D,Dev: Déconnexion détectée (is_connected=False)\nou _retry_event

    D->>C: disconnect()
    C->>Dev: disconnect()
    D->>ZMQ: one/connection {state: "disconnected", retry: N+1}
```

### Conformité vs JS — état après Fix #1

| Étape JS | Implémenté Python | Statut |
|---|---|---|
| identificationProcess (read 2A24/25/26) | ❌ Absent en mode normal | ℹ️ Mineur |
| authorisationProcess (FBDE0001→0003) | ✅ `_authenticate()` | ✅ |
| **Re-lecture FBDE0002 post-auth** | **✅ Fix #1 appliqué** | **✅ Corrigé** |
| syncRTCProcess | ✅ `_sync_rtc()` | ✅ |
| utilisationProcess (subscribe + read) | ✅ dans `_session()` | ✅ |


> Source : `one/one_ble.py` — méthodes `connect_and_auth()`, `_authenticate()`, `_sync_rtc()`  
> Comparaison JS : [03_sequence_connection.md](../js/03_sequence_connection.md)

```mermaid
sequenceDiagram
    participant D as OneDaemon._session()
    participant C as OneBLEClient
    participant BL as bleak BleakClient
    participant Dev as Module On.e
    participant ZMQ as ZMQ PUB :5560

    D->>ZMQ: one/connection {state: "connecting", retry: N}
    D->>C: OneBLEClient(address, shared_key)
    D->>C: connect_and_auth()

    rect rgb(220, 240, 255)
        Note over C,Dev: ── Connexion BLE ──
        C->>BL: BleakClient(address) [pas de timeout explicite]
        BL->>Dev: connect() [L2CAP / ATT]
        Note over Dev: ⚠️ Pas de requestMTU\nBlueZ négocie auto
        Dev-->>BL: connected
        BL-->>C: connected
    end

    rect rgb(255, 220, 220)
        Note over C,Dev: ── _authenticate() ── [✅ conforme JS authorisationProcess]
        C->>Dev: read_gatt_char(FBDE0001)
        Dev-->>C: raw[16]
        C->>C: random_key = bytes(reversed(raw[:16]))\nresponse = AES-ECB(PRIVATE_KEY,\n  shared_key+random_key) → reversed
        C->>Dev: write_gatt_char(FBDE0003, response[32B], response=True)
        Dev-->>C: ACK
    end

    rect rgb(240, 220, 255)
        Note over C,Dev: ── _sync_rtc() ── [✅ conforme JS syncRTCProcess]
        C->>Dev: write_gatt_char(2A08, [year%100, month, day, h, m, s])
        C->>Dev: write_gatt_char(2A09, [(isoweekday-1)%7])
        Dev-->>C: ACK (exception ignorée si refus firmware)
    end

    Note over C: connect_and_auth() terminé

    D->>ZMQ: one/connection {state: "connected"}

    D->>C: subscribe_status(callback=_pub_status)
    rect rgb(200, 255, 240)
        Note over C,Dev: ── Subscribe NOTIFY ── [✅ conforme JS utilisationProcess]
        C->>Dev: start_notify(FBDE0104, _handler)
        Dev-->>C: CCCD activé
    end

    D->>C: read_status() [best-effort, erreur ignorée]
    rect rgb(200, 255, 240)
        C->>Dev: read_gatt_char(FBDE0104)
        Dev-->>C: status[1B]
        Note over Dev: ⚠️ Peut retourner NotAuthorized\nsi firmware exige bonding BLE
        C->>C: OneStatus.from_byte(data[0])
    end
    C-->>D: OneStatus (ou exception ignorée)
    D->>ZMQ: one/status + one/pump/* + one/light/*

    loop Boucle maintien (poll=5s)
        Dev-->>C: NOTIFY FBDE0104
        C->>C: OneStatus.from_byte(data[0])
        C-->>D: callback _pub_status
        D->>ZMQ: one/status\none/pump/mode, one/pump/state\none/light/mode, one/light/state
    end

    Note over D,Dev: Déconnexion détectée (is_connected=False)\nou _retry_event

    D->>C: disconnect()
    C->>Dev: disconnect()
    D->>ZMQ: one/connection {state: "disconnected", retry: N+1}
```

### ⚠️ Différence critique identifiée vs JS — `connect` normal

| Étape JS | Implémenté Python | Risque |
|---|---|---|
| identificationProcess (read 2A24/25/26) | ❌ Absent en mode normal | ℹ️ Mineur — pas bloquant |
| authorisationProcess (FBDE0001→0003) | ✅ `_authenticate()` | OK |
| **Re-lecture FBDE0002 post-auth** | **❌ Absent dans `connect_and_auth()`** | **🔴 Critique si rotation clé** |
| syncRTCProcess | ✅ `_sync_rtc()` | OK |
| utilisationProcess (subscribe + read) | ✅ en deux temps dans `_session()` | OK |

> **Action corrective** → voir [04_diff_analysis.md](04_diff_analysis.md)
