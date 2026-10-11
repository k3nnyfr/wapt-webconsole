# Changelog

## [0.7.0] - 2026-10-11

Première version publiée : les étapes v0.1 à v0.7 de la [feuille de route](ROADMAP.md).

### Added
- **Console web pour WAPT 2.7 Discovery** : backend FastAPI, interface React et Mantine, deux conteneurs Docker durcis (lecture seule, sans privilèges, non root) et docker-compose ; utilisable sur ordinateur, tablette et téléphone Android (cartes, feuille d'actions, barre de navigation basse, PWA).
- **Connexion par SSO** OpenID Connect (code + PKCE, Authelia ou autre fournisseur), session signée sans jeton côté navigateur, jeton CSRF, durée de vie absolue ; rôles lecture, opérateur et admin déduits des groupes du fournisseur. Script `deploy/authelia-register.sh` pour déclarer la console dans Authelia.
- **Page Machines** : inventaire en direct par WebSocket (une seule boucle de lecture côté backend, seules les machines modifiées envoyées), indicateurs servant de filtres (connectées, mises à jour, erreurs), 25 colonnes à afficher, réordonner et trier (connectées d'abord par défaut), recherche, filtres par système, état, audit, domaine et agent.
- **Fiche machine** : système, état WAPT, réseau, utilisateurs, matériel, BIOS et disques ; paquets avec journaux d'installation et d'audit ; logiciels ; paquet machine ; tâches de l'agent (en cours avec progression, en attente, en erreur, terminées).
- **Actions à distance** signées, sur une machine ou une sélection (clic droit, appui long, bouton `⋮`) : mise à jour de l'index, application des mises à jour, installation, remontée d'inventaire, audit, annulation, Wake-on-LAN (opérateur) ; désinstallation, oubli, description, redémarrage de l'agent, redémarrage et extinction si l'agent les autorise (admin). Machines déconnectées signalées, confirmation des actions destructrices, nombre de machines à retaper dès 10.
- **Affectation de paquets et de groupes** : aperçu avant/après de chaque paquet machine, construction et signature par `waptpython`, publication (`upload_hosts`), mise à jour immédiate en option ; règles de la console WAPT (un paquet ajouté sort des conflits, retrait des dépendances contraintes) ; verrou optimiste contre les modifications faites entre-temps dans la console WAPT.
- **Groupes** : création, modification et suppression (refusée tant que des machines les utilisent).
- **Gestion du dépôt** : pages Paquets et Groupes avec icônes et état de déploiement ; suppression d'un paquet ou d'une version, refusée tant que quelque chose en dépend ; envoi d'un `.wapt` signé ; nettoyage des versions remplacées par cible ; retrait de machines de l'inventaire.
- **Store Tranquil IT** : catalogue filtré pour les systèmes du parc, mises à jour disponibles pour le dépôt, import en tâche de fond (taille et MD5 vérifiés, signature d'origine vérifiée, renommage au préfixe du dépôt avec les dépendances, signature avec la clé de l'opérateur, envoi), dépendances absentes importées d'abord.
- **Clé de signature apportée par l'opérateur** : clé privée chiffrée et certificat choisis sur son appareil à chaque déverrouillage, gardés en mémoire dans un processus de signature propre à la session (30 minutes par défaut), jamais sur disque ; clé non chiffrée refusée ; essais limités. Une clé stockée sur le serveur reste possible par l'override de compose.
- **Journal d'audit** (SQLite, volume persistant) : déverrouillages, actions, publications, imports et suppressions, avec l'utilisateur, son IP, les machines, le certificat signataire et le résultat.
- **Dates absolues en RFC 3339** dans toute l'interface.
- **Documentation** : README avec captures, guide de déploiement (reverse proxies, réseaux sans « hairpin NAT »), cartographie de l'API WAPT 2.7, prototype de signature ; serveur de démonstration sur données fictives et script de captures (`scripts/`).

### Fixed
- Dernier utilisateur des machines macOS, remonté sous forme de liste par l'agent.
- Noms de machine contenant un retour à la ligne.
- Paquets remontés deux fois par WAPT pour une même machine (statistiques et affichage).
- Audit à distance sans effet : l'agent ignore les paquets pas encore à échéance, l'action est désormais toujours forcée.
- Champ `name` des paquets machine : l'API le remplace par le FQDN, il n'est plus réécrit dans les paquets reconstruits.
- Store : les anciennes entrées « toutes architectures » ne sont plus proposées à côté d'une version plus récente, `waptupgrade`, `waptsetup`, `waptagent` et `waptserver` ne sont jamais importés, et seul le certificat Tranquil IT est accepté (l'index en livre aussi un « CN=test »).
