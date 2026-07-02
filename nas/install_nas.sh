#!/usr/bin/env bash
# =============================================================================
# install_one_nas.sh — Installation du serveur web One sur NAS Synology DSM 7
# =============================================================================
# Usage :
#   bash nas/install_one_nas.sh <DAEMON_IP> [HTTP_PORT]
#
#   DAEMON_IP  : IP du Raspberry Pi qui exécute one_daemon.py
#   HTTP_PORT  : port HTTP du serveur web (défaut : 8081)
#
# Exemples :
#   bash nas/install_one_nas.sh 192.168.0.16
#   bash nas/install_one_nas.sh 192.168.0.16 8081
#
# Prérequis sur le NAS :
#   - DSM 7.x
#   - Python 3 installé via Synology Package Center
#     (paquet "Python 3.11" ou via SynoCommunity)
#   - Accès SSH activé (Panneau de config → Terminal & SNMP → Terminal)
#
# Ce script :
#   1. Crée /volume1/one/ et copie les sources
#   2. Crée un virtualenv Python et installe flask + pyzmq
#   3. Écrit /etc/one/web.env (IP du Pi, ports)
#   4. Crée un utilisateur système one-web (si absent)
#   5. Installe le service systemd dans /usr/local/lib/systemd/system/
#      (emplacement persistant aux mises à jour DSM)
#   6. Active et démarre le service

set -euo pipefail

DAEMON_IP="${1:-}"
HTTP_PORT="${2:-8081}"

[[ -z "$DAEMON_IP" ]] && { echo "Usage : $0 <DAEMON_IP> [HTTP_PORT]"; exit 1; }

INSTALL_DIR="/volume1/one"
VENV_DIR="$INSTALL_DIR/venv_one_web"
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="/etc/one"
SERVICE_NAME="one-web"
SERVICE_USER="one-web"
SERVICE_DIR="/usr/local/lib/systemd/system"
SERVICE_FILE="$SERVICE_DIR/${SERVICE_NAME}.service"

# ---------------------------------------------------------------------------
# Couleurs
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

# ---------------------------------------------------------------------------
# Vérifications préliminaires
# ---------------------------------------------------------------------------
[[ $EUID -ne 0 ]] && error "Ce script doit être lancé en root (sudo)"

info "=== Installation One Web Server ==="
info "Daemon IP : $DAEMON_IP"
info "HTTP port : $HTTP_PORT"
info "Sources   : $SRC_DIR"

# Trouver Python 3 sur le NAS
PYTHON3=""
for candidate in \
    /usr/local/bin/python3.12 \
    /usr/local/bin/python3.11 \
    /usr/local/bin/python3.10 \
    /usr/local/bin/python3.9  \
    /usr/bin/python3; do
    if "$candidate" --version &>/dev/null 2>&1; then
        PYTHON3="$candidate"
        break
    fi
done
[[ -z "$PYTHON3" ]] && error "Python 3 introuvable. Installez-le via Synology Package Center."
info "Python trouvé : $PYTHON3 ($($PYTHON3 --version))"

# ---------------------------------------------------------------------------
# Répertoire d'installation
# ---------------------------------------------------------------------------
info "Création de $INSTALL_DIR…"
mkdir -p "$INSTALL_DIR"

info "Copie des sources vers $INSTALL_DIR…"
rsync -a --delete \
    --exclude='venv' --exclude='venv_one' --exclude='venv_one_web' \
    --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.git' --exclude='*.log' \
    "$SRC_DIR/" "$INSTALL_DIR/"

# ---------------------------------------------------------------------------
# Virtualenv Python
# ---------------------------------------------------------------------------
if [[ ! -d "$VENV_DIR" ]]; then
    info "Création du virtualenv dans $VENV_DIR…"
    "$PYTHON3" -m venv "$VENV_DIR"
fi

info "Mise à jour de pip…"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip

info "Installation des dépendances Python (one/requirements_web.txt)…"
"$VENV_DIR/bin/pip" install --quiet \
    -r "$INSTALL_DIR/one/requirements_web.txt"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
info "Création de $CONFIG_DIR/web.env…"
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_DIR/web.env" <<EOF
# Configuration One Web Server
# Généré par install_one_nas.sh le $(date)
# Modifier puis : sudo systemctl restart one-web

# IP du Raspberry Pi exécutant one_daemon.py
ONE_HOST=$DAEMON_IP

# Port ZMQ PUB du daemon BLE (doit correspondre à ONE_PUB_PORT sur le Pi)
ONE_PUB_PORT=5560

# Port HTTP du serveur web One (accessible sur le LAN)
ONE_WEB_PORT=$HTTP_PORT

# Niveau de log : DEBUG | INFO | WARNING | ERROR
ONE_LOG_LEVEL=INFO
EOF
chmod 600 "$CONFIG_DIR/web.env"

# ---------------------------------------------------------------------------
# Utilisateur dédié
# ---------------------------------------------------------------------------
if ! id -u "$SERVICE_USER" &>/dev/null 2>&1; then
    info "Création de l'utilisateur système $SERVICE_USER…"
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER" \
        || warn "Impossible de créer l'utilisateur $SERVICE_USER automatiquement." \
                "Sur Synology, le créer manuellement via Panneau de config → Utilisateur."
fi

info "Attribution des permissions à $SERVICE_USER…"
chown -R "$SERVICE_USER":http "$INSTALL_DIR" 2>/dev/null || \
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"
chown "$SERVICE_USER":"$SERVICE_USER" "$CONFIG_DIR/web.env" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Service systemd
# ---------------------------------------------------------------------------
info "Installation du service systemd $SERVICE_NAME…"
mkdir -p "$SERVICE_DIR"
cp "$SRC_DIR/nas/one-web.service" "$SERVICE_FILE"

# Adapter si le user a un nom différent
sed -i "s/^User=one-web/User=$SERVICE_USER/" "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

# ---------------------------------------------------------------------------
# Résumé
# ---------------------------------------------------------------------------
sleep 2
STATUS=$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || true)
if [[ "$STATUS" == "active" ]]; then
    info "✓ Service $SERVICE_NAME démarré avec succès"
    info "  Dashboard : http://$(hostname -I | awk '{print $1}'):$HTTP_PORT"
else
    warn "Service status : $STATUS"
    warn "Voir les logs : journalctl -fu $SERVICE_NAME"
fi

info ""
info "Commandes utiles :"
info "  sudo systemctl status  $SERVICE_NAME"
info "  sudo journalctl -fu    $SERVICE_NAME"
info "  sudo nano              $CONFIG_DIR/web.env"
info ""
info "Pour mettre à jour les sources :"
info "  bash $SRC_DIR/nas/install_one_nas.sh $DAEMON_IP $HTTP_PORT"
