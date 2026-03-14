"""
Focus Discord Bot — Système FOMO
=================================
Commandes admin :
  !live <titre>         → Annonce live, aperçu 3 min, push notification
  !endlive [résumé]     → Termine le live, poste résumé partial dans canal public
  !livelog <texte>      → Poste une mise à jour en cours de live (public)
  !push <titre> <msg>   → Envoie push à tous les membres carte
  !stats                → Stats serveur + carte

Variables d'environnement requises :
  DISCORD_BOT_TOKEN
  APERCU_CHANNEL_ID       → #aperçu-live (visible free members)
  RESUME_CHANNEL_ID       → #résumé-membres (visible free members)
  STATUS_CHANNEL_ID       → #live-status (visible free members, bot édite le message)
  LIVE_VOICE_CHANNEL_ID   → Salon vocal/vidéo des lives
  ADMIN_ROLE_ID           → Rôle admin Focus
  PUSH_SECRET             → Secret API carte (MF2026FOCUS)
  CARD_API_URL            → URL de la carte (https://groupe-focus-card.vercel.app)
"""
import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import os
import time
import json

# ─── CONFIG ────────────────────────────────────────────────────────────────────
TOKEN              = os.environ["DISCORD_BOT_TOKEN"]
APERCU_CHANNEL_ID  = int(os.environ.get("APERCU_CHANNEL_ID",  "0"))
RESUME_CHANNEL_ID  = int(os.environ.get("RESUME_CHANNEL_ID",  "0"))
STATUS_CHANNEL_ID  = int(os.environ.get("STATUS_CHANNEL_ID",  "0"))
LIVE_VOICE_ID      = int(os.environ.get("LIVE_VOICE_CHANNEL_ID", "0"))
ADMIN_ROLE_ID      = int(os.environ.get("ADMIN_ROLE_ID", "0"))
LIVES_CHANNEL_ID   = int(os.environ.get("LIVES_CHANNEL_ID", "0"))
PUSH_SECRET        = os.environ.get("PUSH_SECRET", "MF2026FOCUS")
CARD_API           = os.environ.get("CARD_API_URL", "https://groupe-focus-card.vercel.app/api")
CARD_URL           = os.environ.get("CARD_URL", "https://groupe-focus-card.vercel.app")
JOIN_URL           = os.environ.get("JOIN_URL", "https://mentalitefocus.com/")

# ─── BOT ───────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members       = True
intents.voice_states  = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# State en mémoire
current_live = None        # dict | None
status_msg_id = None       # ID du message status éditable
apercu_msg_id = None       # ID du message aperçu

# ─── HELPERS ───────────────────────────────────────────────────────────────────
def is_admin(ctx):
    if ctx.author.guild_permissions.administrator:
        return True
    if ADMIN_ROLE_ID:
        return any(r.id == ADMIN_ROLE_ID for r in ctx.author.roles)
    return False

def members_in_voice():
    if not LIVE_VOICE_ID:
        return 0
    vc = bot.get_channel(LIVE_VOICE_ID)
    if not vc or not hasattr(vc, "members"):
        return 0
    return len([m for m in vc.members if not m.bot])

async def send_card_push(title: str, body: str, url: str = "/", tier: str = "ALL"):
    """Envoie une push notification via l'API de la carte."""
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{CARD_API}/push",
                json={"secret": PUSH_SECRET, "title": title, "body": body, "url": url, "tier": tier},
                timeout=aiohttp.ClientTimeout(total=10)
            )
    except Exception as e:
        print(f"Push error: {e}")

async def notify_live_api(action: str, title: str = "", stream_url: str = "", host: str = "Focus"):
    """Notifie l'API de la carte du statut du live (pour le preview player)."""
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{CARD_API}/live",
                json={"secret": PUSH_SECRET, "action": action, "title": title, "stream_url": stream_url, "host": host},
                timeout=aiohttp.ClientTimeout(total=10)
            )
    except Exception as e:
        print(f"Live API error: {e}")

# ─── EVENTS ────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Focus Bot connecté — {bot.user} (id:{bot.user.id})")
    if not update_live_status.is_running():
        update_live_status.start()
    if not check_scheduled_lives.is_running():
        check_scheduled_lives.start()

@bot.event
async def on_member_join(member):
    """Message de bienvenue automatique en DM + séquence J+1/J+7/J+14."""
    await asyncio.sleep(5)
    try:
        embed = discord.Embed(
            title="Bienvenue dans Focus 👋",
            description=(
                f"Salut **{member.display_name}** !\n\n"
                "Tu viens d'rejoindre le serveur public Focus.\n\n"
                "**Ce que tu peux faire maintenant :**\n"
                "→ Voir les aperçus des lives en direct\n"
                "→ Lire les résumés partiels des sessions\n"
                "→ Obtenir ta **carte fidélité gratuite**\n\n"
                "**Les lives complets, replays et la communauté active sont réservés aux membres.**\n\n"
                f"[🃏 Obtenir ma carte Focus gratuite]({CARD_URL})\n"
                f"[🚀 Rejoindre l'abonnement]({JOIN_URL})"
            ),
            color=0x0A0A0A
        )
        embed.set_footer(text="Focus Business · Entrepreneurs, pas salariés.")
        await member.send(embed=embed)
    except discord.Forbidden:
        pass  # DMs désactivés

    # Programmer les rappels J+7 et J+14
    asyncio.create_task(delayed_dm(member, days=7,
        title="Tu as raté 7 jours de lives 🔥",
        body=(
            f"Salut {member.display_name} — ça fait une semaine que tu es dans le serveur public.\n\n"
            "Cette semaine, les membres ont eu accès à plusieurs lives sur :\n"
            "• Comment structurer ton premier business en ligne\n"
            "• Les méthodes pour dépasser les 5K€/mois\n"
            "• Q&A en direct avec la communauté\n\n"
            "**Tu as raté tout ça.**\n\n"
            f"[Rejoindre Focus pour ne plus rien rater]({JOIN_URL})"
        )
    ))
    asyncio.create_task(delayed_dm(member, days=14,
        title="Offre spéciale 48h — Focus 🎯",
        body=(
            f"Salut {member.display_name},\n\n"
            "Tu es dans le serveur depuis 2 semaines — on te fait une offre une seule fois.\n\n"
            "**Premier mois à 4,95€** au lieu de 9,90€.\n"
            "Offre valable 48h uniquement.\n\n"
            f"[Saisir l'offre maintenant]({JOIN_URL}?promo=BIENVENUE50)"
        )
    ))

async def delayed_dm(member, days: int, title: str, body: str):
    await asyncio.sleep(days * 86400)
    # Vérifier que le membre est toujours là
    guild = member.guild
    if guild.get_member(member.id) is None:
        return
    try:
        embed = discord.Embed(title=title, description=body, color=0x0A0A0A)
        await member.send(embed=embed)
    except discord.Forbidden:
        pass

# ─── COMMANDE : !live ──────────────────────────────────────────────────────────
@bot.command(name="live")
async def cmd_live(ctx, *, args: str = ""):
    if not is_admin(ctx):
        return await ctx.send("❌ Accès refusé.")

    # Parser titre et stream_url optionnel
    # Usage: !live Titre du live | https://youtube.com/watch?v=xxx
    parts = args.split("|", 1)
    title      = parts[0].strip() or "Live Mentalité Focus"
    stream_url = parts[1].strip() if len(parts) > 1 else ""

    global current_live, apercu_msg_id

    host = ctx.author.display_name
    already_live = current_live is not None

    current_live = {
        "title":      title,
        "stream_url": stream_url,
        "start_ts":   current_live.get("start_ts", time.time()) if current_live else time.time(),
        "host":       host,
    }

    # 1) Notifier l'API carte (update titre si déjà live, sinon start)
    await notify_live_api("start", title=title, stream_url=stream_url, host=host)

    # 2) Push notification Focus Card — UNE SEULE FOIS
    if not already_live:
        await send_card_push(
            title=f"🔴 {title}",
            body=f"Par {host} — Rejoins maintenant",
            url="/?tab=live",
            tier="ALL"
        )
        print(f"[BOT] Push envoyée : {title}")
    else:
        print(f"[BOT] Live déjà actif, titre mis à jour : {title} (pas de re-push)")

    # 3) Post dans #aperçu-live
    apercu_ch = bot.get_channel(APERCU_CHANNEL_ID)
    if apercu_ch:
        embed = discord.Embed(color=0xC9A227)
        embed.description = (
            f"🔴 **EN DIRECT MAINTENANT**\n\n"
            f"**{title}**\n"
            f"🎙️ Par **{host}**\n\n"
            f"[Rejoindre le live]({JOIN_URL})"
        )
        msg = await apercu_ch.send(embed=embed)
        apercu_msg_id = msg.id

    await ctx.message.delete()
    await update_lives_channel()
    print(f"[BOT] Live démarré : {title}")

# ─── COMMANDE : !endlive ───────────────────────────────────────────────────────
@bot.command(name="endlive")
async def cmd_endlive(ctx, *, summary: str = ""):
    if not is_admin(ctx):
        return await ctx.send("❌ Accès refusé.")

    global current_live
    if not current_live:
        return await ctx.send("❌ Aucun live en cours.")

    title = current_live["title"]

    # 1) Notifier l'API carte (désactive le preview player)
    await notify_live_api("end")

    # 2) Post résumé dans le canal
    resume_ch = bot.get_channel(RESUME_CHANNEL_ID)
    if resume_ch:
        embed = discord.Embed(
            title=f"📋 {title} — Terminé",
            color=0xC9A227
        )
        if summary:
            points = [p.strip() for p in summary.split(";") if p.strip()]
            desc = "\n".join(f"✅ {p}" for p in points)
        else:
            desc = "Le live est terminé."
        desc += f"\n\n📲 [Voir tous les lives sur ta carte Focus]({CARD_URL})"
        embed.description = desc
        await resume_ch.send(embed=embed)

    current_live = None
    await ctx.message.delete()
    await update_lives_channel()
    print(f"[BOT] Live terminé : {title}")

# ─── COMMANDE : !livelog ───────────────────────────────────────────────────────
@bot.command(name="livelog")
async def cmd_livelog(ctx, *, text: str = ""):
    """Poste une mise à jour publique pendant le live (teaser de contenu)."""
    if not is_admin(ctx):
        return await ctx.send("❌ Accès refusé.")
    if not current_live:
        return await ctx.send("❌ Aucun live en cours.")

    apercu_ch = bot.get_channel(APERCU_CHANNEL_ID)
    if apercu_ch:
        nb = members_in_voice()
        embed = discord.Embed(color=0xFF6600)
        embed.description = (
            f"🔴 **{current_live['title']}** — En cours\n\n"
            f"_{text}_\n\n"
            f"👥 {nb} membres connectés · 🔒 Suite réservée aux membres\n\n"
            f"[Rejoindre le live complet]({JOIN_URL})"
        )
        await apercu_ch.send(embed=embed)
    await ctx.message.delete()

# ─── COMMANDE : !sujet — définir le sujet du live en cours ────────────────────
@bot.command(name="sujet")
async def cmd_sujet(ctx, *, titre: str = ""):
    """Change le sujet du live en cours et renvoie une push notification avec le vrai sujet."""
    if not is_admin(ctx):
        return await ctx.send("❌ Accès refusé.")
    if not current_live:
        return await ctx.send("❌ Aucun live en cours.")
    if not titre:
        return await ctx.send("Usage : `!sujet Le mindset des entrepreneurs d'élite`")

    old_title = current_live["title"]
    current_live["title"] = titre

    # Mettre à jour l'API live
    await notify_live_api("start", title=titre, host=current_live.get("host", "Focus"))

    # Pas de re-push pour un changement de sujet (éviter doublons)

    # Mettre à jour l'embed dans #aperçu-live
    apercu_ch = bot.get_channel(APERCU_CHANNEL_ID)
    if apercu_ch and apercu_msg_id:
        try:
            msg = await apercu_ch.fetch_message(apercu_msg_id)
            nb = members_in_voice()
            embed = discord.Embed(title=f"🔴 {titre}", color=0xFF0000)
            embed.description = (
                "**Le live vient de démarrer.**\n\n"
                f"👥 **{nb} membres** connectés en ce moment\n\n"
                "🔒 Réservé aux membres Focus\n\n"
                f"[🃏 Ouvrir ma carte]({CARD_URL}/?tab=live)  ·  [🚀 Rejoindre Focus]({JOIN_URL})"
            )
            embed.set_footer(text="Mentalité Focus")
            await msg.edit(embed=embed)
        except Exception:
            pass

    await ctx.send(f"✅ Sujet mis à jour : **{titre}**\n📲 Push notification envoyée à tous les abonnés.", delete_after=10)
    await ctx.message.delete()
    print(f"[BOT] Sujet live changé : {old_title} → {titre}")

# ─── COMMANDE : !planlive — programmer un futur live ──────────────────────────
@bot.command(name="planlive")
async def cmd_planlive(ctx, *, args: str = ""):
    """Programme un live futur.
    Usage: !planlive Titre du live | Présentateur | JJ/MM à HH:MM
    Ex:    !planlive Automatisation Campagne Mail 🚀📧 | VALD | 15/03 à 20:30
    """
    if not is_admin(ctx):
        return await ctx.send("❌ Accès refusé.")
    if not args or "|" not in args:
        return await ctx.send("Usage : `!planlive Titre 🔥 | Présentateur | JJ/MM à HH:MM`")

    parts = [p.strip() for p in args.split("|")]
    if len(parts) < 3:
        return await ctx.send("Usage : `!planlive Titre 🔥 | Présentateur | JJ/MM à HH:MM`")

    title = parts[0]
    host = parts[1]
    date_str = parts[2]

    # Parser la date (format JJ/MM à HH:MM)
    import re
    m = re.match(r"(\d{1,2})/(\d{1,2})\s*[àa]\s*(\d{1,2})[h:](\d{2})", date_str)
    if not m:
        return await ctx.send("Format date invalide. Utilise : `JJ/MM à HH:MM` (ex: 15/03 à 20:30)")

    from datetime import datetime, timezone, timedelta
    day, month, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    year = datetime.now().year
    paris = timedelta(hours=1)
    dt_paris = datetime(year, month, day, hour, minute, 0)
    dt_utc = dt_paris - paris
    ts = dt_utc.replace(tzinfo=timezone.utc).timestamp()

    # Enregistrer dans l'API
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{CARD_API}/live",
                json={"secret": PUSH_SECRET, "action": "schedule", "title": title, "host": host, "scheduled_at": ts},
                timeout=aiohttp.ClientTimeout(total=10)
            )
    except Exception as e:
        print(f"planlive API error: {e}")

    await ctx.send(f"✅ Live programmé !\n🎙️ **{title}**\n👤 Par **{host}**\n📅 **{date_str}**", delete_after=15)
    await ctx.message.delete()

    # Mettre à jour le canal programme
    await update_lives_channel()
    print(f"[BOT] Live programmé : {title} par {host} le {date_str}")

# ─── MISE A JOUR DU CANAL PROGRAMME LIVES ────────────────────────────────────
_lives_msg_id = None

async def update_lives_channel():
    """Met à jour le canal #programme-lives avec tous les lives."""
    global _lives_msg_id
    if not LIVES_CHANNEL_ID:
        return
    ch = bot.get_channel(LIVES_CHANNEL_ID)
    if not ch:
        return

    # Charger les lives depuis l'API
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{CARD_API}/live", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
    except:
        return

    history = data.get("history", [])
    current = data.get("current", {})

    # Trier par date
    scheduled = [l for l in history if l.get("status") == "scheduled"]
    ended = [l for l in history if l.get("status") == "ended"]
    scheduled.sort(key=lambda x: x.get("scheduled_at", 0))
    ended.sort(key=lambda x: x.get("started_at", 0), reverse=True)

    from datetime import datetime, timezone, timedelta

    # Construire l'embed
    embed = discord.Embed(
        title="📋 PROGRAMME DES LIVES",
        color=0xC9A227
    )

    # Live en cours
    if current.get("active"):
        embed.add_field(
            name="🔴 EN DIRECT MAINTENANT",
            value=f"**{current.get('title', 'Live Focus')}**\n🎙️ {current.get('host', 'Focus')}",
            inline=False
        )

    # Lives à venir
    if scheduled:
        upcoming = ""
        for l in scheduled[:10]:
            ts = l.get("scheduled_at", 0)
            dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=1)))
            date_str = dt.strftime("%d/%m à %Hh%M")
            upcoming += f"⏰ **{l.get('title', 'Live')}**\n   🎙️ {l.get('host', 'Focus')} · 📅 {date_str}\n\n"
        embed.add_field(name="📅 LIVES À VENIR", value=upcoming, inline=False)
    else:
        embed.add_field(name="📅 LIVES À VENIR", value="_Aucun live programmé pour le moment_", inline=False)

    # Historique
    if ended:
        hist = ""
        for l in ended[:10]:
            ts = l.get("started_at", 0)
            dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=1)))
            date_str = dt.strftime("%d/%m à %Hh%M")
            hist += f"✅ **{l.get('title', 'Live')}** — {l.get('host', 'Focus')} · {date_str}\n"
        embed.add_field(name="📼 LIVES PASSÉS", value=hist, inline=False)

    embed.set_footer(text=f"Dernière mise à jour · {datetime.now(tz=timezone(timedelta(hours=1))).strftime('%d/%m %H:%M')}")

    # Éditer ou envoyer le message
    try:
        if _lives_msg_id:
            try:
                msg = await ch.fetch_message(_lives_msg_id)
                await msg.edit(embed=embed)
                return
            except:
                pass

        # Chercher un message existant du bot
        async for msg in ch.history(limit=10):
            if msg.author == bot.user and msg.embeds:
                await msg.edit(embed=embed)
                _lives_msg_id = msg.id
                return

        # Sinon créer
        msg = await ch.send(embed=embed)
        _lives_msg_id = msg.id
    except Exception as e:
        print(f"[BOT] update_lives_channel error: {e}")

# ─── COMMANDE : !push ─────────────────────────────────────────────────────────
@bot.command(name="push")
async def cmd_push(ctx, title: str = "", *, body: str = ""):
    if not is_admin(ctx):
        return await ctx.send("❌ Accès refusé.")
    if not title:
        return await ctx.send("Usage : !push \"Titre\" message complet")
    await send_card_push(title=title, body=body, url="/", tier="ALL")
    await ctx.send(f"✅ Push envoyé : {title}", delete_after=5)

# ─── COMMANDE : !stats ────────────────────────────────────────────────────────
@bot.command(name="stats")
async def cmd_stats(ctx):
    if not is_admin(ctx):
        return
    guild = ctx.guild
    total  = guild.member_count
    online = sum(1 for m in guild.members if m.status != discord.Status.offline)
    voice  = members_in_voice()

    embed = discord.Embed(title="📊 Stats Focus Discord", color=0x0A0A0A)
    embed.add_field(name="Membres total", value=str(total), inline=True)
    embed.add_field(name="En ligne",      value=str(online), inline=True)
    embed.add_field(name="Live en ce moment", value=str(voice), inline=True)
    embed.add_field(name="Live en cours", value=current_live["title"] if current_live else "Aucun", inline=False)
    await ctx.send(embed=embed)

# ─── TÂCHE : rappel 10 min avant les lives programmés ─────────────────────────
_notified_lives = set()  # IDs des lives pour lesquels le rappel a déjà été envoyé

@tasks.loop(minutes=1)
async def check_scheduled_lives():
    """Vérifie les lives programmés et envoie un rappel 10 min avant."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{CARD_API}/live", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()

        history = data.get("history", [])
        now = time.time()

        for live in history:
            if live.get("status") != "scheduled":
                continue
            lid = live.get("id", "")
            scheduled_at = live.get("scheduled_at", 0)
            time_until = scheduled_at - now

            # Rappel 10 min avant (entre 9 et 11 min)
            if 540 < time_until < 660 and lid not in _notified_lives:
                _notified_lives.add(lid)
                title = live.get("title", "Live Focus")
                host = live.get("host", "Focus")

                # Push notification à tous les abonnés
                await send_card_push(
                    title=f"⏰ Live dans 10 min — {host}",
                    body=f"{title}",
                    url="/?tab=live",
                    tier="ALL"
                )

                # Post dans #aperçu-live
                apercu_ch = bot.get_channel(APERCU_CHANNEL_ID)
                if apercu_ch:
                    embed = discord.Embed(title=f"⏰ LIVE DANS 10 MINUTES", color=0xFFAA00)
                    embed.description = (
                        f"**{title}**\n\n"
                        f"🎙️ Présenté par **{host}**\n"
                        f"🕐 Début à **20h30**\n\n"
                        f"Prépare-toi, ça va démarrer !\n\n"
                        f"[🃏 Ouvrir ma carte]({CARD_URL}/?tab=live)  ·  [🚀 Rejoindre Focus]({JOIN_URL})"
                    )
                    embed.set_footer(text="Mentalité Focus")
                    await apercu_ch.send(embed=embed)

                print(f"[BOT] ⏰ Rappel envoyé : {title} par {host} dans 10 min")
    except Exception as e:
        print(f"[BOT] check_scheduled error: {e}")

@check_scheduled_lives.before_loop
async def before_check_scheduled():
    await bot.wait_until_ready()

# ─── TÂCHE : statut live mis à jour toutes les 5 min ─────────────────────────
@tasks.loop(minutes=5)
async def update_live_status():
    """Met à jour le canal #live-status avec le compteur en temps réel."""
    if not STATUS_CHANNEL_ID:
        return
    ch = bot.get_channel(STATUS_CHANNEL_ID)
    if not ch:
        return

    nb = members_in_voice()

    if current_live:
        content = (
            f"🔴 **LIVE EN COURS** — {current_live['title']}\n"
            f"👥 **{nb} membres** connectés en ce moment\n\n"
            f"_Réservé aux membres Focus_\n"
            f"[🃏 Ouvrir ma carte]({CARD_URL}/?tab=live) · [🚀 Rejoindre Focus]({JOIN_URL})"
        )
    else:
        content = (
            f"⚫ Pas de live en ce moment\n\n"
            f"📅 Les lives arrivent presque tous les soirs.\n"
            f"Ne rate pas le prochain → [obtiens ta carte gratuite]({CARD_URL})"
        )

    # Essayer d'éditer le dernier message, sinon recréer
    try:
        async for msg in ch.history(limit=5):
            if msg.author == bot.user:
                await msg.edit(content=content)
                return
        # Aucun message existant
        await ch.send(content)
    except Exception:
        pass

# ─── AUTO-DETECT : stream/live démarré dans un salon vocal ────────────────────
@bot.event
async def on_voice_state_update(member, before, after):
    """Détecte automatiquement quand un admin lance un stream/live."""
    global current_live, apercu_msg_id

    # Ignorer les bots
    if member.bot:
        return

    print(f"[VOX] {member.display_name} | before={before.channel} stream={getattr(before,'self_stream',False)} | after={after.channel} stream={getattr(after,'self_stream',False)}", flush=True)

    # Vérifier que c'est un admin ou le propriétaire du serveur
    is_adm = member.guild_permissions.administrator
    if ADMIN_ROLE_ID and not is_adm:
        is_adm = any(r.id == ADMIN_ROLE_ID for r in member.roles)
    if not is_adm:
        print(f"[VOX] {member.display_name} n'est pas admin, ignoré", flush=True)
        return

    # Détecter : admin rejoint un vocal OU lance un stream/vidéo
    was_in_voice  = before.channel is not None
    now_in_voice  = after.channel is not None
    was_streaming = getattr(before, "self_stream", False) or getattr(before, "self_video", False)
    now_streaming = getattr(after, "self_stream", False) or getattr(after, "self_video", False)

    # Trigger : rejoint un vocal, OU lance un stream/vidéo
    just_joined   = now_in_voice and not was_in_voice
    just_streamed = now_streaming and not was_streaming

    if (just_joined or just_streamed) and not current_live:
        title = f"Live de {member.display_name}"
        print(f"[BOT] 🔴 Auto-détection : {member.display_name} a lancé un stream !")

        current_live = {
            "title":      title,
            "stream_url": "",
            "start_ts":   time.time(),
            "host":       member.display_name,
        }

        # Juste notifier l'API (pas de push — attendre !live pour le vrai titre)
        await notify_live_api("start", title=title)
        print(f"[BOT] Auto-détection : live créé, en attente de !live pour la push")

    # Détecter le STOP : quitte le vocal OU arrête le stream
    just_left = was_in_voice and not now_in_voice
    just_stopped = was_streaming and not now_streaming

    if (just_left or just_stopped) and current_live:
        if current_live.get("host") == member.display_name:
            title = current_live["title"]
            print(f"[BOT] ⚫ Auto-détection : {member.display_name} a arrêté le stream.")

            await notify_live_api("end")

            current_live = None
            await update_lives_channel()
            print(f"[BOT] Live terminé (auto) : {title}")

bot.run(TOKEN)
