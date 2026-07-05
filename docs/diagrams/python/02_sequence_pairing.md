# Python — Séquence appairage (`OneBLEClient.pair`)

> Source : `one/one_ble.py` — méthode `OneBLEClient.pair()`  
> Comparaison JS : [02_sequence_pairing.md](../js/02_sequence_pairing.md)

```mermaid
sequenceDiagram
    participant D as ble_daemon._do_pair()
    participant C as OneBLEClient.pair()
    participant BL as bleak BleakClient
    participant Dev as Module On.e
    participant ZMQ as ZMQ PUB :5560

    D->>ZMQ: one/connection {state: "pairing"}

    D->>C: scan_for_pairing(timeout=30s)
    Note over Dev: Bouton pressé → ADV FBDE0100
    Dev-->>C: BLEDevice (1er trouvé → event stop)
    C-->>D: devices[0]

    D->>C: OneBLEClient.pair(address)
    C->>BL: BleakClient(address, timeout=15s)
    BL->>Dev: connect() [L2CAP / ATT]
    Note over Dev: ⚠️ Pas de requestMTU explicite\nBlueZ négocie automatiquement\n(MTU ≤ 185B sur BT 4.2, 23B sur BT 4.0/4.1)
    Dev-->>BL: connected
    BL-->>C: connected

    rect rgb(220, 255, 220)
        Note over C,Dev: ── Identification ── [✅ conforme JS]
        C->>Dev: read_gatt_char(2A24)
        Dev-->>C: "ON.E"
        C->>Dev: read_gatt_char(2A25)
        Dev-->>C: serial
        C->>Dev: read_gatt_char(2A26)
        Dev-->>C: firmware
    end

    rect rgb(255, 240, 200)
        Note over C,Dev: ── Association (shared_key) ── [✅ conforme JS]
        C->>Dev: read_gatt_char(FBDE0002)
        Dev-->>C: raw[16]
        C->>C: shared_key = bytes(reversed(raw))
    end

    rect rgb(255, 220, 220)
        Note over C,Dev: ── Autorisation AES ── [✅ conforme JS]
        C->>Dev: read_gatt_char(FBDE0001)
        Dev-->>C: raw[16]
        C->>C: random_key = bytes(reversed(raw[:16]))\nplaintext = shared_key + random_key (32B)\nciphertext = AES-ECB(PRIVATE_KEY, plaintext)\nresponse = bytes(reversed(ciphertext))
        C->>Dev: write_gatt_char(FBDE0003, response[32B], response=True)
        Dev-->>C: ACK
    end

    rect rgb(240, 220, 255)
        Note over C,Dev: ── Sync RTC ── [✅ conforme JS]
        C->>Dev: write_gatt_char(2A08, [year%100, month, day, h, m, s])
        C->>Dev: write_gatt_char(2A09, [(isoweekday-1)%7])
        Dev-->>C: ACK (best-effort, exception ignorée)
    end

    rect rgb(200, 255, 240)
        Note over C,Dev: ── utilisationProcess Python ── [✅ conforme JS + rotation clé]
        C->>Dev: start_notify(FBDE0104, _handler)
        Dev-->>C: CCCD activé
        C->>Dev: read_gatt_char(FBDE0002) ← re-lecture post-auth
        Note right of C: ✅ Spécifique Python : détection\nrotation shared_key après auth
        Dev-->>C: raw2
        C->>C: si raw2 ≠ raw1 → shared_key = reversed(raw2)
        C->>Dev: read_gatt_char(FBDE0104)
        Dev-->>C: status[1B]
    end

    C-->>D: (OneBLEClient, OnePairingResult)
    D->>D: save_config(address, shared_key.hex())
    D->>ZMQ: one/connection {state: "connected"}
```

### Conformité vs JS
| Étape | JS | Python | Écart |
|---|---|---|---|
| Scan | `startDeviceScan` LowLatency | `BleakScanner` + event | ✅ Équivalent |
| requestMTU | Implicite Android ≥517B | Non fait (BlueZ auto) | ℹ️ Sans impact pour 1-32B |
| Identification | 2A24/25/26 | Idem | ✅ |
| SHARED_KEY (FBDE0002) | `reversed(raw)` | `bytes(reversed(raw))` | ✅ |
| AES handshake | ECB(PRIV, sk+rk) reversed | Idem | ✅ |
| Sync RTC | year%100, 6B + 1B | Idem | ✅ |
| subscribe FBDE0104 | `monitorCharacteristic` | `start_notify` | ✅ |
| read STATUS | `readCharacteristic` | `read_gatt_char` | ✅ |
| Re-lecture FBDE0002 | ❌ Absent | ✅ Ajouté | ✅ Python plus robuste |
