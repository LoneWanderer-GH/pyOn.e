# Module One — WA Conception (Reverse Engineering BLE)

Supervision et rétro-ingénierie d'un module **One** de WA Conception (contrôleur piscine pompe + éclairage) via BLE.  
Architecture daemon headless (Pi3) + serveur web + intégrations HomeKit / MagicMirror.

Web UI:
<img src="docs/img/web_ui.png" alt="drawing" style="width:350px;"/>

Etat du reverse engineering → [voir ici](docs\REVERSE_ENGINEERING.md)

---

## État du projet

| Composant                         | État                                          |
|---------------------------------- |-----------------------------------------------|
| Acquisition BLE (bleak)           | 🚧 En cours: appairage instable              |
| Daemon headless (ble_daemon.py)   | 🚧 En cours: problème de clé publique/privée |
| Protocole réseau ZMQ/JSON         | ✅ Fonctionnel                               |
| Dashboard web (web_server.py)     | ✅ Fonctionnel (non testé)                   |
| Plugin MagicMirror²               | ⏳ Non démarré                               |
| Plugin Homebridge / HomeKit       | ⏳ Non démarré                               |
| Scripts systemd Pi3               | 🚧 En cours                                  |
| Scripts systemd NAS Synology      | 🚧 En cours                                  |


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

## Démarrage rapide


### Installation

```bash
# exemple raspi 3
pip install bleak pycryptodome pyzmq
```
ou

```bash
# exemple raspi 3
pip install -r one/requirements_daemon.txt
```

### Appairage initial

! A CONFIRMER  !

```bash
# exemple raspi 3
# Appuyer 3s sur le bouton du module One, puis :
python one_daemon.py --pair-only
```

La `shared_key` et l'adresse BLE sont sauvegardées dans
`~/.config/one_daemon.json`.

### Démarrage normal

```bash
python one_daemon.py
```

Ou avec paramètres explicites :
! A CONFIRMER  !
```bash
python one_daemon.py --address E7:4A:DB:3B:62:E5 --log-level DEBUG
```



---

## Documentation

| Sujet | Fichier |
|---|---|
| TODO | TODO |
|---|---|


Fichiers :
- `one/one_ble.py` — bibliothèque BLE (scan, appairage, connexion, lecture statut)
- `ble_daemon.py` — démon ZMQ headless (à la racine du projet)




---

### Topics ZMQ publiés (port 5560)

| Topic | Contenu JSON |
|---|---|
| `one/connection` | `{"connected": true/false, "address": "..."}` |
| `one/status` | Snapshot complet (voir ci-dessous) |
| `one/pump/mode` | `{"value": 0/1/2, "label": "Manuel/Horloge/Auto"}` |
| `one/pump/state` | `{"value": 0/1}` |
| `one/light/mode` | `{"value": 0/1/2, "label": "Manuel/Horloge/Auto"}` |
| `one/light/state` | `{"value": 0/1}` |

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

| Topic | Effet |
|---|---|
| `one/cmd/retry` | Force une tentative de reconnexion immédiate |
| `one/cmd/pair` | Déclenche un appairage (bouton module requis) |

---

## Coexistence avec pyHackeron

| Projet                            | Démon           | PUB  | CMD  | Préfixe topics |
|---------------------------------  |-----------------|------|------|----------------|
| pyHackeron (régulateur Corelec)   | `ble_daemon.py` | 5555 | 5556 | `corelec/`     |
| pyOn.e (module One WA Conception) | `ble_daemon.py` | 5560 | 5561 | `one/`         |

Les deux démons peuvent tourner simultanément sur un raspberry pi — BlueZ gère l'adaptateur BLE.




---

## Licence

MIT [LICENSE](LICENSE)

