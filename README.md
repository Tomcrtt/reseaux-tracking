# Réseaux Tracking — Setup

## Variables d'environnement à configurer sur Railway

| Variable | Valeur |
|----------|--------|
| `NOTION_TOKEN` | Token de ton intégration Notion |
| `IG_ACCESS_TOKEN` | Token Meta/Instagram |
| `IG_USER_ID` | Ton ID numérique Instagram (ctom.scalee) |
| `ANTHROPIC_API_KEY` | Ta clé API Anthropic |
| `DB_IG_VIDEO` | `3fc014eaff164b8bbcb3f80f2fdc2bf8` |
| `DB_LINKEDIN` | `16c5da1dd5974ca5b80cedc5681a7d46` |
| `DB_HOOKS` | `34b74dbbcdbe8050bd7cc9ad8a409d16` |
| `LINKEDIN_TOKEN` | Token LinkedIn (à configurer plus tard) |
| `LINKEDIN_URN` | URN LinkedIn ex: urn:li:person:XXXXX |

## Cron schedule
Le script tourne tous les jours à 10h UTC = 12h heure française (CEST).
Configuré dans railway.toml : `0 10 * * *`

## Ce que fait le script
1. Récupère tous les posts IG VIDEO/REEL postés depuis +24h
2. Récupère les métriques (vues, likes, rétention)
3. Extrait hook et CTA depuis la caption
4. Génère une leçon + recommandation avec Claude AI
5. Met à jour ou crée les entrées dans Notion
6. Met à jour le tracker de hooks
7. Fait pareil pour LinkedIn (si token configuré)
