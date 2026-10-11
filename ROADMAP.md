# Roadmap

Plan détaillé, architecture et décisions : [PLAN.md](PLAN.md).

## v0.1 — Phase 0 : cadrage et prototypes (prototypes validés le 2026-10-11)
- [x] Créer le dépôt `wapt-webconsole`, **privé** sur git.k3nny.fr (miroir GitHub à l'annonce)
- [x] Recenser les endpoints de la console Discovery à partir des sources de WAPT 2.7 ([docs/wapt-api.md](docs/wapt-api.md))
- [ ] Confirmer sur le serveur réel les points restés ouverts (droits, audit, redémarrage, statut des tâches)
- [x] Prototype : image Docker avec `waptpython`, requête signée acceptée par un agent réel via proxy.example.org ([docs/prototype-signature.md](docs/prototype-signature.md))
- [x] Prototype : construction et signature d'un paquet machine modifié, sans envoi
- [x] Prototype : action réelle (`trigger_host_update`) exécutée par l'agent de `pc-01`, résultat suivi par `host_tasks_status`
- [x] Vérifier le format des paquets machine stockés : reconstruction identique à l'original, sauf version et signature
- [x] Déclarer le client OIDC dans Authelia, groupe `wapt-admins` pour alex ([docs/deploy.md](docs/deploy.md))

## v0.2 — Socle
- [x] Squelettes backend (FastAPI) et frontend (Vite, React, Mantine), CI Gitea (ruff, pytest, typecheck, build)
- [x] Coque d'interface responsive (barre latérale sur ordinateur, barre en bas sur mobile), manifeste PWA
- [x] Menu d'actions unique : clic droit, appui long, bouton `⋮`, feuille d'actions sur mobile
- [x] Connexion OIDC (code + PKCE), session signée, rôles par groupes, CSRF, durée de vie absolue
- [ ] Compte local de secours (mot de passe et TOTP)
- [x] Client WAPT (compte admin, reconnexion sur 401), testé contre wapt.example.org
- [ ] Lecture des index `Packages`, comparaison de versions WAPT
- [x] Images Docker durcies et docker-compose, testés en local (podman)
- [x] Déploiement sur https://wapt-console.example.org (docker.example.org, Authelia OIDC, vhost et certificat sur proxy.example.org)

## v0.3 — Inventaire en lecture seule *(premier usage réel)*
Retours du premier essai sur wapt-console.example.org (2026-10-11) intégrés.

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
- [ ] Recherche et filtres (OS, état, connectée, en erreur) ; liste de cartes sur mobile
- [x] Fiche machine (panneau latéral, plein écran sur mobile, adresse partageable) : résumé, matériel et disques, paquets avec journaux d'installation et d'audit, logiciels, paquet machine
- [ ] Dépôt privé et groupes en lecture, « machines ayant ce paquet »
- [ ] Statut en direct par WebSocket

## v0.4 — Actions à distance
- [ ] Déverrouillage de la clé (passphrase en mémoire, durée limitée)
- [ ] Menus contextuels machines et paquets (clic droit, appui long, bouton `⋮`, feuille d'actions sur mobile) : update, upgrade, installer, désinstaller, oublier, annuler, renvoyer l'inventaire, changer la description, redémarrer l'agent, Wake-on-LAN
- [ ] Audit, redémarrage et extinction de la machine, si les agents Discovery les acceptent
- [ ] Suivi des tâches et résultats par machine
- [ ] Journal d'audit consultable

## v0.5 — Affectation et groupes
- [ ] Ajouter ou retirer des paquets et des groupes sur une sélection de machines, avec aperçu avant/après
- [ ] Créer, modifier et supprimer des groupes
- [ ] Option « appliquer maintenant » (upgrade des machines connectées après publication)
- [ ] Verrou optimiste contre les modifications concurrentes faites depuis la console lourde

## v0.6 — Gestion du dépôt
- [ ] Suppression de paquets, refusée si un autre paquet en dépend
- [ ] Upload d'un `.wapt` déjà signé
- [ ] Nettoyage des anciennes versions
- [ ] Suppression de machines de l'inventaire

## v0.7 — Store *(phase 2)*
- [ ] Parcourir et rechercher le store Tranquil IT (filtres OS, architecture, maturité, licence)
- [ ] Import avec vérification, préfixe et signature, en tâche de fond avec progression
- [ ] Mises à jour disponibles pour les paquets du dépôt, import groupé

## Plus tard
- [ ] Préférences d'affichage (colonnes, tri) enregistrées côté serveur, pour les retrouver d'un appareil à l'autre
- [ ] Vues d'analyse (logiciels hors WAPT, santé du parc, déploiements en erreur), sur le modèle de wapt-analyzer mais implémentées dans le projet
- [ ] Tâches planifiées (autopilot) pilotées depuis l'interface
- [ ] Notifications (mail, webhook) sur les erreurs de déploiement
- [ ] Interface en anglais
