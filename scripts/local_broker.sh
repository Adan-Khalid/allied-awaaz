#!/usr/bin/env bash
# Starts a throwaway Mosquitto with the repo's ACL and generated passwords.
# Usage: scripts/local_broker.sh <workdir> <port> <backend_pw> <device_pw>
set -euo pipefail
dir="$1"; port="$2"; bpw="$3"; dpw="$4"
root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$dir"
cp "$root/infra/mosquitto/acl" "$dir/acl"
rm -f "$dir/passwd"
mosquitto_passwd -b -c "$dir/passwd" awaaz-backend "$bpw" 2>/dev/null
mosquitto_passwd -b "$dir/passwd" awz-demo-001 "$dpw" 2>/dev/null
chmod 0644 "$dir/acl" "$dir/passwd"
chmod 0755 "$dir"
cat > "$dir/mosquitto.conf" <<CONF
listener $port 127.0.0.1
allow_anonymous false
password_file $dir/passwd
acl_file $dir/acl
persistence false
user $(id -un)
CONF
exec mosquitto -c "$dir/mosquitto.conf"
