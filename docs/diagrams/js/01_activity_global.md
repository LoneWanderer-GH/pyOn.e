# JS — Activité globale (Android app)

> Source : `one/decompiled_js/Bluetooth/BleNetworkManager.js`  
> Référence : `BleNetworkState = { Nothing, Scanning, DeviceInAssociationProcess, DeviceInConnectionProcess, DeviceConnected }`

```mermaid
flowchart TD
    START([App démarre]) --> PERM[Demande permissions BLE + Location]
    PERM --> BTCHECK{BT allumé ?}
    BTCHECK -- Non --> BTERR[État: InError\nonServiceStateChange.emit]
    BTCHECK -- Oui --> SCAN

    subgraph SCAN_ADV["startAdvertisingScan — scan continu en arrière-plan"]
        SCAN[startDeviceScan\nFBDE0000 + FBDE0100\nScanMode.LowLatency\nallowDuplicates: true] --> FOUND{Device connu\ndans _scanDevicesHistory ?}
        FOUND -- Oui + serviceData --> ADVDATA["receiveAdvertisingData<br/>parser octet 0 : status<br/>bits: filtration + éclairage<br/>état InProximity"]
        ADVDATA --> EMIT_ADV["onDataChange.emit<br/>UI mise à jour<br/>sans connexion"]
    end

    SCAN_ADV --> CONNECT_CHOICE{Action utilisateur}
    CONNECT_CHOICE -- "Premier appairage\n(bouton module pressé)" --> SCAN_PAIR[scanForAppairage\nstartDeviceScan FBDE0100\nLowLatency]
    SCAN_PAIR --> ASSOC[connectWithAssociation]
    CONNECT_CHOICE -- "Connexion normale\n(shared_key connue)" --> CONN[connect]

    ASSOC --> CONN_OK([DeviceConnected])
    CONN --> CONN_OK
```
