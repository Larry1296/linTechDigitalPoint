#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 DigitalOcean Droplet. Run as root:
#   ssh root@YOUR_DROPLET_IP 'bash -s' < deploy/server-setup.sh
# It installs Docker, opens only SSH and the web ports, adds swap, and creates the "deploy" user GitHub signs in as
# (with the same SSH keys root has). Safe to run again.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then echo "Run this as root."; exit 1; fi

echo "== Updates and basics"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -yq
apt-get install -yq ca-certificates curl ufw unattended-upgrades fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "== Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
# Keep container logs from filling the disk.
cat > /etc/docker/daemon.json <<'JSON'
{ "log-driver": "json-file", "log-opts": { "max-size": "20m", "max-file": "5" } }
JSON
systemctl restart docker

echo "== Firewall: SSH, http and https only"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "== Swap (2 GB), so a small Droplet copes with busy moments"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== Time zone"
timedatectl set-timezone Africa/Nairobi

echo "== The deploy user"
if ! id deploy >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" deploy
fi
usermod -aG docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
if [ -f /root/.ssh/authorized_keys ]; then
  cat /root/.ssh/authorized_keys >> /home/deploy/.ssh/authorized_keys
  sort -u -o /home/deploy/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
  chown deploy:deploy /home/deploy/.ssh/authorized_keys
  chmod 600 /home/deploy/.ssh/authorized_keys
fi
install -d -o deploy -g deploy /opt/lintech

echo
echo "Done. Next (see docs/deployment.md):"
echo "  1. Add the GitHub deploy key's public half to /home/deploy/.ssh/authorized_keys"
echo "  2. Put the filled-in .env at /opt/lintech/.env (owned by deploy, chmod 600)"
echo "  3. Run the Deploy workflow on GitHub"
