# Focus Discord Bot — Installation

## Prérequis
```bash
pip install -r requirements.txt
```

## Variables d'environnement (.env)
```env
DISCORD_BOT_TOKEN=ton_token_bot_discord
APERCU_CHANNEL_ID=ID_du_canal_apercu-live
RESUME_CHANNEL_ID=ID_du_canal_resume-membres
STATUS_CHANNEL_ID=ID_du_canal_live-status
LIVE_VOICE_CHANNEL_ID=ID_du_salon_vocal_live
ADMIN_ROLE_ID=ID_du_role_admin
PUSH_SECRET=MF2026FOCUS
CARD_API_URL=https://groupe-focus-card.vercel.app/api
CARD_URL=https://groupe-focus-card.vercel.app
JOIN_URL=https://focus-business.com
```

## Lancer le bot
```bash
python bot.py
```

## Commandes admin

| Commande | Usage | Description |
|----------|-------|-------------|
| `!live` | `!live Titre du live \| https://youtube.com/watch?v=xxx` | Démarre un live : post aperçu public, push notification carte, active le preview player |
| `!endlive` | `!endlive Point 1; Point 2; Point 3` | Termine le live, poste résumé partiel dans #résumé-membres |
| `!livelog` | `!livelog On vient de voir comment faire X...` | Poste un teaser en cours de live dans #aperçu-live |
| `!push` | `!push "Titre" Corps du message` | Push notification manuelle vers tous les abonnés carte |
| `!stats` | `!stats` | Stats serveur + live en cours |

## Canaux Discord à créer

1. **#aperçu-live** — Visible par tous (free + payants). Le bot y poste l'annonce du live + l'aperçu 3 min + la coupure.
2. **#résumé-membres** — Visible par tous. Le bot y poste les résumés partiels après chaque live.
3. **#live-status** — Visible par tous. Le bot édite un seul message pour afficher le statut en temps réel.
4. **Salon vocal Live** — Réservé aux membres payants. Le bot compte les membres présents.

## Flux FOMO

```
Admin tape !live "Titre" | youtube_url
    ↓
Bot poste dans #aperçu-live avec embed rouge 🔴
    ↓
Bot envoie push notification → téléphones des abonnés carte
    ↓
Bot notifie l'API carte → active le preview player 3 min
    ↓
3 minutes plus tard → bot poste la coupure ⛔
    ↓
Free members voient "Live continue pour les membres" → paywall
```

## IP Blocking (preview player carte)

- 1 aperçu de 3 min par IP par 24h
- 3 tentatives de contournement → ban 7 jours
- Double vérification : IP + canvas fingerprint
- Les bans sont stockés dans `live_sessions.json` dans le repo GitHub
