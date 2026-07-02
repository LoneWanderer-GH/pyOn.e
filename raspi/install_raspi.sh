#!/usr/bin/env bash
# =============================================================================
# install_one_raspi.sh — Installation du démon One BLE sur Raspberry Pi
# =============================================================================
# Usage :
#   sudo bash raspi/install_one_raspi.sh [BLE_ADDRESS]
#
# Ce script :
#   1. Installe les dépendances système (Python 3.9+, BlueZ, ZeroMQ)
#   2. Crée un virtualenv Python dans /opt/one/venv_one
#   3. Installe les paquets Python (one/requirements_daemon.txt)
#   4. Crée /etc/one/daemon.env avec l'adresse BLE
#   5. Installe et active le service systemd one-daemon.service
#
# Lancé depuis la racine du projet :
#   git clone ... && cd pyHackeron
#   sudo bash raspi/install_one_raspi.sh E7:4A:DB:3B:62:E5
#
# Testé sur Raspberry Pi OS Bullseye/Bookworm (Debian 11/12), Python 3.9+

set -euo pipefail

BLE_ADDRESS="${1:-}"
INSTALL_DIR="/opt/one"
VENV_DIR="$INSTALL_DIR/venv_one"
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="/etc/one"
SERVICE_NAME="one-daemon"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
RUN_USER="pi"   # adapter si l'utilisateur Pi est différent
LOG_LEVEL="INFO"

# ---------------------------------------------------------------------------
# Couleurs
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

# ---------------------------------------------------------------------------
# Vérifications
# ---------------------------------------------------------------------------
[[ $EUID -ne 0 ]] && error "Ce script doit être lancé en root (sudo)"

info "=== Installation One BLE Daemon ==="
info "Source      : $SRC_DIR"
info "Destination : $INSTALL_DIR"
[[ -n "$BLE_ADDRESS" ]] && info "Adresse BLE : $BLE_ADDRESS" \
    || warn "Adresse BLE non fournie — à renseigner manuellement dans $CONFIG_DIR/daemon.env"

# ---------------------------------------------------------------------------
# Dépendances système
# ---------------------------------------------------------------------------
info "Mise à jour des paquets système…"
apt-get update -qq

info "Installation des dépendances système…"
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    libzmq3-dev \
    bluetooth bluez \
    libglib2.0-dev \
    rsync

# Activer le service Bluetooth
systemctl enable bluetooth
systemctl start bluetooth

# ---------------------------------------------------------------------------
# Répertoire d'installation
# ---------------------------------------------------------------------------
mkdir -p "$INSTALL_DIR"
chown "$RUN_USER":"$RUN_USER" "$INSTALL_DIR"

info "Copie des sources vers $INSTALL_DIR…"
rsync -a --delete \
    --exclude='venv' --exclude='venv_one' \
    --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.git' --exclude='*.log' \
    "$SRC_DIR/" "$INSTALL_DIR/"
chown -R "$RUN_USER":"$RUN_USER" "$INSTALL_DIR"

# ---------------------------------------------------------------------------
# Virtualenv Python
# ---------------------------------------------------------------------------
info "Création du virtualenv dans $VENV_DIR…"
sudo -u "$RUN_USER" python3 -m venv "$VENV_DIR"

info "Mise à jour de pip…"
sudo -u "$RUN_USER" "$VENV_DIR/bin/pip" install --quiet --upgrade pip

info "Installation des dépendances Python (one/requirements_daemon.txt)…"
sudo -u "$RUN_USER" "$VENV_DIR/bin/pip" install --quiet \
    -r "$INSTALL_DIR/one/requirements_daemon.txt"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
info "Création de $CONFIG_DIR/daemon.env…"
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_DIR/daemon.env" <<EOF
# Configuration One BLE Daemon
# Généré par install_one_raspi.sh le $(date)
# Modifier puis : sudo systemctl restart one-daemon

# Adresse BLE du module One (obligatoire si pas de config JSON)
ONE_ADDRESS=${BLE_ADDRESS:-}

# Ports ZeroMQ
ONE_PUB_PORT=5560
ONE_CMD_PORT=5561

# Chemin de la config JSON (shared_key persistée lors de l'appairage)
ONE_CONFIG=/etc/one/one_daemon.json

# Intervalle de polling en secondes (défaut : 5.0)
ONE_POLL_INTERVAL=5.0

# Niveau de log : DEBUG | INFO | WARNING | ERROR
ONE_LOG_LEVEL=$LOG_LEVEL
EOF
chmod 600 "$CONFIG_DIR/daemon.env"
chown "$RUN_USER":"$RUN_USER" "$CONFIG_DIR/daemon.env"

# ---------------------------------------------------------------------------
# Service systemd
# ---------------------------------------------------------------------------
info "Installation du service systemd $SERVICE_NAME…"
cp "$SRC_DIR/raspi/one-daemon.service" "$SERVICE_FILE"

# Adapter l'utilisateur si différent de 'pi'
sed -i "s/^User=pi/User=$RUN_USER/" "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# ---------------------------------------------------------------------------
# Appairage initial (si adresse fournie)
# ---------------------------------------------------------------------------
if [[ -n "$BLE_ADDRESS" ]]; then
    info ""
    info "─── Appairage initial ───────────────────────────────────────"
    info "Appuyez sur le bouton physique du module One, puis appuyez"
    info "sur Entrée pour démarrer l'appairage…"
    read -r _
    sudo -u "$RUN_USER" "$VENV_DIR/bin/python" "$INSTALL_DIR/one_daemon.py" \
        --address "$BLE_ADDRESS" \
        --config "$CONFIG_DIR/one_daemon.json" \
        --pair-only \
        --log-level INFO \
    && info "Appairage réussi — shared_key sauvegardée dans $CONFIG_DIR/one_daemon.json" \
    || warn "Appairage échoué — relancer manuellement : sudo -u $RUN_USER $VENV_DIR/bin/python $INSTALL_DIR/one_daemon.py --pair-only"
fi

# ---------------------------------------------------------------------------
# Démarrage du service
# ---------------------------------------------------------------------------
info "Démarrage du service $SERVICE_NAME…"
systemctl start "$SERVICE_NAME"

# ---------------------------------------------------------------------------
# Résumé
# ---------------------------------------------------------------------------
sleep 2
STATUS=$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || true)
if [[ "$STATUS" == "active" ]]; then
    info "✓ Service $SERVICE_NAME démarré avec succès"
else
    warn "Service status : $STATUS"
    warn "Voir les logs : journalctl -fu $SERVICE_NAME"
fi

info ""
info "Commandes utiles :"
info "  sudo systemctl status  $SERVICE_NAME"
info "  sudo journalctl -fu    $SERVICE_NAME"
info "  sudo nano              $CONFIG_DIR/daemon.env"
info ""
info "Pour appairage manuel ultérieur :"
info "  sudo -u $RUN_USER $VENV_DIR/bin/python $INSTALL_DIR/one_daemon.py --pair-only"
