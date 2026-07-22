# Module On.e — WA Conception for connected pools (Reverse Engineering BLE)

French → see [README.md](./README.md)

Supervise and retro engineer a [**On.e** pool module](https://www.wa-conception.com/produit/module-on-e/) from de WA Conception.

[Architecture](#Architecture) headless daemon (Pi3) + web server (NAS) + HomeKit / MagicMirror integrations.

Help much needed.
State of reverse engineering → [see here](docs/REVERSE_ENGINEERING.md)

---

## State of project

| Component                         | State                                         |
|---------------------------------- |-----------------------------------------------|
| BLE Acquisition (bleak)           | 🚧 In progress: unsable pairing               |
| Headless daemon (ble_daemon.py)   | 🚧 In progress: doubts on public/private keys |
| ZMQ/JSON Network protocol         | ✅ Working                                    |
| Web dashboard (web_server.py)     | ✅ Working but not tested                     |
| MagicMirror² plugin               | ⏳ Not started yet                            |
| Homebridge / HomeKit plugin       | ⏳ Not started yet                            |
| systemd scripts for Pi3           | 🚧 In progress                                |
| systemd scripts for NAS Synology  | 🚧 In progress                                |


---
## Architecture

```
+--------------------------+                +--------------------------+
|  On.e module             |    Bluetooth   |  Raspberry Pi 3          |
|  pump, light             |<-------------->|  ble_daemon.py           |
|  Bluetooth               |   Low Energy   |  BLE . Decoder .         |
|                          |      (BLE)     |  :5560 PUB  :5561 PULL   |
+--------------------------+                +------------+-------------+
  mac address to find via                                | ZMQ SUBSCRIBE
  bluetooth device explorer                              v
  app (PC or phone)                           -> web_server.py  ->  http://nas:8080
  ex: "nRF Connect"                              Dashboard HTML  . /api/state . /api/stream (SSE)
                                              -> MagicMirror2
                                              -> Homebridge / HomeKit -> iPhone HomeKit
```

---

## Quick start


### Installation

```bash
# exemple raspi 3
pip install bleak pycryptodome pyzmq
```
or

```bash
# exemple raspi 3
pip install -r one/requirements_daemon.txt
```

### Initial pairing

! TO BE CONFIRMED  !

```bash
# exemple raspi 3
# Push 3s on module One button, then :
python one_daemon.py --pair-only
```

`shared_key` and BLE address are saved in
`~/.config/one_daemon.json`.

### Normal start

```bash
python one_daemon.py
```

Or with explicit parameters:
! TO BE CONFIRMED !
```bash
python one_daemon.py --address AA:BB:CC:DD:EE:FF --log-level DEBUG
```



---

## Documentation

| Topic | File |
|---|---|
| TODO | TODO |
|---|---|


Files :
- `./one/one_ble.py` — BLE library (scan, pairing, connection, status reading)
- `./ble_daemon.py` — headless ZMQ deamon (project root)


---

### Published ZMQ topics (port 5560)

| Topic             | JSON content                                       |
|-------------------|----------------------------------------------------|
| `one/connection`  | `{"connected": true/false, "address": "..."}`      |
| `one/status`      | Snapshot complet (voir ci-dessous)                 |
| `one/pump/mode`   | `{"value": 0/1/2, "label": "Manuel/Horloge/Auto"}` |
| `one/pump/state`  | `{"value": 0/1}`                                   |
| `one/light/mode`  | `{"value": 0/1/2, "label": "Manuel/Horloge/Auto"}` |
| `one/light/state` | `{"value": 0/1}`                                   |

Exemple `one/status` :
```json
{
  "filtration_mode": 1,
  "filtration_mode_label": "Horloge",
  "filtration_state": 1,
  "eclairage_mode": 0,
  "eclairage_mode_label": "Manuel",
  "eclairage_state": 0,
  "eclairage_type": 0
}
```

### Commandes ZMQ (port 5561)

| Topic           | Effect                                              |
|-----------------|-----------------------------------------------------|
| `one/cmd/retry` | Forces immediate reconnection attempt               |
| `one/cmd/pair`  | Triggers pairing (module On.e push button required) |

---

## Coexistence with project [pyHackeron](https://github.com/LoneWanderer-GH/pyHackeron/)

| Project                           | Daemon          | PUB  | CMD  | Préfixe topics |
|---------------------------------  |-----------------|------|------|----------------|
| pyHackeron (régulateur Corelec)   | `ble_daemon.py` | 5555 | 5556 | `corelec/`     |
| pyOn.e (module One WA Conception) | `ble_daemon.py` | 5560 | 5561 | `one/`         |

Both deamons can run simultaneously on a raspberry pi — BlueZ handles the BLE adapter.

---

## Licence

MIT [LICENSE](LICENSE)

