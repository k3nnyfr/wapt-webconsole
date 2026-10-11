# Roadmap

Plan détaillé, architecture et décisions : [PLAN.md](PLAN.md).

Les étapes v0.1 à v0.7 sont livrées dans la release **v0.7.0** (2026-10-11), voir le [changelog](CHANGELOG.md).

## v0.1 — Phase 0 : cadrage et prototypes (prototypes validés le 2026-10-11) — ✓ livré en v0.7.0
- [x] Créer le dépôt `wapt-webconsole` sur git.k3nny.fr (privé jusqu'à la v0.7.0, public depuis)
- [x] Recenser les endpoints de la console Discovery à partir des sources de WAPT 2.7 ([docs/wapt-api.md](docs/wapt-api.md))
- [ ] Confirmer sur le serveur réel les points restés ouverts (droits, audit, redémarrage, statut des tâches)
- [x] Prototype : image Docker avec `waptpython`, requête signée acceptée par un agent réel via proxy.example.org ([docs/prototype-signature.md](docs/prototype-signature.md))
- [x] Prototype : construction et signature d'un paquet machine modifié, sans envoi
- [x] Prototype : action réelle (`trigger_host_update`) exécutée par l'agent de `pc-01`, résultat suivi par `host_tasks_status`
- [x] Vérifier le format des paquets machine stockés : reconstruction identique à l'original, sauf version et signature
- [x] Déclarer le client OIDC dans Authelia, groupe `wapt-admins` pour alex ([docs/deploy.md](docs/deploy.md))

## v0.2 — Socle — ✓ livré en v0.7.0
- [x] Squelettes backend (FastAPI) et frontend (Vite, React, Mantine), CI Gitea (ruff, pytest, typecheck, build)
- [x] Coque d'interface responsive (barre latérale sur ordinateur, barre en bas sur mobile), manifeste PWA
- [x] Menu d'actions unique : clic droit, appui long, bouton `⋮`, feuille d'actions sur mobile
- [x] Connexion OIDC (code + PKCE), session signée, rôles par groupes, CSRF, durée de vie absolue
- [ ] Compte local de secours (mot de passe et TOTP)
- [x] Client WAPT (compte admin, reconnexion sur 401), testé contre un serveur réel
- [ ] Lecture des index `Packages`, comparaison de versions WAPT
- [x] Images Docker durcies et docker-compose, testés en local (podman)
- [x] Déploiement réel : docker-compose derrière Authelia (OIDC), deux reverse proxies en série, réseau sans « hairpin NAT »

## v0.3 — Inventaire en lecture seule *(premier usage réel)* — ✓ livré en v0.7.0
Retours du premier essai en production (2026-10-11) intégrés.

- [x] **Page Machines comme page d'accueil** : suppression du tableau de bord ; ses indicateurs (machines, connectées, à mettre à jour, en erreur) passent en en-tête de la page et servent de filtres rapides
- [x] Navigation prête pour les pages suivantes : Paquets et Groupes (v0.3), Journal (v0.4), Store (v0.7)
- [x] **Colonnes personnalisables** : afficher, masquer et réordonner, choix mémorisé par utilisateur, retour aux colonnes par défaut
- [x] Catalogue de colonnes :
  - identité : nom, description, domaine DNS ;
  - réseau : adresse IP principale, adresses IP, adresse MAC ;
  - utilisateurs : dernier utilisateur connecté, sessions ouvertes ;
  - système : OS, version, édition, architecture, dernier démarrage ;
  - matériel : fabricant, modèle, numéro de série, processeur, mémoire ;
  - WAPT : connexion, état, audit, mises à jour en attente, erreurs, dernière remontée, version de l'agent
- [x] **Tri sur toutes les colonnes**, par défaut les machines connectées en premier, puis par nom ; tri par menu sur mobile
- [x] Recherche et filtres (système, état, audit, domaine, agent) en plus des indicateurs ; liste de cartes sur mobile
- [x] Fiche machine (panneau latéral, plein écran sur mobile, adresse partageable) : résumé, matériel et disques, paquets avec journaux d'installation et d'audit, logiciels, paquet machine
- [x] Pages Paquets et Groupes en lecture : icônes, déploiement (installé, en attente, en erreur), fiche avec versions, contenu et « machines ayant ce paquet »
- [x] Statut en direct par WebSocket (backend seul à interroger le serveur WAPT, envoi des seules machines modifiées, reconnexion automatique)

## v0.4 — Actions à distance — ✓ livré en v0.7.0
- [x] Déverrouillage de la clé par session (passphrase vérifiée par WAPT puis oubliée, 30 min par défaut, 5 essais par 10 min), processus de signature unique arrêté quand plus personne ne l'utilise
- [x] Menus contextuels machines et paquets (clic droit, appui long, bouton `⋮`, feuille d'actions sur mobile) : update, upgrade, installer, désinstaller, oublier, annuler, renvoyer l'inventaire, audit, changer la description, redémarrer l'agent, Wake-on-LAN
- [x] Redémarrage et extinction de la machine, proposés seulement si l'agent les autorise (`allow_remote_reboot`, `allow_remote_shutdown`)
- [x] Sélection multiple et actions groupées ; confirmation obligatoire pour les actions destructrices, nombre de machines à retaper dès 10
- [x] Rôles par action : opérateur (update, upgrade, installation, inventaire, audit, annulation, Wake-on-LAN), admin (désinstallation, oubli, description, agent, redémarrage, extinction)
- [x] Suivi des tâches de l'agent dans la fiche machine (en cours avec progression, en attente, en erreur, terminées, journaux)
- [x] Journal d'audit (SQLite, volume persistant) : déverrouillages et actions, par utilisateur, IP, cibles, résultat
- [ ] Vérifier sur un agent Discovery l'audit à distance (`trigger_host_audit`) : relayé et accepté le 2026-10-11, mais sans effet tant qu'il n'est pas forcé (paquets pas encore à échéance) ; désormais toujours forcé

## v0.5 — Affectation et groupes — ✓ livré en v0.7.0
- [x] Ajouter ou retirer des paquets et des groupes sur une sélection de machines : choix, aperçu avant/après par machine, publication des paquets machine signés (`upload_hosts`)
- [x] Règles de la console WAPT : un paquet ajouté sort des conflits, un retrait couvre les dépendances avec contrainte de version ; paquets absents du dépôt refusés
- [x] Créer, modifier et supprimer des groupes (suppression refusée tant que des machines les utilisent)
- [x] Option « appliquer maintenant » (upgrade signé des machines connectées après publication)
- [x] Verrou optimiste : la version vue dans l'aperçu est relue avant l'écriture, un paquet modifié entre-temps (console WAPT, autre utilisateur) n'est pas écrasé
- [x] Points d'entrée : menu machine et sélection, fiche machine (paquet machine), fiche paquet et groupe (« Affecter à des machines », « Retirer de machines »), page Groupes
- [x] Dates absolues en RFC 3339 dans toute l'interface

## Sécurité de la clé de signature — option A ✓ livrée en v0.7.0
- [x] Option A : clé privée chiffrée et certificat apportés depuis l'appareil de l'opérateur à chaque déverrouillage, gardés en mémoire dans un processus de signature par session, jamais sur disque ; plus aucune clé stockée sur le serveur (2026-10-11)
- [x] Clés par opérateur possibles ; le journal indique le certificat utilisé (CN, empreinte)
- [ ] Option B : signature dans le navigateur (WebCrypto, RSA PKCS#1 v1.5 / SHA-256 sur JSON canonique), la clé ne quittant jamais l'appareil ; à prototyper comme en phase 0 (actions, puis paquets en deux temps : `control` puis manifeste)

## v0.6 — Gestion du dépôt — ✓ livré en v0.7.0
- [x] Suppression d'un paquet, refusée tant qu'un paquet, un groupe ou un paquet machine en dépend (raisons affichées) ; suppression d'une ancienne version, refusée si elle est exigée explicitement (`paquet(=version)`)
- [x] Envoi d'un `.wapt` déjà signé (contrôle du paquet, progression, fichiers temporaires hors mémoire, taille limitée)
- [x] Nettoyage des versions remplacées par cible (système, architecture, langue, maturité), en gardant N versions précédentes ; plan recalculé au moment de supprimer
- [x] Retrait de machines de l'inventaire, avec ou sans leur paquet machine
- [x] README avec captures d'écran, serveur de démonstration et script de captures reproductibles

## v0.7 — Store — ✓ livré en v0.7.0
- [x] Index du store Tranquil IT mis en cache (requête conditionnelle), confiance limitée aux empreintes configurées : l'index livre aussi un certificat « CN=test », ignoré
- [x] Catalogue filtré pour les systèmes du parc (Windows, macOS, Linux), production, langues courantes ; cibles « toutes architectures » périmées écartées ; recherche, catégories, état par rapport au dépôt
- [x] Paquets réservés à WAPT Enterprise signalés et refusés ; `waptupgrade`, `waptsetup`, `waptagent`, `waptserver` jamais importés
- [x] Import en tâche de fond : téléchargement (taille et MD5 vérifiés), signature d'origine vérifiée, renommage au préfixe du dépôt (dépendances comprises), signature avec la clé de l'opérateur, envoi ; progression par paquet ; dépendances absentes importées d'abord
- [x] Mises à jour disponibles pour les paquets du dépôt, « Tout mettre à jour »

## Plus tard
- [ ] Préférences d'affichage (colonnes, tri) enregistrées côté serveur, pour les retrouver d'un appareil à l'autre
- [ ] Vues d'analyse (logiciels hors WAPT, santé du parc, déploiements en erreur), sur le modèle de wapt-analyzer mais implémentées dans le projet
- [ ] Tâches planifiées (autopilot) pilotées depuis l'interface
- [ ] Notifications (mail, webhook) sur les erreurs de déploiement
- [ ] Interface en anglais
