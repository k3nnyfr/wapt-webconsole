# API du serveur WAPT 2.7 — cartographie

Établie à partir des sources du serveur **WAPT 2.7.0.19598 Discovery** installé sur wapt.example.org (`/opt/wapt/waptserver/server.py`, `decorators.py`, `server_socketio.py`) et de l'agent livré avec (`/opt/wapt/waptservice/`). Seul le code a été lu : aucun appel n'a été fait au serveur.

Conventions de toutes les réponses : JSON `{"success": bool, "msg": str, "result": ..., "request_time": float}`. Un échec renvoie `success: false`, souvent avec HTTP 200 : il faut toujours tester `success`.

## Authentification

| Endpoint | Méthode | Usage |
|---|---|---|
| `/api/v3/login` | POST `{"user", "password"}` | Ouvre une session (cookie Flask). Si le compte a un TOTP : 401 avec `Missing TOTP code`, puis renvoyer `password` suivi de `{code}`. `get_token: true` renvoie un jeton au lieu d'un cookie. Le résultat contient `user_acls` et `hosts_count`. |
| `/api/v3/logout` | POST | Ferme la session. |
| `/api/v3/get_current_user_acls` | GET | Droits du compte connecté. |
| `/api/v3/ping` | GET | Version du serveur, sans authentification. |

Méthodes acceptées par `requires_auth` : session (cookie), Basic, jeton, certificat client (en-tête `X-Ssl-Client-Sha1` posé par le nginx du serveur). Le backend utilisera la session avec un compte de service, et se reconnectera sur 401.

## Lecture

| Endpoint | Méthode | Paramètres utiles | Usage dans la console |
|---|---|---|---|
| `/api/v3/hosts` | GET, POST | `columns` (csv ou liste JSON), `uuid`, `filter=champs:regex`, `not_filter`, `has_errors`, `need_upgrade`, `groups`, `limit`, `format=compact` | Grille des machines. Colonnes par défaut : `uuid`, `host_status`, `computer_fqdn`, `description`, `last_seen_on`, `server_uuid` |
| `/api/v3/host_data` | GET, POST | `uuid`, `field` = une colonne de `Hosts` ou `installed_packages`, `installed_softwares`, `audit_data`, `configurations`, `wsusupdates` | Fiche machine : paquets, logiciels, matériel (`dmi`, `wmi`), audit |
| `/api/v3/packages_for_hosts` | GET, POST | `host_uuids`, `install_status`, `last_audit_status`, `sections`, `reachable`, `limit` | Statut agrégé des paquets sur un ensemble de machines |
| `/api/v3/hosts_for_package` | GET, POST | `package`, `columns`, `limit` | « Machines ayant ce paquet » |
| `/api/v3/hosts_count_for_package` | GET | | Compteurs dans la vue dépôt |
| `/api/v3/packages` | GET | `q`, `sections` (défaut `base,wsus`, `host` pour les paquets machine), `newest_only`, `dependencies` | Dépôt privé, paquets machine stockés |
| `/api/v3/packages_list` | GET | | Liste brute des paquets en base |
| `/api/v3/known_packages` | GET | | Noms de paquets connus (autocomplétion) |
| `/api/v3/groups` | GET | | Paquets groupe (`section == group`) |
| `/api/v3/host_packages_filters` | GET | | Filtres prédéfinis de la console |
| `/api/v3/audit_data` | GET, POST | `host_uuids`, `section`, `keys`, `latest_only`, `columns` | Données d'audit des paquets |
| `/api/v3/waptagent_version` | GET | | Version de référence de l'agent |
| `/api/v3/usage_statistics` | GET | | Tableau de bord |
| `/api/v3/global_config` | GET | | Configuration exposée par le serveur |
| `/api/v3/trusted_signers_certificates` | GET | | Certificats de signature acceptés |

## Écriture

| Endpoint | Méthode | Corps | Usage |
|---|---|---|---|
| `/api/v3/upload_packages` | POST multipart | fichier `.wapt` signé | Paquets logiciels et **groupes** |
| `/api/v3/upload_hosts` | POST multipart | fichier `.wapt` signé | **Paquets machine** (affectation de paquets et de groupes à une machine) ; le serveur les chiffre pour la machine s'il est configuré pour |
| `/api/v3/packages_delete` | POST | liste de noms de fichiers | Suppression dans le dépôt |
| `/api/v3/packages_delete_by_uuid` | POST | `{"package_uuids": [...]}` | Suppression dans le dépôt (utilisé par wapt-analyzer) |
| `/api/v3/hosts_delete` | POST | `{"uuids": [...], "delete_packages": bool, "delete_inventory": bool}` (ou `filter`) | Retirer une machine de l'inventaire, éventuellement son paquet machine |
| `/api/v3/trigger_wakeonlan` | POST | `{"uuids": [...]}` | Wake-on-LAN (non signé) |
| `/api/v3/trigger_host_action` | POST | une action signée ou une liste | Actions à distance, voir plus bas |
| `/api/v3/host_tasks_status` | GET, POST | `{"uuid", "last_event_id", "timeout"}`, **signé** | Tâches en cours d'une machine connectée |
| `/api/v3/trigger_cancel_task` | GET | | Annulation (ancienne API) |

## Actions à distance

Le serveur relaie l'action par websocket **uniquement aux machines connectées** et **refuse toute action non signée**. L'agent vérifie la signature contre ses certificats de confiance et la dérive d'horloge (`signature_clockskew`), puis met la tâche en file. La signature est produite par `waptcrypto.SSLPrivateKey.sign_claim(action, signer_certificate_chain=...)`, comme le fait la console.

`trigger_host_action` **ne renvoie pas le résultat des tâches** (le callback est commenté côté serveur). Seul le compteur « Actions launched » est fiable. Le suivi passe par `host_tasks_status` (signé), puis par la relecture de `hosts` et `host_data` après la remontée de l'agent (`notify_server: true`).

Champs communs : `action`, `uuid` (ou `uuids`), `notify_server`, `notify_user`, `force`.

| Action | Champs en plus | Effet sur l'agent | Console Discovery |
|---|---|---|---|
| `trigger_host_update` | `download` | Met à jour l'index des paquets (et télécharge) | Oui |
| `trigger_host_upgrade` | `update`, `only_priorities`, `only_if_not_process_running` | Update, téléchargement, upgrade, nettoyage | Oui |
| `trigger_install_packages` | `packages` | Télécharge et installe chaque paquet | Oui |
| `trigger_remove_packages` | `packages` | Désinstalle | Oui |
| `trigger_forget_packages` | `packages` | Oublie le paquet sans le désinstaller | Oui |
| `trigger_cancel_all_tasks`, `trigger_cancel_running_task`, `trigger_cancel_tasks` (`id`) | | Annule des tâches | Oui |
| `trigger_host_update_server_status` | | Renvoie l'inventaire au serveur | Oui |
| `trigger_change_description` | `computer_description` | Change la description de la machine | Oui |
| `trigger_waptservicerestart` | | Redémarre le service de l'agent | Oui |
| `trigger_host_audit`, `trigger_audit_packages` (`packages`) | | Audit des paquets | À tester : le code de l'agent n'a pas de contrôle de licence, mais la console officielle peut griser l'entrée |
| `trigger_host_reboot`, `trigger_host_shutdown` | `only_if_no_user_session` | Redémarrage, extinction | Idem, et seulement si l'agent l'autorise (`allow_remote_reboot`, `allow_remote_shutdown`) |
| `show_message` (`msg`), `start_waptexit`, `trigger_session_setup`, `trigger_gpupdate`, `trigger_cleanmgr` | | | Hors périmètre au départ |
| `trigger_waptwua_*` | | Windows Update | **Enterprise**, exclu |

## Temps réel

Le socket.io du serveur (`server_socketio.py`) est conçu pour les **agents** : il relaie `trigger_*_result` dans la room de l'uuid de la machine. Il n'existe pas de flux d'événements prévu pour une console. Le backend fera donc du **polling** :

- `hosts` (colonnes `reachable`, `host_status`, `last_seen_on`, `last_update_status`) toutes les 15 à 30 s ;
- `host_tasks_status` sur les machines où une action vient d'être lancée.

Il poussera les changements aux navigateurs par son propre WebSocket.

## Exclu : Enterprise, ou sans objet pour la console

AD (`get_ad_*`, `hosts_sid`), ACL et comptes (`users_acls`, `*_otp`, `set_account_certificate`), licences, WADS (`wads.py`), WSUS (`wsus*.py`), `hosts_for_wua`, `hosts_for_normalization`, `merge_stripped_package` (paquets unité, profil, self-service), `login_self_service`, configurations, modèles, `upload_agents`, `get_waptagent_exe`, `dag_download_files`.

## Encore à vérifier sur le serveur réel

1. Les droits effectifs d'un compte de service non admin en Discovery (`user_acls`).
2. Les actions audit et redémarrage : acceptées par les agents Discovery ?
3. Le format exact de `host_tasks_status` et de `last_event_id`.
4. La forme de `packages_delete` (noms de fichiers) par rapport à `packages_delete_by_uuid`.
