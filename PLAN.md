# Console WAPT web — plan

Objectif : une console **full-web** pour piloter un serveur WAPT **Discovery** sans `waptconsole.exe` : inventaire, actions à distance, affectation de paquets aux machines et aux groupes, puis import depuis le store. Utilisable sur ordinateur, **tablette et mobile Android**. Back et front en conteneurs Docker, accès protégé par SSO.

Nom : **`wapt-webconsole`**, distinct du projet abandonné [Agumayasd/wapt-webui](https://github.com/Agumayasd/wapt-webui).

Serveur WAPT cible : **wapt.example.org**, **WAPT 2.7.0.19598 Discovery** (Debian 13). API cartographiée dans [docs/wapt-api.md](docs/wapt-api.md). Hébergement de la console : **docker.example.org** (docker-compose), derrière l'**Authelia** déjà en place.

**Code indépendant** : wapt-webconsole ne dépend pas de wapt-analyzer et n'en importe aucun module. wapt-analyzer sert seulement de référence documentaire (endpoints déjà validés, comportement de la signature).

Licence : GPL-3.0-or-later, comme WAPT et wapt-analyzer.

---

## 1. Périmètre

### Inclus : fonctionnalités de la console Discovery

| Domaine | Fonctionnalités |
|---|---|
| **Inventaire** | Liste des machines (recherche, filtres, colonnes, tri, sélection multiple), statut de connexion, dernière remontée, OS, version de l'agent, état des paquets (OK / en attente / erreur) |
| **Fiche machine** | Matériel (DMI), logiciels installés, paquets installés avec statut et logs d'installation, audit, paquet machine (dépendances, conflits), tâches en cours |
| **Actions à distance** | Update, upgrade, installer, désinstaller, oublier un paquet, audit, annuler les tâches, Wake-on-LAN, supprimer une machine de l'inventaire |
| **Affectation** | Ajouter ou retirer des paquets et des groupes sur une ou plusieurs machines (= reconstruire et signer le paquet machine) |
| **Groupes** | Créer, modifier et supprimer des paquets groupe, voir les machines concernées |
| **Dépôt privé** | Liste des paquets, détail (control, dépendances, signataire), suppression, upload d'un `.wapt` déjà signé |
| **Store** *(phase 2)* | Parcourir le store Tranquil IT, importer (vérification, préfixe, signature avec votre clé), mettre à jour |

### Exclu : fonctionnalités Enterprise

OU / Active Directory, profils, unités, ACL fines côté WAPT, self-service, WAPTWUA (Windows Update), dépôts secondaires, reporting SQL, WADS (déploiement d'OS), édition de `setup.py` dans la console (PyScripter).

### Hors périmètre pour l'instant

La création de paquets logiciels à partir d'un installeur. Elle demanderait l'édition et le test d'un `setup.py` ; on pourra y revenir plus tard.

---

## 2. Architecture

```
                 Internet / LAN
                       │
              ┌────────▼─────────┐
              │ proxy.example.org   │  LXC sur l'hyperviseur : terminaison TLS
              └────────┬─────────┘
              ┌────────▼─────────┐
              │ nginx            │  docker.example.org : vhost wapt-webconsole,
              │ (docker.example.org)   │  Authelia, en-têtes de sécurité
              └────────┬─────────┘
                       │
        ┌──────────────▼──────────────┐
        │ frontend (nginx)            │  SPA statique + proxy /api et /ws → backend
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐      ┌───────────────┐
        │ backend (FastAPI, uvicorn)  │─────▶│ Authelia (OIDC)│
        │  - session utilisateur      │      └───────────────┘
        │  - client API WAPT          │
        │  - signature (waptpython)   │      ┌───────────────┐
        │  - journal d'audit (SQLite) │─────▶│ wapt.example.org │  api/v3/*, /wapt (dépôt)
        │  - tâches longues + WS      │      └───────────────┘
        └─────────────────────────────┘
          volumes : /data (audit, cache)   secrets : clé, certificat, mots de passe
```

### Backend : Python + FastAPI

- **Briques propres au projet**, écrites pour une application web et non pour une CLI :
  - client API WAPT asynchrone (`httpx`) : login, TOTP, certificat client, reconnexion ;
  - lecture des index `Packages` (dépôt et store) et comparaison de versions WAPT ;
  - modèles Pydantic des machines, paquets et groupes, qui alimentent aussi l'OpenAPI ;
  - construction des paquets machine et groupe, actions signées, import du store.
- **Signature dans le conteneur** : l'image backend installe l'agent Linux WAPT (`tis-waptagent`, dépôt apt Tranquil IT, Debian 12) **sans l'enregistrer**, uniquement pour son `waptpython`. Un script propre au projet, `signer.py`, est exécuté par `waptpython`. Il utilise l'implémentation de référence (`waptcrypto.SSLPrivateKey.sign_claim`, `waptpackage.PackageEntry.sign_package`, `build_management_package`) au lieu de réécrire la signature, puisque c'est elle que les agents vérifient. Protocole : un job JSON en entrée, une ligne JSON par résultat en sortie. Un appel coûte environ 300 ms (démarrage et déchiffrement de la clé) : le backend garde un **processus `signer.py` persistant** tant que la passphrase est déverrouillée. Validé par le prototype ([docs/prototype-signature.md](docs/prototype-signature.md)). Seul point à vérifier : la licence de redistribution de l'image, qui pourrait limiter sa publication sur un registre public.
- **Client WAPT longue durée** : une session `httpx.AsyncClient` par backend, connexion automatique et reconnexion sur 401, requêtes parallèles bornées.
- **Cache et rafraîchissement** : le serveur WAPT n'a pas de flux d'événements pour une console (son socket.io sert aux agents). Le backend fait donc du **polling** :
  - `hosts` (connexion, statut, dernière remontée) toutes les 15 à 30 s ;
  - `host_tasks_status` sur les machines où une action est en cours.

  Les changements sont poussés aux navigateurs par le WebSocket du backend. Le détail d'une machine est chargé à la demande.
- **Résultat des actions** : `trigger_host_action` confirme seulement l'envoi aux machines connectées, pas le résultat. L'interface affiche donc une action comme « envoyée », puis « en cours » et « terminée » ou « en erreur » au fil du polling.
- **Tâches longues** (import, reconstruction de N paquets machine, Wake-on-LAN puis attente) : file en mémoire, une tâche à la fois par type, progression diffusée par WebSocket. Pas de Redis ni de Celery au départ.
- **Persistance** : SQLite dans `/data` pour le journal d'audit, l'historique des tâches et les préférences d'affichage. Pas de Postgres.

### Frontend : React + TypeScript + Vite

- **Mantine** (composants, thème clair/sombre, modales, notifications) avec **mantine-datatable** (grilles avec sélection multiple et tri) et **mantine-contextmenu** (clic droit).
  - Écarté : AG Grid, dont le menu contextuel n'existe que dans l'édition Enterprise payante.
- **TanStack Query** pour les données (cache, invalidation après action), **TanStack Router** ou React Router.
- **WebSocket** pour le statut des machines et la progression des tâches.
- Interface en français d'abord, textes centralisés (i18n possible plus tard).

### Ergonomie, proche de la console lourde

- Grille des machines avec un panneau de détail à droite (ou en dessous), onglets : Paquets / Logiciels / Matériel / Tâches / Paquet machine.
- **Clic droit sur une ou plusieurs machines** : Mettre à jour, Upgrade, Installer un paquet…, Ajouter à un groupe…, Retirer un paquet…, Audit, Réveiller, Annuler les tâches, Supprimer de l'inventaire.
- **Clic droit sur un paquet** (fiche machine) : Réinstaller, Désinstaller, Oublier, Voir les logs.
- **Clic droit sur un paquet du dépôt** : Voir les machines, Affecter à…, Supprimer.
- **Aperçu avant application**, sur le modèle de la simulation de wapt-analyzer : toute modification affiche le plan (machines touchées, dépendances avant/après, nombre de paquets signés) et demande confirmation. Au-delà d'un seuil (10 machines, par exemple), il faut retaper le nombre de machines.
- Raccourcis clavier (recherche `/`, sélection, `Échap`), barre de commande `Ctrl+K`.

### Mobile et tablette Android

La console doit rester pleinement utilisable au doigt, pas seulement lisible. C'est une contrainte de conception dès v0.2, pas une adaptation de fin de projet.

- **Trois mises en page** (points de rupture Mantine) :
  - ordinateur (≥ 1200 px) : grille et panneau de détail côte à côte ;
  - tablette (768 à 1199 px) : grille avec moins de colonnes, détail en panneau coulissant (`Drawer`) ;
  - mobile (< 768 px) : **liste de cartes** (nom, OS, statut, pastille d'erreurs) à la place de la grille, détail en plein écran avec onglets, navigation par barre en bas d'écran.
- **Menu contextuel sans clic droit** : le même menu s'ouvre par clic droit, par **appui long** (environ 500 ms) et par un bouton `⋮` sur chaque ligne ou carte. Sur mobile, il s'affiche en **feuille d'actions** en bas d'écran (`Drawer position="bottom"`). Les actions sont définies une seule fois et rendues selon le support.
- **Sélection multiple au toucher** : un appui long active le mode sélection, puis un appui simple coche ; une barre d'actions groupées remplace l'en-tête.
- **Cibles tactiles** d'au moins 44 px, pas d'information visible seulement au survol, confirmations en modale plein écran sur mobile.
- **Saisie de la passphrase** : champ `password` avec `autocomplete="off"`, jamais conservé par le navigateur.
- **PWA** : manifeste, icônes, `display: standalone` pour l'installer sur l'écran d'accueil Android. Le service worker met en cache l'interface seulement, **jamais les données de l'API** (inventaire et actions toujours en direct).
- **Réseau mobile** : réponses API compressées, pagination côté serveur au-delà de quelques centaines de machines, WebSocket reconnecté automatiquement (mise en veille, changement de réseau).
- **Recette** : Chrome Android (téléphone et tablette) et le mode appareil de Chrome desktop, dès la v0.3 ; captures d'écran mobiles dans la documentation.

---

## 3. Authentification et sécurité

Cette console peut **pousser du code sur tout le parc** : sa compromission équivaut à celle du serveur WAPT et de la clé de signature. Les choix ci-dessous partent de là.

### Accès à l'interface (utilisateurs)

- **Authelia comme fournisseur OpenID Connect**, avec un client `wapt-webconsole` déclaré dans `identity_providers.oidc.clients` (flux *authorization code* + PKCE, scopes `openid profile email groups`, politique `two_factor`).
- **OIDC natif dans le backend** (Authlib), en mode *Backend-for-Frontend* : le navigateur ne voit jamais de jeton, seulement un cookie de session `HttpOnly`, `Secure`, `SameSite=Strict`, avec un en-tête anti-CSRF sur les requêtes qui modifient l'état.
- **Rôles** déduits du claim `groups` d'Authelia (groupes `wapt-viewers`, `wapt-operators`, `wapt-admins`, noms configurables) :
  - `viewer` : lecture seule ;
  - `operator` : actions à distance (update, upgrade, audit, Wake-on-LAN) ;
  - `admin` : affectations, groupes, dépôt, import, suppression de machines.
- **Compte local de secours** (désactivable), mot de passe et TOTP, pour le premier démarrage ou une panne de l'IdP.
- Variante écartée : le `forward-auth` d'Authelia (en-têtes `Remote-User` et `Remote-Groups`). Il est plus simple à brancher, mais le backend devrait alors faire confiance à des en-têtes qu'un accès direct au conteneur permettrait de falsifier. Il reste possible d'**ajouter** le forward-auth devant l'OIDC, comme seconde barrière.

### Accès au serveur WAPT (backend)

- **Compte `admin` du serveur WAPT** (mot de passe en secret Docker) : Discovery ne permet pas de créer un autre compte administrateur. Sans TOTP, car une connexion non interactive ne peut pas fournir de code. Certificat client pris en charge si le nginx du serveur l'exige.
- En Discovery, WAPT ne voit qu'un seul compte. **Le journal d'audit de la console** enregistre donc qui a fait quoi : utilisateur SSO, action, cibles, avant/après, résultat. Il est consultable dans l'interface et exportable.

### Clé de signature

| Option | Sécurité | Confort |
|---|---|---|
| A. Clé chiffrée en secret Docker, **passphrase saisie dans l'interface** et gardée en mémoire N minutes (comme `sudo`), réservée aux rôles `operator` et `admin` | Élevée : rien d'exploitable au repos | Une saisie par session de travail |
| B. Clé et passphrase en secrets Docker | Moyenne : l'accès à l'hôte Docker donne la clé | Aucune saisie |
| C. Clé sur l'hôte et signature déportée (agent local, HSM) | Très élevée | Complexe |

**Retenu : A par défaut, B en option** pour d'éventuelles tâches planifiées. Les actions à distance (`trigger_host_action`) sont signées elles aussi, donc la clé est nécessaire même pour un simple upgrade.

### Exposition

- Le backend joint le serveur WAPT **par son URL publique**, donc par proxy.example.org pour wapt.example.org. Aucune hypothèse de réseau interne : la console doit fonctionner avec n'importe quel serveur WAPT.
- **Deux proxys en série** (proxy.example.org pour le TLS, puis le nginx de docker.example.org) :
  - uvicorn lancé avec `--proxy-headers` et `--forwarded-allow-ips` limité au nginx, pour que le backend voie `https` (cookies `Secure`, URI de redirection OIDC) et la vraie IP du client (journal d'audit) ;
  - `X-Forwarded-For` et `X-Forwarded-Proto` transmis tels quels par les deux proxys ;
  - montée en WebSocket (`Upgrade`, `Connection`) autorisée sur les deux, avec un `proxy_read_timeout` long ;
  - `client_max_body_size` relevé sur les deux pour l'upload de paquets (plusieurs centaines de Mo).
- Exposer cette console sur Internet n'est acceptable qu'avec : SSO avec MFA obligatoire, liste d'IP autorisées ou VPN si possible, CSP stricte, limitation de débit sur l'authentification, conteneurs non-root avec système de fichiers en lecture seule, journal d'audit. Le plus sûr serait de la garder sur le réseau interne ou derrière le VPN.

---

## 4. Points techniques à valider (phase 0)

1. **API WAPT** : **fait**, voir [docs/wapt-api.md](docs/wapt-api.md). Restent à tester sur le serveur réel : droits d'un compte de service non admin, actions audit et redémarrage sur un agent Discovery, format de `host_tasks_status`.
2. **waptpython dans Docker** : installer `tis-waptagent` sans l'enregistrer dans une image Debian, puis exécuter `signer.py` (signer une action, construire un paquet machine).
3. **Concurrence avec la console lourde** : avant de reconstruire un paquet machine ou groupe, relire sa version courante sur le serveur et refuser si elle a changé depuis l'affichage (verrou optimiste).
4. **Chiffrement des paquets machine** (`upload_hosts`) : vérifier que le serveur chiffre bien les paquets machine envoyés depuis le conteneur.
5. **Performances** : temps de chargement de `host_data` pour toutes les machines. Charger la fiche à la demande plutôt que tout l'inventaire détaillé d'un coup.

---

## 5. Structure du dépôt

```
wapt-webconsole/
├── backend/
│   ├── pyproject.toml          # FastAPI, Authlib, httpx, Pydantic, pytest, ruff
│   ├── Dockerfile              # Debian 12 + tis-waptagent (waptpython) + uv
│   └── src/wapt_webconsole/
│       ├── main.py             # application, routes, WebSocket
│       ├── auth/               # OIDC, session, rôles, compte local
│       ├── wapt/               # client API, index Packages, versions, cache inventaire, paquets machine/groupe
│       ├── signing/            # déverrouillage de la clé, signer.py (exécuté par waptpython)
│       ├── jobs/               # tâches longues et progression
│       ├── audit/              # journal SQLite
│       └── api/                # routes REST : hosts, packages, groups, actions, store, audit
├── frontend/
│   ├── package.json            # React, Vite, Mantine, TanStack Query
│   ├── Dockerfile              # build Node → image nginx
│   └── src/
│       ├── pages/              # Machines, Dépôt, Groupes, Store, Journal, Paramètres
│       ├── components/         # grilles, menus contextuels, panneau de détail, aperçu
│       └── api/                # client typé, généré depuis l'OpenAPI du backend
├── deploy/
│   ├── docker-compose.yml      # frontend + backend, réseau du reverse proxy, secrets, volume /data
│   ├── authelia-client.yml     # extrait de configuration du client OIDC pour Authelia
│   └── .env.example
├── docs/
├── CHANGELOG.md
├── ROADMAP.md
└── README.md
```

Le client TypeScript est généré depuis l'OpenAPI de FastAPI (`openapi-typescript`), pour garder front et back synchronisés.

---

## 6. Feuille de route

### v0.1 — Phase 0 : cadrage et prototypes (prototypes validés le 2026-10-11)
- [ ] Créer le dépôt `wapt-webconsole`, **privé** sur git.k3nny.fr (miroir GitHub à l'annonce)
- [x] Recenser les endpoints de la console Discovery à partir des sources de WAPT 2.7 ([docs/wapt-api.md](docs/wapt-api.md))
- [ ] Confirmer sur le serveur réel les points restés ouverts (droits, audit, redémarrage, statut des tâches)
- [x] Prototype : image Docker avec `waptpython`, requête signée acceptée par un agent réel via proxy.example.org ([docs/prototype-signature.md](docs/prototype-signature.md))
- [x] Prototype : construction et signature d'un paquet machine modifié, sans envoi
- [x] Prototype : action réelle (`trigger_host_update`) exécutée par l'agent de `pc-01`, résultat suivi par `host_tasks_status`
- [x] Vérifier le format des paquets machine stockés : reconstruction identique à l'original, sauf version et signature
- [ ] Déclarer le client OIDC dans Authelia, créer les groupes de rôles

### v0.2 — Socle
- [ ] Squelettes backend (FastAPI) et frontend (Vite, React, Mantine), CI (ruff, pytest, eslint, typecheck, build des images)
- [ ] Coque d'interface responsive (barre latérale sur ordinateur, barre en bas sur mobile), manifeste PWA
- [ ] Connexion OIDC via Authelia, session, rôles, compte local de secours
- [ ] Client WAPT (compte de service, reconnexion), lecture des index `Packages`, comparaison de versions, tests unitaires
- [ ] docker-compose fonctionnel en local puis sur docker.example.org

### v0.3 — Inventaire en lecture seule *(premier usage réel)*
- [ ] Grille des machines : recherche, filtres (OS, statut, connectée, en erreur), colonnes configurables ; liste de cartes sur mobile
- [ ] Fiche machine : paquets (statut, logs), logiciels, matériel, paquet machine
- [ ] Dépôt privé et groupes en lecture, « machines ayant ce paquet »
- [ ] Statut en direct par WebSocket

### v0.4 — Actions à distance
- [ ] Déverrouillage de la clé (passphrase en mémoire, durée limitée)
- [ ] Menus contextuels machines et paquets (clic droit, appui long, bouton `⋮`, feuille d'actions sur mobile) : update, upgrade, installer, désinstaller, oublier, annuler, renvoyer l'inventaire, changer la description, redémarrer l'agent, Wake-on-LAN
- [ ] Audit, redémarrage et extinction de la machine, si les agents Discovery les acceptent
- [ ] Suivi des tâches et résultats par machine
- [ ] Journal d'audit consultable

### v0.5 — Affectation et groupes
- [ ] Ajouter ou retirer des paquets et des groupes sur une sélection de machines, avec aperçu avant/après
- [ ] Créer, modifier et supprimer des groupes
- [ ] Option « appliquer maintenant » (upgrade des machines connectées après publication)
- [ ] Verrou optimiste contre les modifications concurrentes faites depuis la console lourde

### v0.6 — Gestion du dépôt
- [ ] Suppression de paquets, refusée si un autre paquet en dépend
- [ ] Upload d'un `.wapt` déjà signé
- [ ] Nettoyage des anciennes versions
- [ ] Suppression de machines de l'inventaire

### v0.7 — Store *(phase 2)*
- [ ] Parcourir et rechercher le store Tranquil IT (filtres OS, architecture, maturité, licence)
- [ ] Import avec vérification, préfixe et signature, en tâche de fond avec progression
- [ ] Mises à jour disponibles pour les paquets du dépôt, import groupé

### Plus tard
- [ ] Vues d'analyse (logiciels hors WAPT, santé du parc, déploiements en erreur), sur le modèle de wapt-analyzer mais implémentées dans le projet
- [ ] Tâches planifiées (autopilot) pilotées depuis l'interface
- [ ] Notifications (mail, webhook) sur les erreurs de déploiement
- [ ] Interface en anglais

---

## 7. Questions ouvertes

1. Le serveur WAPT exige-t-il un certificat client (nginx) ? Ce n'est pas le cas aujourd'hui pour wapt.example.org, mais la prise en charge est prévue pour d'autres serveurs.

## Décisions

| Sujet | Décision |
|---|---|
| Nom | `wapt-webconsole` |
| Serveur WAPT | wapt.example.org, WAPT 2.7.0.19598 Discovery, joint par son URL publique (proxy.example.org) ; console utilisable avec n'importe quel serveur |
| Compte WAPT | `admin` (Discovery n'en permet pas d'autre) ; traçabilité par le journal d'audit de la console |
| Reverse proxy | proxy.example.org (TLS) puis nginx sur docker.example.org |
| SSO | Authelia existant, en fournisseur OIDC |
| Code | Indépendant de wapt-analyzer : aucune dépendance, aucun import |
| Clé de signature | Option A (passphrase saisie dans l'interface), B en option |
| Stack | FastAPI + waptpython / React + Mantine / docker-compose |
| Supports | Ordinateur, tablette et mobile Android (responsive, appui long, PWA) |
| Dépôt | Privé sur git.k3nny.fr jusqu'à l'annonce ; pas de miroir GitHub avant |
