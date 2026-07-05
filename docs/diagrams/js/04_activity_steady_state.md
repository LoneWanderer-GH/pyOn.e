# JS — Activité données en régime établi

> Source : `one/decompiled_js/Bluetooth/BleNetworkManager.js` — `askDataSubscribe`, `askDataWrite`  
> Source : `one/decompiled_js/One/One/OneInterface.js` — `receiveComModel`, `prepareControl`

```mermaid
flowchart TD
    CONN_OK([État: DeviceConnected]) --> PARALLEL

    subgraph PARALLEL["Deux flux parallèles"]
        direction LR
        subgraph NOTIFY["Flux NOTIFY — réception passive"]
            N1[Réception NOTIFY\nFBDE0104\n1 octet] --> N2["receiveComModel(deviceModel, data):\nbits 0-1: filtrationModeFonctionnement\nbit  2:   filtrationModeState\nbits 3-4: eclairageModeFonctionnement\nbit  5:   eclairageModeState\nbit  6:   eclairageType"]
            N2 --> N3[onDataChange.emit\n→ UI re-render]
            N3 --> N1
        end

        subgraph ADV["Flux ADV — status sans connexion"]
            A1[Réception ADV packet\nFBDE0000 + serviceData] --> A2[receiveAdvertisingData\nmême décodage octet 0\n→ InProximity]
            A2 --> A3[onDataChange.emit]
        end
    end

    subgraph CMD["Commandes utilisateur → écriture GATT"]
        C1([Action UI:\nPompe ON/OFF\nLumière ON/OFF\nMode]) --> C2["prepareControl(eclairageState,\nfiltrationState, modes)\n→ octet CONTROLE\nbits: [ec_state|fi_state|ec_mode|fi_mode]"]
        C2 --> C3["askDataWrite\nwriteCharacteristicWithResponse\nFBDE0101 (CONTROLE)"]
        C3 --> DEV[Module On.e\nactualise STATUS]
        DEV --> N1
    end
```
