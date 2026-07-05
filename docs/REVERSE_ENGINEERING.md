# REVERSE ENGINEERING / RETRO INGENIEURIE

L'analyse s'appuie sur une décompilation du code Hermes de l'appli Android "On.e".
Les éléments suivants sont déterminés par l'analyse de code manuelle et une assistance avec un LLM de codage.

**Un doute subsiste sur les valeurs des clés de chiffrement utilisées et sur la mécanique d'appairage.**

---

## Diagrammes de référence

### App Android (JS décompilé)
| Diagramme | Description |
|---|---|
| [01 — Activité globale](diagrams/js/01_activity_global.md) | États BLE, scan, modes normal vs appairage |
| [02 — Séquence appairage](diagrams/js/02_sequence_pairing.md) | `connectWithAssociation` : 5 étapes |
| [03 — Séquence connexion normale](diagrams/js/03_sequence_connection.md) | `connect` : sans associationProcess |
| [04 — Données en régime établi](diagrams/js/04_activity_steady_state.md) | NOTIFY FBDE0104, commandes CONTROLE |

### Implémentation Python (Raspi headless)
| Diagramme | Description |
|---|---|
| [01 — Activité globale](diagrams/python/01_activity_global.md) | `OneDaemon._acquisition_loop()`, ZMQ |
| [02 — Séquence appairage](diagrams/python/02_sequence_pairing.md) | `OneBLEClient.pair()` vs JS |
| [03 — Séquence connexion normale](diagrams/python/03_sequence_connection.md) | `connect_and_auth()` vs JS |
| [04 — Analyse des différences](diagrams/python/04_diff_analysis.md) | Tableau conformité + impact BT4 vs BT5 |

---

## UUIDs GATT

### Service système (auth)
| Caractéristique | UUID | Accès |
|---|---|---|
| Service | `fbde0000-4c7b-4e67-8292-a9b8e686cf87` | — |
| RANDOM_KEY | `fbde0001-4c7b-4e67-8292-a9b8e686cf87` | Read |
| SHARED_KEY | `fbde0002-4c7b-4e67-8292-a9b8e686cf87` | Read |
| ENCRYPT_KEY | `fbde0003-4c7b-4e67-8292-a9b8e686cf87` | Write |

### Service One (pompe + éclairage)
| Caractéristique | UUID | Accès |
|---|---|---|
| Service | `fbde0100-4c7b-4e67-8292-a9b8e686cf87` | — |
| CONTROLE | `fbde0101-4c7b-4e67-8292-a9b8e686cf87` | Write |
| FILTRATION | `fbde0102-4c7b-4e67-8292-a9b8e686cf87` | Read/Write |
| ECLAIRAGE | `fbde0103-4c7b-4e67-8292-a9b8e686cf87` | Read/Write |
| STATUS | `fbde0104-4c7b-4e67-8292-a9b8e686cf87` | Read/Notify (chiffré) |

### Services standard GATT
| Caractéristique | UUID | Usage |
|---|---|---|
| Model (2A24) | `00002a24-0000-1000-8000-00805f9b34fb` | Modèle (`ON.E`, etc.) |
| Serial (2A25) | `00002a25-0000-1000-8000-00805f9b34fb` | Numéro de série |
| Firmware (2A26) | `00002a26-0000-1000-8000-00805f9b34fb` | Version firmware |
| Current Time (2A08) | `00002a08-0000-1000-8000-00805f9b34fb` | Sync horloge |
| Day of Week (2A09) | `00002a09-0000-1000-8000-00805f9b34fb` | Sync jour semaine |

---

## Advertising BLE

Le module annonce deux UUID de service différents selon son mode :

| UUID annoncé | Mode |
|---|---|
| `fbde0100-...` | **Mode appairage** — bouton physique pressé sur le module |
| `fbde0000-...` | **Mode utilisation** — normal |

---

## Handshake d'authentification (applicatif)

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

## Bonding BLE (chiffrement couche BLE)

La caractéristique **STATUS (FBDE0104)** et le **service Time (2A08/2A09)** requièrent
un lien BLE chiffré (SMP bonding). Ce niveau de sécurité est distinct
de l’authentification applicative AES décrite ci-dessus.

**Confirmé par log (2026-07-05)** : sans bonding, les deux opérations retournent
`[org.bluez.Error.NotAuthorized] Operation Not Authorized` même après une AES auth réussie.

**Séquence correcte (implémentée dans `one_ble.py`) :**

1. `connect()` — connexion BLE bas niveau
2. `_authenticate()` — AES handshake (FBDE0001 → FBDE0003), **sans chiffrement**
3. `pair()` — bonding SMP (BlueZ ↔ module), **après** l’AES auth
4. `_sync_rtc()` — écriture 2A08/2A09, **maintenant autorisée**
5. `read_gatt_char(FBDE0104)` / `start_notify(FBDE0104)` — **maintenant autorisé**

**Pourquoi l’ordre est critique :** `pair()` appelé *avant* l’AES auth provoque
un `AuthenticationFailed` et une déconnexion immédiate.

**Comportement Android/iOS :** le SMP bonding est déclenché de façon transparente
par l’OS quand une caractéristique répond `Insufficient Encryption`.
BlueZ sur Linux/Raspi ne le fait pas automatiquement : `pair()` est explicite.

---

## Registre STATUS (FBDE0104)

Un seul octet, bitfield :

```
Bits [1:0]  → filtration_mode   (0=Manuel, 1=Horloge, 2=Auto)
Bit  [2]    → filtration_state  (0=arrêté, 1=en marche)
Bits [4:3]  → eclairage_mode    (0=Manuel, 1=Horloge, 2=Auto)
Bit  [5]    → eclairage_state   (0=éteint, 1=allumé)
Bit  [6]    → eclairage_type    (0 ou 1 selon type installé)
Bit  [7]    → réservé
```

Extraction Python (`one/one_ble.py`) :
```python
filtration_mode  = b & 0x03
filtration_state = (b >> 2) & 0x01
eclairage_mode   = (b >> 3) & 0x03
eclairage_state  = (b >> 5) & 0x01
eclairage_type   = (b >> 6) & 0x01
```

Extraction JS (`OneInterface.receiveComModel`) :
```js
filtrationModeFonctionnement = data.readUInt8(0) & 3
filtrationModeState          = data.readUInt8(0) >> 2 & 1
eclairageModeFonctionnement  = data.readUInt8(0) >> 3 & 3
eclairageModeState           = data.readUInt8(0) >> 5 & 1
eclairageType                = data.readUInt8(0) >> 6 & 1
```

> ✅ Les deux extractions sont rigoureusement identiques.

---

## Points ouverts / instabilités connues

| # | Problème | Hypothèse | Action |
|---|---|---|---|
| 1 | Appairage instable | `connect_and_auth()` ne relit pas FBDE0002 post-auth | **Fix #1 appliqué 2026-07-05** |
| 2 | `NotAuthorized` sur FBDE0104 et 2A08 | Confirmé : firmware exige SMP bonding | **Fix #2 appliqué 2026-07-05** |
| 3 | Clé privée PRIVATE_KEY | Extraite du binaire JS — supposée fixe pour tous les appareils | Confirmer avec un 2e appareil |
