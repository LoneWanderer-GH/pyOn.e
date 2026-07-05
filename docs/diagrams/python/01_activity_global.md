# Python — Activité globale (ble_daemon.py)

> Source : `ble_daemon.py` — classe `OneDaemon._acquisition_loop()`  
> Comparaison JS : [01_activity_global.md](../js/01_activity_global.md)

```mermaid
flowchart TD
    START([ble_daemon.py démarre]) --> CFG[Charger config JSON\n~/.config/one_daemon.json\naddress + shared_key]
    CFG --> MODE{--pair\nou one/cmd/pair ?}

    MODE -- Oui --> SCAN_P["scan_for_pairing(timeout=30s)\nBleakScanner\nfiltre ADV_UUID_PAIR=FBDE0100\narrêt au 1er trouvé ⚠️"]
    SCAN_P --> FOUND_P{Module trouvé ?}
    FOUND_P -- Non --> PUBERR[ZMQ PUB\none/connection error]
    FOUND_P -- Oui --> PAIR_PROC[OneBLEClient.pair\nsee sequence_pairing.md]
    PAIR_PROC --> SAVE["save_config<br/>shared_key.hex() sauvegardé"]
    SAVE --> POST_PAIR[Session post-appairage\nread_status + subscribe]
    POST_PAIR --> LOOP

    MODE -- Non --> LOOP[_acquisition_loop\nretry=0]
    LOOP --> SESS[_session retry]
    SESS --> CONN_AUTH[connect_and_auth\nsee sequence_connection.md]
    CONN_AUTH -- OK --> SUB[subscribe_status\nread_status best-effort]
    SUB --> MAINTAIN["Boucle maintien\nattente _retry_event (5s)\nou is_connected=False"]
    MAINTAIN -- "_retry_event set\nou déconnexion" --> DISC[disconnect]
    DISC --> BACKOFF["Backoff exponentiel\n3s + 2×retry\nmax 60s"]
    BACKOFF --> LOOP

    CONN_AUTH -- Erreur --> PUBERR2[ZMQ PUB\none/connection error]
    PUBERR2 --> DISC

    subgraph ZMQ_CMD["ZMQ PULL :5561 — commandes entrantes"]
        CMD1["one/cmd/retry : _retry_event.set"]
        CMD2["one/cmd/pair : _pair_event.set"]
    end

    subgraph ZMQ_PUB["ZMQ PUB :5560 — publications"]
        PUB1[one/connection\none/status\none/pump/mode\none/pump/state\none/light/mode\none/light/state]
    end

    MAINTAIN --> ZMQ_PUB

    %% Différences vs JS
    style SCAN_P fill:#fff3cd,stroke:#ffc107
    note1["⚠️ Différence JS : JS scan continu\nallowDuplicates + parse ADV data.\nPython : arrêt immédiat 1er trouvé,\npas de parse ADV data en continu"]
    SCAN_P -.-> note1
```

### Différences notables vs JS
| Point | JS | Python |
|---|---|---|
| Scan arrière-plan | Continu, parse ADV data → status sans connexion | Absent — statut uniquement via connexion GATT |
| Arrêt scan appairage | Timeout ou 1er trouvé | 1er trouvé (event set) ✅ conforme |
| Reconnexion | `reset()` → relance immédiate | Backoff exponentiel 3–60s |
| Publication état | `onDataChange.emit` → UI | ZMQ PUB → web_server, homebridge, etc. |
