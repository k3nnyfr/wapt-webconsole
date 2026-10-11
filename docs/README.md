# Documentation

[README](../README.md) · [Feuille de route](../ROADMAP.md)

## Mise en route

- [Déploiement](deploy.md) : Docker Compose, secrets, déclaration dans Authelia, reverse proxies, clé de signature, réseaux sans « hairpin NAT »

## Fonctionnement

- [API du serveur WAPT 2.7](wapt-api.md) : endpoints lus et écrits, actions relayées aux agents, ce qui est exclu (Enterprise)
- [Prototype de signature](prototype-signature.md) : signature des actions et des paquets machine par `waptpython`, validée sur un agent réel

## Projet

- [Plan](../PLAN.md) : périmètre, architecture, sécurité, décisions
- [Feuille de route](../ROADMAP.md)
- Captures d'écran : `scripts/screenshots.py` les régénère dans `docs/images/` à partir de `scripts/demo_server.py` (données fictives)
