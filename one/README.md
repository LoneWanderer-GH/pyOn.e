# Module One — WA Conception (Reverse Engineering BLE)

Bibliothèque Python 3 + démon headless pour le module **One** de WA Conception
(contrôleur piscine pompe + éclairage).

Fichiers :
- `one_ble.py` — bibliothèque BLE (scan, appairage, connexion, lecture statut)
- `../one_daemon.py` — démon ZMQ headless (à la racine du projet)

---

### UUIDs GATT

#### Service système (auth)
| Caractéristique | UUID | Accès |
|---|---|---|
| Service | `fbde0000-4c7b-4e67-8292-a9b8e686cf87` | — |
| RANDOM_KEY | `fbde0001-4c7b-4e67-8292-a9b8e686cf87` | Read |
| SHARED_KEY | `fbde0002-4c7b-4e67-8292-a9b8e686cf87` | Read |
| ENCRYPT_KEY | `fbde0003-4c7b-4e67-8292-a9b8e686cf87` | Write |

#### Service One (pompe + éclairage)
| Caractéristique | UUID | Accès |
|---|---|---|
| Service | `fbde0100-4c7b-4e67-8292-a9b8e686cf87` | — |
| CONTROLE | `fbde0101-4c7b-4e67-8292-a9b8e686cf87` | Write |
| FILTRATION | `fbde0102-4c7b-4e67-8292-a9b8e686cf87` | Read/Write |
| ECLAIRAGE | `fbde0103-4c7b-4e67-8292-a9b8e686cf87` | Read/Write |
| STATUS | `fbde0104-4c7b-4e67-8292-a9b8e686cf87` | Read/Notify (chiffré) |

#### Services standard GATT
| Caractéristique | UUID | Usage |
|---|---|---|
| Model (2A24) | `00002a24-0000-1000-8000-00805f9b34fb` | Modèle (`ON.E`, etc.) |
| Serial (2A25) | `00002a25-0000-1000-8000-00805f9b34fb` | Numéro de série |
| Firmware (2A26) | `00002a26-0000-1000-8000-00805f9b34fb` | Version firmware |
| Current Time (2A08) | `00002a08-0000-1000-8000-00805f9b34fb` | Sync horloge |
| Day of Week (2A09) | `00002a09-0000-1000-8000-00805f9b34fb` | Sync jour semaine |

---

### Advertising BLE

Le module annonce deux UUID de service différents selon son mode :

| UUID annoncé | Mode |
|---|---|
| `fbde0100-...` | **Mode appairage** — bouton physique pressé sur le module |
| `fbde0000-...` | **Mode utilisation** — normal |

---

### Handshake d'authentification (applicatif)

Exécuté à **chaque connexion**, avant toute lecture/écriture des caractéristiques
du service One.

```
1. Lire FBDE0001 (RANDOM_KEY)  → 16 octets bruts
   random_key = reversed(raw_FBDE0001)

2. Lire FBDE0002 (SHARED_KEY)  → 16 octets bruts  (seulement lors de l'appairage)
   shared_key = reversed(raw_FBDE0002)

3. Calculer la réponse :
   plaintext  = shared_key (16 B) + random_key (16 B)   → 32 octets
   ciphertext = AES-128-ECB( PRIVATE_KEY, plaintext )   → 32 octets
   response   = reversed(ciphertext)                     → 32 octets

4. Écrire FBDE0003 (ENCRYPT_KEY) ← response
```

**Clé privée fixe** (extraite du binaire JS) :
```
1141a80537444a6a85888d84115f2811
```

---

### Bonding BLE (chiffrement couche BLE)

La caractéristique **STATUS (FBDE0104)** requiert un lien BLE chiffré
(propriété `Encrypted Read/Notify`). Ce niveau de sécurité est distinct
de l'authentification applicative AES décrite ci-dessus.

**Séquence complète pour un premier appairage :**

1. Appuyer sur le bouton physique du module (→ module en mode `FBDE0100`)
2. Se connecter et effectuer le handshake AES applicatif
3. Appeler `client.pair()` (BlueZ ↔ module : échange de clés BLE, création du bond)
4. Stocker `shared_key` pour les reconnexions futures

**Reconnexions suivantes :**

- BlueZ réutilise automatiquement le bond stocké → lien chiffré dès le `connect()`
- Effectuer uniquement le handshake AES applicatif (FBDE0001→FBDE0003)
- **Ne pas rappeler `pair()`** : cela provoque un re-connect BlueZ interne qui
  efface le cache de service-discovery de bleak, causant l'erreur
  `"Service Discovery has not been performed yet"`

---

### Registre STATUS (FBDE0104)

Un seul octet, bitfield :

```
Bits [1:0]  → filtration_mode   (0=Manuel, 1=Horloge, 2=Auto)
Bit  [2]    → filtration_state  (0=arrêté, 1=en marche)
Bits [4:3]  → eclairage_mode    (0=Manuel, 1=Horloge, 2=Auto)
Bit  [5]    → eclairage_state   (0=éteint, 1=allumé)
Bit  [6]    → eclairage_type    (0 ou 1 selon type installé)
Bit  [7]    → réservé
```

---

## Installation

```bash
pip install bleak pycryptodome pyzmq
```

---

## Appairage initial

```bash
# Appuyer sur le bouton du module One, puis :
python one_daemon.py --pair-only
```

La `shared_key` et l'adresse BLE sont sauvegardées dans
`~/.config/one_daemon.json`.

---

## Démarrage normal

```bash
python one_daemon.py
```

Ou avec paramètres explicites :

```bash
python one_daemon.py --address E7:4A:DB:3B:62:E5 --log-level DEBUG
```

---

## Topics ZMQ publiés (port 5560)

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

## Commandes ZMQ (port 5561)

| Topic | Effet |
|---|---|
| `one/cmd/retry` | Force une tentative de reconnexion immédiate |
| `one/cmd/pair` | Déclenche un appairage (bouton module requis) |

---

## Coexistence avec ble_daemon.py

| Démon | PUB | CMD | Préfixe topics |
|---|---|---|---|
| `ble_daemon.py` (régulateur Corelec) | 5555 | 5556 | `corelec/` |
| `one_daemon.py` (module One) | 5560 | 5561 | `one/` |

Les deux démons peuvent tourner simultanément — BlueZ gère l'adaptateur BLE.

