# Prototype de signature

Objectif : vérifier qu'un conteneur peut signer les actions et les requêtes destinées aux agents WAPT avec l'implémentation de référence (`waptcrypto`), et qu'un agent réel les accepte. Le flux passe par le reverse proxy proxy.example.org, comme pour n'importe quel serveur WAPT.

Les essais ont été menés sur une installation réelle ; ses noms d'hôtes, de machines et d'utilisateurs sont remplacés ici par des valeurs fictives.

Fichiers :
- `backend/signer/signer.py` : exécuté par `waptpython`, requête JSON sur stdin, une ligne JSON par résultat sur stdout. Opérations `info`, `sign_actions` et `verify_actions`. La passphrase ne transite que par stdin.
- `backend/proto/proto_signing.py` : scénario de test en Python standard (sans dépendance), qui appelle `signer.py` en sous-processus, comme le fera le backend.
- `backend/proto/Dockerfile` : Debian 13 slim et `/opt/wapt` extrait du `.deb` de l'agent 2.7.0.19598 (version et SHA-256 fixés, scripts `postinst` **non** exécutés), utilisateur non-root.

## Résultats du 2026-10-11

| Étape | Résultat |
|---|---|
| Extraction de l'agent et import de `waptcrypto`, `waptpackage` et `waptutils` | OK, image de 349 Mo |
| Certificat et clé (`info`) | OK : CN `wapt.example.org`, signature de code, expire le 2027-09-14 |
| Signature d'une action (`sign_claim`) | OK, environ 300 ms par appel (démarrage de `waptpython` compris) |
| Vérification telle que la fait l'agent (`check_action_signature`) | OK : `verified_by=wapt.example.org` |
| Copie modifiée après signature | Rejetée (`SSLVerifyException`) |
| Login `admin` sur https://wapt.example.org (via proxy.example.org) | OK : 11 machines, 1 connectée |
| `host_tasks_status` signé vers `pc-01.example.lan` (agent 2.7.0.19598) | **Accepté par l'agent** : `last_event_id=530`, 30 tâches terminées |
| Même requête modifiée après signature | **Refusée par l'agent** : `Error on client: SSLVerifyException` |
| `trigger_host_update` signé (rafraîchit l'index des paquets de la machine), lancé par l'utilisateur | OK : relayé par le serveur (« Actions launched: 1 »), exécuté par l'agent, résultat lu par `host_tasks_status` : « 47 paquet(s) dans le dépôt ; paquets à mettre à jour : 1B4E28BA-…(=7), tsi-obs-studio(=32.2.2.0-31) » |

La chaîne complète est donc validée : conteneur → `waptpython` → serveur (via le reverse proxy) → websocket → agent → vérification de la signature. L'exécution d'une tâche déclenchée à distance est aussi constatée : la phase 0 est validée.

## Paquet machine (2026-10-11, sans envoi)

Étape 6 (`--build-host`) : le `control` du paquet machine est lu sur le serveur (`api/v3/packages?sections=host&q=<uuid>`), puis modifié selon les règles de `Wapt.edit_host` de la console (un paquet ajouté aux dépendances sort des conflits, et inversement). Le paquet est ensuite reconstruit (`build_management_package`), sa version incrémentée, signé et vérifié. `api/v3/upload_hosts` n'est jamais appelé.

| Essai sur `pc-01.example.lan` | Résultat |
|---|---|
| Reconstruction sans changement | OK : version 7 → 8, mêmes 25 dépendances, nouveau `package_uuid`, signature vérifiée (`wapt.example.org`), autres attributs identiques |
| `--add-depends tsi-7zip,tsi-doesnotexist --remove-depends tsi-handbrake` | OK : `tsi-7zip` ajouté, `tsi-handbrake` retiré. `tsi-doesnotexist` signalé absent du dépôt mais **ajouté quand même** : la console devra bloquer ce cas |
| Contenu du `.wapt` | `WAPT/control`, `WAPT/certificate.crt`, `WAPT/manifest.sha256`, `WAPT/signature.sha256` (2,9 Ko) |

Points à reprendre dans le backend :
- **Champ `name`** : `api/v3/packages` le remplace par le FQDN de la machine (`pe.name = computer_fqdn`, `server.py`), alors qu'il est **vide dans les paquets stockés**. Vérifié avec `sudo` sur les 11 fichiers de `/var/www/wapt-host/`. Le backend ignore donc `name` dans la réponse de l'API. Après cette correction, le paquet reconstruit est **identique à l'original** sauf `version`, `package_uuid`, `signature` et `signature_date`, avec les mêmes 4 fichiers et les mêmes tailles.
- **Concurrence** : le backend relira la version juste avant l'envoi et refusera si elle a changé depuis l'aperçu (ici 7). Sinon, une modification faite entre-temps dans la console lourde serait écrasée.
- **Dépendances inconnues** : refuser un paquet absent du dépôt, et accepter les groupes (`section=group`), qui sont aussi des dépendances.

Structure des paquets machine sur wapt.example.org (11 fichiers, lus avec `sudo`) :
- zip **non chiffré** de 4 fichiers : `WAPT/control`, `WAPT/certificate.crt`, `WAPT/manifest.sha256`, `WAPT/signature.sha256` ;
- `control` complet (44 attributs, tous signés), dont seuls `package` (uuid), `version`, `architecture: all`, `section: host`, `priority: optional`, `target_os: all`, `description` (nom de la machine), `depends` et la signature sont renseignés ;
- les dates de signature groupées (2026-10-10 12:09:29, 2026-10-11 10:00:20) montrent que ces paquets ont été produits en lot, sans doute par `wapt-analyzer hosts`, qui utilise les mêmes fonctions WAPT. Pour une référence produite par `waptconsole.exe`, il faudrait modifier une machine dans la console puis relire son paquet.

## Ce que le prototype a appris

- **`waptpython.sh` développe `$@` sans guillemets** : `-c "import x"` est découpé. Il faut toujours lui passer un chemin de script sans espace.
- **`waptpython.sh` lance Python avec `-I`** : `PYTHONPATH` est ignoré et `/opt/wapt` n'est pas dans `sys.path`, même sur une installation normale. `signer.py` l'ajoute lui-même (`WAPT_BASE_DIR`, `/opt/wapt` par défaut).
- **Le `.deb` de l'agent suffit**, sans l'installer : `dpkg-deb --fsys-tarfile ... | tar -x ./opt/wapt`. Le `postinst` (systemd, rsyslog, redémarrage du service) n'est pas exécuté. Le dépôt apt de Tranquil IT ne contient que le serveur ; l'agent vient de `https://wapt.tranquil.it/wapt/releases/wapt-<version>/`. `tis-waptcore` ne contient pas Python et ne convient pas.
- **Coût d'un appel** : environ 300 ms, dus au démarrage de l'interpréteur et au déchiffrement de la clé. Pour le polling de `host_tasks_status` (une requête signée par machine toutes les quelques secondes), le backend gardera un **processus `signer.py` persistant** : clé déchiffrée une fois, requêtes en flux, arrêt à l'expiration de la passphrase.
- **Toutes les clés de l'action sont signées** (`signed_attributes`) : le backend ne doit rien modifier après la signature, ni ajouter de champ.
- **Dérive d'horloge** : l'agent contrôle la date de signature pour les actions (`signature_clockskew`). Le conteneur doit avoir une horloge juste (NTP de l'hôte).

## Relancer

```bash
cd backend
podman build -f proto/Dockerfile -t wapt-webconsole-signer-proto .     # ou docker build

P=/chemin/vers/certificat; C=~/.config/wapt-analyzer
podman run --rm --userns=keep-id --user $(id -u) \
  -v $P/signer.crt:/run/secrets/signer.crt:ro -v $P/signer.pem:/run/secrets/signer.pem:ro \
  -v $C/key-password:/run/secrets/key_password:ro -v $C/password:/run/secrets/wapt_password:ro \
  wapt-webconsole-signer-proto                       # --offline : sans serveur ; --host <uuid|fqdn> ; --trigger update
```

L'étape 6 construit le paquet machine dans le dossier monté sur `/out`, sans l'envoyer :

```bash
... -v "$PWD/out:/out" wapt-webconsole-signer-proto --host pc-01.example.lan --build-host \
    --add-depends tsi-7zip --remove-depends tsi-handbrake
```

L'étape 5 envoie une action réelle (`trigger_host_update`, sans installation) à la machine choisie :

```bash
... wapt-webconsole-signer-proto --host pc-01.example.lan --trigger update
```
