"""
bot.py — Hauptdatei: Bot-Setup, Slash Commands, Event Handler
Vinted Discord Snipe Bot (Python)
"""

import asyncio
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import os
import json

from scraper import start_filter_task, stop_filter_task, running_tasks
from storage import (
    load_filters, save_filter, remove_filter,
    load_user_tokens, save_user_token, get_user_token
)
from embeds import ItemView

load_dotenv()

# ─── Konfiguration ────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
VINTED_COOKIES    = os.getenv("VINTED_COOKIES", "")
VINTED_DOMAIN     = os.getenv("VINTED_DOMAIN", "vinted.de")
POLL_INTERVAL     = int(os.getenv("POLL_INTERVAL", "4"))
BOT_OWNER_ID      = int(os.getenv("BOT_OWNER_ID", "0"))

# ─── Bot-Instanz ──────────────────────────────────────────────────────────────
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


# ─── Token Auto-Refresh ───────────────────────────────────────────────────────

async def refresh_vinted_token_loop():
    """
    Erneuert den Vinted access_token automatisch alle 90 Minuten
    via POST /oauth/token (funktioniert server-seitig ohne Browser).
    """
    global VINTED_COOKIES
    while True:
        await asyncio.sleep(90 * 60)
        try:
            cookies_dict = {}
            for part in VINTED_COOKIES.split(';'):
                part = part.strip()
                if '=' in part:
                    k, v = part.split('=', 1)
                    cookies_dict[k.strip()] = v.strip()

            refresh_token = cookies_dict.get('refresh_token_web', '')
            if not refresh_token:
                print('[Token] ⚠️ Kein refresh_token_web gefunden')
                continue

            body = (
                'grant_type=refresh_token&client_id=web&scope=user&refresh_token='
                + refresh_token
            )
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f'https://www.{VINTED_DOMAIN}/oauth/token',
                    data=body,
                    headers={
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': 'application/json',
                        'Origin': f'https://www.{VINTED_DOMAIN}',
                        'Referer': f'https://www.{VINTED_DOMAIN}/',
                    },
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        new_access  = data.get('access_token', '')
                        new_refresh = data.get('refresh_token', refresh_token)
                        if new_access:
                            VINTED_COOKIES = (
                                f'access_token_web={new_access}; '
                                f'refresh_token_web={new_refresh}'
                            )
                            print('[Token] ✅ Vinted Token erneuert')
                        else:
                            print('[Token] ⚠️ Kein access_token in Response')
                    else:
                        txt = await resp.text()
                        print(f'[Token] ❌ HTTP {resp.status}: {txt[:80]}')
        except Exception as e:
            print(f'[Token] Fehler: {e}')


# ─── Events ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"[Bot] ✅ Eingeloggt als {bot.user} (ID: {bot.user.id})")
    await tree.sync()
    print("[Bot] Slash Commands synchronisiert.")
    asyncio.create_task(refresh_vinted_token_loop())
    print("[Bot] Token Auto-Refresh gestartet (alle 90 Min).")

    filters = load_filters()
    print(f"[Bot] Lade {len(filters)} gespeicherte Filter...")
    for f in filters.values():
        channel = bot.get_channel(int(f["channel_id"]))
        if channel:
            await start_filter_task(f, channel, VINTED_COOKIES, bot,
                                    VINTED_DOMAIN, POLL_INTERVAL, BOT_OWNER_ID)
            print(f"[Bot] Filter '{f['filter_id']}' gestartet in #{channel.name}")

    bot.add_view(ItemView(item_id=0, item_url="", vinted_domain=VINTED_DOMAIN))
    print("[Bot] Bereit.")


# ─── /setup ───────────────────────────────────────────────────────────────────

@tree.command(name="setup", description="Verknüpfe deinen Vinted Account für Kaufen & Liken-Buttons.")
@app_commands.describe(cookie="Dein Vinted Cookie-String (F12 → Network → Cookie: Zeile).")
async def cmd_setup(interaction: discord.Interaction, cookie: str):
    save_user_token(interaction.user.id, cookie)
    await interaction.response.send_message(
        "✅ Vinted Account verknüpft! Du kannst jetzt 🛒 Kaufen und ❤️ Liken.",
        ephemeral=True
    )


# ─── /filter ──────────────────────────────────────────────────────────────────

filter_group = app_commands.Group(name="filter", description="Vinted-Suchfilter verwalten.")
tree.add_command(filter_group)


@filter_group.command(name="add", description="Neuen Suchfilter hinzufügen und sofort starten.")
@app_commands.describe(
    channel="Discord-Channel für neue Artikel",
    keywords="Suchbegriffe (z.B. 'Nike Air Max 90')",
    max_price="Maximaler Preis in Euro (optional)",
    brand="Marke (optional)",
)
async def filter_add(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    keywords: str,
    max_price: float = None,
    brand: str = None,
):
    import uuid
    filter_id = str(uuid.uuid4())[:8]
    filter_config = {
        "filter_id": filter_id,
        "channel_id": str(channel.id),
        "keywords": keywords,
        "max_price": max_price,
        "brand": brand,
        "catalog_id": "",
    }
    save_filter(filter_id, filter_config)
    await start_filter_task(filter_config, channel, VINTED_COOKIES, bot,
                            VINTED_DOMAIN, POLL_INTERVAL, BOT_OWNER_ID)

    embed = discord.Embed(title="✅ Filter hinzugefügt", color=0x00C853)
    embed.add_field(name="🆔 Filter-ID", value=f"`{filter_id}`", inline=True)
    embed.add_field(name="🔍 Keywords", value=keywords, inline=True)
    embed.add_field(name="📺 Channel", value=channel.mention, inline=True)
    if max_price:
        embed.add_field(name="💰 Max. Preis", value=f"{max_price:.2f} €", inline=True)
    if brand:
        embed.add_field(name="🏷️ Marke", value=brand, inline=True)
    embed.set_footer(text=f"Polling alle {POLL_INTERVAL}s · Token-Refresh alle 90 Min")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@filter_group.command(name="list", description="Alle aktiven Filter anzeigen.")
async def filter_list(interaction: discord.Interaction):
    filters = load_filters()
    if not filters:
        await interaction.response.send_message(
            "📭 Keine Filter aktiv. Nutze `/filter add`.", ephemeral=True
        )
        return
    embed = discord.Embed(title=f"🔍 Aktive Filter ({len(filters)})", color=0x2196F3)
    for fid, f in filters.items():
        channel = bot.get_channel(int(f["channel_id"]))
        ch = channel.mention if channel else f"ID:{f['channel_id']}"
        running = fid in running_tasks and not running_tasks[fid].done()
        parts = [f"📺 {ch}", f"🔍 `{f.get('keywords','-')}`"]
        if f.get("max_price"):
            parts.append(f"💰 {f['max_price']:.2f}€")
        parts.append("🟢 Aktiv" if running else "🔴 Gestoppt")
        embed.add_field(name=f"`{fid}`", value=" · ".join(parts), inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@filter_group.command(name="remove", description="Filter löschen und stoppen.")
@app_commands.describe(filter_id="Die Filter-ID (aus /filter list)")
async def filter_remove(interaction: discord.Interaction, filter_id: str):
    if filter_id not in load_filters():
        await interaction.response.send_message(f"❌ Filter `{filter_id}` nicht gefunden.", ephemeral=True)
        return
    await stop_filter_task(filter_id)
    remove_filter(filter_id)
    await interaction.response.send_message(f"✅ Filter `{filter_id}` gestoppt und gelöscht.", ephemeral=True)


# ─── /status ──────────────────────────────────────────────────────────────────

@tree.command(name="status", description="Bot-Status und aktive Tasks anzeigen.")
async def cmd_status(interaction: discord.Interaction):
    filters = load_filters()
    active = sum(1 for t in running_tasks.values() if not t.done())
    embed = discord.Embed(title="📊 Bot Status", color=0x9C27B0)
    embed.add_field(name="🤖 Bot", value=str(bot.user), inline=True)
    embed.add_field(name="🔍 Filter", value=str(len(filters)), inline=True)
    embed.add_field(name="▶️ Aktiv", value=str(active), inline=True)
    embed.add_field(name="⏱️ Poll", value=f"{POLL_INTERVAL}s", inline=True)
    embed.add_field(name="🌐 Domain", value=VINTED_DOMAIN, inline=True)
    embed.add_field(name="🍪 Cookie", value="✅" if VINTED_COOKIES else "❌", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ─── Bot starten ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        print("❌ DISCORD_BOT_TOKEN fehlt!")
        exit(1)
    bot.run(DISCORD_BOT_TOKEN)
