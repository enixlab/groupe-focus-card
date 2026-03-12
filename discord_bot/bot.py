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
PUSH_SECRET        = os.environ.get("PUSH_SECRET", "MF2026FOCUS")
CARD_API           = os.environ.get("CARD_API_URL", "https://groupe-focus-card.vercel.app/api")
CARD_URL           = os.environ.get("CARD_URL", "https://groupe-focus-card.vercel.app")
JOIN_URL           = os.environ.get("JOIN_URL", "https://focus-business.com")

# ─── BOT ───────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members       = True
intents.voice_states  = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# State en mémoire
current_live = None        # dict | None
status_msg_id = None       # ID du message status éditable
apercu_msg_id = None       # ID du message aperçu (pour l'éditer à la coupure)

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

async def notify_live_api(action: str, title: str = "", stream_url: str = ""):
    """Notifie l'API de la carte du statut du live (pour le preview player)."""
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{CARD_API}/live",
                json={"secret": PUSH_SECRET, "action": action, "title": title, "stream_url": stream_url},
                timeout=aiohttp.ClientTimeout(total=10)
            )
    except Exception as e:
        print(f"Live API error: {e}")

# ─── EVENTS ────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Focus Bot connecté — {bot.user} (id:{bot.user.id})")
    update_live_status.start()

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
            "• Q&A direct avec Adil\n\n"
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
    current_live = {
        "title":      title,
        "stream_url": stream_url,
        "start_ts":   time.time(),
        "host":       ctx.author.display_name,
    }

    # 1) Notifier l'API carte (active le preview player)
    await notify_live_api("start", title=title, stream_url=stream_url)

    # 2) Push notification vers TOUS les abonnés carte
    await send_card_push(
        title=f"🔴 LIVE — {title}",
        body="Adil est en direct. Aperçu gratuit 3 min → ouvre ta carte Focus.",
        url="/?tab=live",
        tier="ALL"
    )

    # 3) Post dans #aperçu-live
    apercu_ch = bot.get_channel(APERCU_CHANNEL_ID)
    if apercu_ch:
        nb = members_in_voice()
        embed = discord.Embed(
            title=f"🔴 {title}",
            color=0xFF0000
        )
        embed.description = (
            "**Le live vient de démarrer.**\n\n"
            f"👥 **{nb} membres** connectés en ce moment\n\n"
            "✅ Aperçu gratuit : **3 premières minutes** disponibles sur ta carte\n"
            "🔒 Live complet → membres uniquement\n\n"
            f"[🃏 Voir l'aperçu sur ma carte]({CARD_URL}/?tab=live)  ·  [🚀 Rejoindre Focus]({JOIN_URL})"
        )
        embed.set_footer(text="Après 3 min, le live continue uniquement pour les membres.")
        msg = await apercu_ch.send(embed=embed)
        apercu_msg_id = msg.id

        # Tâche : coupure après 3 min
        asyncio.create_task(post_cutoff(apercu_ch, title))

    await ctx.message.delete()
    print(f"[BOT] Live démarré : {title}")

async def post_cutoff(channel, title: str):
    """Poste le message de coupure 3 min après le début du live."""
    await asyncio.sleep(180)  # 3 minutes
    embed = discord.Embed(
        title="⛔ Aperçu terminé",
        color=0x333333
    )
    embed.description = (
        f"Les **3 premières minutes** de « **{title}** » sont écoulées.\n\n"
        "**Le live continue pour les membres.**\n\n"
        f"→ [Rejoindre Focus à 9,90€/mois]({JOIN_URL})\n"
        f"→ [Obtenir ta carte fidélité]({CARD_URL})"
    )
    embed.set_footer(text="Ne rate plus aucun live → rejoins Focus")
    await channel.send(embed=embed)

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

    # 2) Post résumé partiel dans #résumé-membres
    resume_ch = bot.get_channel(RESUME_CHANNEL_ID)
    if resume_ch:
        embed = discord.Embed(
            title=f"📋 Résumé — {title}",
            color=0x0A0A0A
        )
        if summary:
            points = [p.strip() for p in summary.split(";") if p.strip()]
            desc = "**Points abordés ce soir :**\n\n"
            desc += "\n".join(f"✅ {p}" for p in points)
        else:
            desc = (
                "**Points abordés ce soir :**\n\n"
                "✅ Méthodes concrètes partagées\n"
                "✅ Q&A avec Adil\n"
                "✅ Ressources exclusives\n\n"
                "_Résumé partiel — le contenu complet est disponible en replay._"
            )
        desc += (
            f"\n\n🔒 **Replay complet réservé aux membres.**\n\n"
            f"→ [Accéder au replay + tous les lives]({JOIN_URL})\n"
            f"→ [Obtenir ta carte Focus]({CARD_URL})"
        )
        embed.description = desc
        embed.set_footer(text="Focus Business · Ne rate plus rien → rejoins l'abonnement")
        await resume_ch.send(embed=embed)

    # 3) Push notification de fin
    await send_card_push(
        title=f"📋 Live terminé — {title}",
        body="Résumé disponible. Replay complet pour les membres.",
        url="/?tab=live",
        tier="ALL"
    )

    current_live = None
    await ctx.message.delete()
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
            f"_Aperçu 3 min gratuit · Live complet → membres uniquement_\n"
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

bot.run(TOKEN)
