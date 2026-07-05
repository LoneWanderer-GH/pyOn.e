# JS — Séquence connexion normale (`connect`)

> Source : `one/decompiled_js/Bluetooth/BleNetworkManager.js` — méthode `connect`  
> Utilisé pour toutes les reconnexions après un appairage initial réussi (shared_key connue).  
> **Différence clé vs appairage : pas d'`associationProcess` (pas de lecture FBDE0002).**

```mermaid
sequenceDiagram
    participant App as App Android (JS)
    participant BNM as BleNetworkManager
    participant Dev as Module On.e (BLE)

    App->>BNM: connect(device, timeout=6000ms)
    BNM->>BNM: changeBleState(DeviceInConnectionProcess)

    rect rgb(220, 240, 255)
        Note over BNM,Dev: ── connectProcess ──
        BNM->>Dev: device.connect()
        Note over Dev: requestMTU(517) implicite
        Dev-->>BNM: connected
    end

    rect rgb(220, 255, 220)
        Note over BNM,Dev: ── identificationProcess ──
        BNM->>Dev: read 2A24 / 2A25 / 2A26
        Dev-->>BNM: model / serial / firmware
    end

    rect rgb(255, 220, 220)
        Note over BNM,Dev: ── authorisationProcess (SANS associationProcess) ──
        BNM->>Dev: readCharacteristic(FBDE0001) [RANDOM_KEY]
        Dev-->>BNM: raw[16] → random_key = reversed(raw)
        BNM->>BNM: AES-ECB(PRIVATE_KEY, shared_key+random_key)\n→ reversed → response
        BNM->>Dev: writeCharacteristicWithResponse(FBDE0003, response[32B])
        Dev-->>BNM: ACK
    end

    rect rgb(240, 220, 255)
        Note over BNM,Dev: ── syncRTCProcess ──
        BNM->>Dev: write 2A08 (datetime[6B]) + 2A09 (dayOfWeek[1B])
        Dev-->>BNM: ACK
    end

    rect rgb(200, 255, 240)
        Note over BNM,Dev: ── utilisationProcess ──
        BNM->>Dev: monitorCharacteristicForService(FBDE0104) [subscribe NOTIFY]
        Dev-->>BNM: CCCD activé
        BNM->>Dev: readCharacteristicForService(FBDE0104) [STATUS read initial]
        Dev-->>BNM: status[1B]
        BNM->>BNM: receiveComModel
    end

    BNM->>BNM: changeBleState(DeviceConnected)
    BNM-->>App: onDataChange.emit
```
