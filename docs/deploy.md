# Déploiement

La console tourne en deux conteneurs, décrits dans `deploy/docker-compose.yml` :

| Service | Rôle | Exposé |
|---|---|---|
| `frontend` | nginx non privilégié : interface (SPA) et proxy de `/api` et `/auth` vers le backend | `127.0.0.1:8085` uniquement |
| `backend` | FastAPI : session, OIDC, client WAPT, signature (`waptpython` de l'agent 2.7) | non, réseau Docker seulement |

Chaîne de requêtes, exemple d'une installation réelle :

```
navigateur ──TLS──▶ proxy.example.org ──▶ nginx de docker.example.org ──▶ frontend:8080 ──▶ backend:8000 ──▶ wapt.example.org
                    (terminaison TLS)   (vhost de la console)                          (URL publique)
```

## 1. Nom d'hôte

Prévoir un nom dédié, par exemple `wapt-console.example.org`. Un chemin sous un site existant (`/wapt`) compliquerait les cookies et les URL de l'interface. Le nom doit pointer vers proxy.example.org, qui relaie au nginx de docker.example.org.

## 2. Secrets et configuration

```bash
cd deploy
cp .env.example .env          # WWC_PUBLIC_URL, WWC_WAPT_URL, WWC_OIDC_ISSUER
./init-secrets.sh             # secrets/ en 600 : session, mot de passe admin WAPT, secret OIDC
```

`init-secrets.sh` affiche la commande qui calcule le hash du secret OIDC pour Authelia. Aucun secret ne passe par une variable d'environnement ni par l'image. Chacun est monté en lecture seule dans `/run/secrets/`.

### Clé de signature

Par défaut, **aucune clé n'est stockée sur le serveur**. Pour déverrouiller la signature, chaque opérateur choisit, sur son appareil, sa clé privée **chiffrée** (`.pem`) et son certificat (`.crt`), puis saisit la passphrase. Le serveur garde la clé en mémoire, dans un processus de signature propre à la session, pendant `WWC_SIGNER_UNLOCK_MINUTES` (30 par défaut). Rien n'est écrit sur disque et la passphrase n'est pas conservée. À l'expiration ou au verrouillage, le processus s'arrête et la clé disparaît. Une clé non chiffrée est refusée.

Chaque opérateur peut ainsi utiliser sa propre clé. Les agents n'acceptent toutefois que les signatures des certificats auxquels ils font confiance : un nouveau certificat doit être déployé sur les agents avant usage. Le journal indique quel certificat a signé chaque action.

Pour garder malgré tout une clé sur le serveur, déverrouillable avec la seule passphrase, voir `docker-compose.override.example.yml`.

### Store Tranquil IT

Le backend doit pouvoir joindre `https://wapt.tranquil.it` (index du store, paquets, icônes). Réglages facultatifs dans `.env` :

| Variable | Défaut | Rôle |
|---|---|---|
| `WWC_STORE_URL` | `https://wapt.tranquil.it/wapt` | Store (ou un miroir) |
| `WWC_STORE_PREFIX` | `tis` | Préfixe des paquets du store |
| `WWC_REPO_PREFIX` | préfixe le plus fréquent du dépôt | Préfixe donné aux paquets importés |
| `WWC_STORE_TRUSTED_FINGERPRINTS` | certificat Tranquil IT | Empreintes SHA-256 (liste JSON) des certificats acceptés pour vérifier les paquets du store |

L'index (17 Mo) est conservé dans le volume de données et relu toutes les 6 heures au plus, par requête conditionnelle.

## 3. Authelia

Si Authelia tourne en conteneur sur le même hôte avec une configuration en fichiers, `deploy/authelia-register.sh` fait tout, en root :
- sauvegarde de la configuration et du fichier des utilisateurs ;
- secret client généré par Authelia et écrit dans `secrets/oidc_client_secret`, sans jamais l'afficher ;
- ajout du client et du groupe de l'utilisateur ;
- validation de la configuration (les sauvegardes sont restaurées si elle est refusée), puis redémarrage d'Authelia.

```bash
sudo deploy/authelia-register.sh --config /chemin/configuration.yml --redirect https://<nom>/auth/callback \
  --secret-out deploy/secrets/oidc_client_secret --users /chemin/users_database.yml --user <login> --group wapt-admins
```

Sinon, ajouter à la main le client de `deploy/authelia-client.yml` à `identity_providers.oidc.clients` :
- `redirect_uris` : `https://<nom de la console>/auth/callback` ;
- `client_secret` : le hash obtenu à l'étape 2.

Créer ensuite les groupes et y placer les utilisateurs :

| Groupe | Rôle dans la console |
|---|---|
| `wapt-viewers` | lecture seule |
| `wapt-operators` | actions à distance (update, upgrade, Wake-on-LAN…) |
| `wapt-admins` | affectations, groupes, dépôt, import du store |

Un utilisateur sans aucun de ces groupes est refusé après la connexion. Les noms sont modifiables par `WWC_ROLE_GROUPS` (JSON) dans `.env`.

## 4. Reverse proxies

- **Reverse proxy sur le même hôte** : reprendre `deploy/nginx-host.conf` (nom d'hôte, port `WWC_PORT`), le frontend restant sur `127.0.0.1`.
- **Reverse proxy sur une autre machine**, comme proxy.example.org qui joint directement les ports de docker.example.org : publier le frontend sur l'adresse du réseau interne (`WWC_BIND=10.0.0.40`, par exemple) et ne pas l'exposer ailleurs.
- **proxy.example.org** doit transmettre :
  - `X-Forwarded-For` et `X-Forwarded-Proto: https`, pour que le backend pose des cookies `Secure`, construise la bonne URL de retour OIDC et journalise la vraie IP ;
  - la montée en WebSocket (`Upgrade`, `Connection`), utilisée à partir de la v0.3 ;
  - des corps de requête de plusieurs centaines de Mo (`client_max_body_size`), pour l'upload de paquets en v0.6.

## 5. Réseau sans « hairpin NAT »

Si l'IP publique du reverse proxy n'est pas joignable depuis le réseau interne, le backend ne peut pas atteindre le serveur WAPT ni le fournisseur OIDC par leur nom public (`Connection refused` dans les journaux, erreur 500 sur `/auth/login`). Copier `docker-compose.override.example.yml` en `docker-compose.override.yml` et y faire pointer ces noms vers l'adresse interne du reverse proxy. Les URL restent publiques et les certificats valides.

## 6. Démarrage

```bash
docker compose up -d --build
docker compose ps                          # backend « healthy », puis frontend
curl -s http://127.0.0.1:8085/api/health   # {"status":"ok",...}
```

Ouvrir ensuite `https://<nom de la console>/` : redirection vers Authelia, puis retour sur le tableau de bord.

## Durcissement appliqué

- Conteneurs en système de fichiers **lecture seule** (`/tmp` en tmpfs), toutes les capabilities retirées, `no-new-privileges`, utilisateurs non root.
- Backend non publié ; il ne fait confiance aux en-têtes `X-Forwarded-*` que parce qu'il n'est joignable que par le frontend.
- Cookie de session `HttpOnly`, `Secure` derrière HTTPS, `SameSite=Lax` (nécessaire au retour d'Authelia), jeton CSRF exigé sur toute requête qui modifie l'état, durée de vie absolue de 8 h.
- CSP stricte (`default-src 'self'`, pas de script inline), `nosniff`, `frame-ancestors 'none'`.
- Agent WAPT extrait du `.deb` officiel, version et SHA-256 fixés, sans exécuter ses scripts d'installation.
