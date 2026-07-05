# JS — Séquence appairage (`connectWithAssociation`)

> Source : `one/decompiled_js/Bluetooth/BleNetworkManager.js` — méthode `connectWithAssociation`  
> Appelé uniquement quand le bouton physique du module est pressé (advertising FBDE0100).

```mermaid
sequenceDiagram
    participant App as App Android (JS)
    participant BNM as BleNetworkManager
    participant Dev as Module On.e (BLE)

    App->>BNM: scanForAppairage()
    BNM->>BNM: resetAndStopScan()\nchangeBleState(Scanning)
    BNM->>Dev: startDeviceScan([FBDE0100], LowLatency)
    Note over Dev: Bouton physique pressé\n→ advertising FBDE0100
    Dev-->>BNM: ADV packet (FBDE0100)
    BNM->>BNM: resetAndStopScan()\nassigner _device, _deviceModel, GUID
    BNM->>App: callback(device trouvé)

    App->>BNM: connectWithAssociation(device)
    BNM->>BNM: changeBleState(DeviceInAssociationProcess)

    rect rgb(220, 240, 255)
        Note over BNM,Dev: ── connectProcess ──
        BNM->>Dev: device.connect() [react-native-ble-plx]
        Note over Dev: requestMTU(517) implicite Android
        Dev-->>BNM: connected (MTU négocié)
    end

    rect rgb(220, 255, 220)
        Note over BNM,Dev: ── identificationProcess ──
        BNM->>Dev: readCharacteristic(180A / 2A24) [Model]
        Dev-->>BNM: "ON.E"
        BNM->>Dev: readCharacteristic(180A / 2A25) [Serial]
        Dev-->>BNM: serial
        BNM->>Dev: readCharacteristic(180A / 2A26) [Firmware]
        Dev-->>BNM: firmware
        BNM->>BNM: getInterfaceByLocalName("ONE")\ninitModel() → _deviceModel
    end

    rect rgb(255, 240, 200)
        Note over BNM,Dev: ── associationProcess ──
        BNM->>Dev: readCharacteristic(FBDE0000 / FBDE0002) [SHARED_KEY]
        Dev-->>BNM: raw[16]
        BNM->>BNM: shared_key = reversed(raw)
    end

    rect rgb(255, 220, 220)
        Note over BNM,Dev: ── authorisationProcess ──
        BNM->>Dev: readCharacteristic(FBDE0000 / FBDE0001) [RANDOM_KEY]
        Dev-->>BNM: raw[16]
        BNM->>BNM: random_key = reversed(raw)\nplaintext = shared_key + random_key (32B)\nciphertext = AES-128-ECB(PRIVATE_KEY, plaintext)\nresponse = reversed(ciphertext)
        BNM->>Dev: writeCharacteristicWithResponse(FBDE0000/FBDE0003, response[32B])
        Dev-->>BNM: ACK (auth OK)
    end

    rect rgb(240, 220, 255)
        Note over BNM,Dev: ── syncRTCProcess ──
        BNM->>Dev: writeCharacteristicWithResponse(1805/2A08, datetime[6B])
        Note right of BNM: [year%100, month, day, hour, min, sec]
        BNM->>Dev: writeCharacteristicWithResponse(1805/2A09, dayOfWeek[1B])
        Note right of BNM: (isoweekday-1)%7 → 0=Lun
        Dev-->>BNM: ACK
    end

    rect rgb(200, 255, 240)
        Note over BNM,Dev: ── utilisationProcess → prepareComModelForSync ──
        BNM->>Dev: monitorCharacteristicForService(FBDE0100/FBDE0104) [subscribe NOTIFY]
        Dev-->>BNM: CCCD activé
        BNM->>Dev: readCharacteristicForService(FBDE0100/FBDE0104) [STATUS read]
        Dev-->>BNM: status[1B]
        BNM->>BNM: receiveComModel → model mis à jour
    end

    BNM->>BNM: changeBleState(DeviceConnected)
    BNM-->>App: onDataChange.emit("change", deviceModel)
```
