#!/bin/sh
# Create deploy/secrets/ with restrictive permissions. Existing files are kept.
#   session_secret      random, generated here
#   wapt_password       password of the WAPT admin account (asked)
#   oidc_client_secret  random, generated here: give its hash to Authelia (printed at the end)
set -eu
cd "$(dirname "$0")"
umask 077
mkdir -p secrets

[ -s secrets/session_secret ] || head -c 48 /dev/urandom | base64 | tr -d '\n=' > secrets/session_secret

if [ ! -s secrets/wapt_password ]; then
    printf 'Mot de passe du compte admin WAPT : '
    stty -echo; read -r pw; stty echo; echo
    printf '%s' "$pw" > secrets/wapt_password
fi

new_client=0
# Created by authelia-register.sh when Authelia runs on this host
if [ ! -s secrets/oidc_client_secret ]; then
    head -c 48 /dev/urandom | base64 | tr -d '\n=/+' > secrets/oidc_client_secret
    new_client=1
fi

# The backend runs as uid 10001 and reads its secrets through bind mounts
if [ "$(id -u)" = 0 ]; then
    chown 10001:10001 secrets/session_secret secrets/wapt_password secrets/oidc_client_secret 2>/dev/null || true
    chmod 400 secrets/*
fi
ls -l secrets
if [ "$new_client" = 1 ]; then
    echo
    echo "Secret OIDC créé. Pour Authelia, générer son hash avec :"
    echo "  docker run --rm -i authelia/authelia:latest authelia crypto hash generate pbkdf2 --variant sha512 --password \"\$(cat secrets/oidc_client_secret)\""
    echo "puis le placer dans client_secret (voir deploy/authelia-client.yml)."
fi
