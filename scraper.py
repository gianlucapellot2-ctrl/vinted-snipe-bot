"""
scraper.py — Vinted API Calls und Polling Loop
"""

import aiohttp
import asyncio
from embeds import build_embed

# Globales Dict: filter_id → asyncio.Task
running_tasks: dict[str, asyncio.Task] = {}


def get_headers(cookies: str, domain: str = "vinted.de") -> dict:
    """Baut den vollständigen Header-Dict für Vinted API Calls."""
    return {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/16.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": f"https://www.{domain}",
        "Referer": f"https://www.{domain}/",
        "Cookie": cookies,
        "X-Requested-With": "XMLHttpRequest",
    }


async def fetch_items(
    session: aiohttp.ClientSession,
    filter_config: dict,
    cookies: str,
    domain: str
) -> list[dict]:
    """
    Ruft neue Artikel von der Vinted Catalog API ab.
    Wirft Exceptions bei 401 (Token abgelaufen) und 429 (Rate Limit).
    """
    params = {
        "per_page": 96,
        "page": 1,
        "order": "newest_first",
    }

    # Nur nicht-leere Parameter hinzufügen
    if filter_config.get("keywords"):
        params["search_text"] = filter_config["keywords"]
    if filter_config.get("catalog_id"):
        params["catalog_ids"] = filter_config["catalog_id"]
    if filter_config.get("max_price"):
        params["price_to"] = str(filter_config["max_price"])
    if filter_config.get("brand"):
        params["brand_ids"] = filter_config["brand"]  # Vinted erwartet IDs, String als Fallback

    url = f"https://www.{domain}/api/v2/catalog/items"

    async with session.get(url, headers=get_headers(cookies, domain), params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        if resp.status == 401:
            raise Exception("TOKEN_EXPIRED")
        if resp.status == 429:
            raise Exception("RATE_LIMITED")
        if resp.status != 200:
            raise Exception(f"HTTP_{resp.status}")

        data = await resp.json()
        return data.get("items", [])


async def post_item(item: dict, channel, bot, vinted_domain: str):
    """Postet ein einzelnes Item als Embed mit Buttons in den Channel."""
    try:
        embed, view = await build_embed(item, vinted_domain)
        await channel.send(embed=embed, view=view)
    except Exception as e:
        print(f"[Scraper] ⚠️ Fehler beim Posten von Item {item.get('id', '?')}: {e}")


async def poll_loop(
    filter_config: dict,
    channel,
    cookies: str,
    bot,
    domain: str,
    poll_interval: int,
    bot_owner_id: int
):
    """
    Haupt-Polling-Loop für einen einzelnen Filter.
    Läuft dauerhaft bis zum Abbruch (task.cancel()).
    """
    filter_id = filter_config["filter_id"]
    seen_ids: set[int] = set()
    first_run = True
    consecutive_errors = 0

    print(f"[Scraper] 🟢 Filter '{filter_id}' gestartet — Keywords: {filter_config.get('keywords', '-')}")

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                items = await fetch_items(session, filter_config, cookies, domain)

                if first_run:
                    # Beim allerersten Durchlauf: bestehende IDs merken, NICHT posten
                    seen_ids = {item["id"] for item in items}
                    first_run = False
                    print(f"[Scraper] Filter '{filter_id}' initialisiert mit {len(seen_ids)} bekannten Items.")
                else:
                    # Nur neue Items posten (nicht in seen_ids)
                    new_items = [item for item in items if item["id"] not in seen_ids]
                    for item in reversed(new_items):  # Ältestes zuerst posten
                        seen_ids.add(item["id"])
                        await post_item(item, channel, bot, domain)
                        if len(new_items) > 1:
                            await asyncio.sleep(0.5)  # Kurze Pause zwischen mehreren Posts

                consecutive_errors = 0  # Fehler-Counter zurücksetzen
                await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                # Task wurde absichtlich gestoppt (z.B. /filter remove)
                print(f"[Scraper] 🔴 Filter '{filter_id}' gestoppt.")
                return

            except Exception as e:
                error_str = str(e)

                if "TOKEN_EXPIRED" in error_str:
                    print(f"[Scraper] ❌ Token abgelaufen! Filter '{filter_id}' wird gestoppt.")
                    # DM an Bot-Owner senden
                    if bot_owner_id:
                        try:
                            owner = await bot.fetch_user(bot_owner_id)
                            await owner.send(
                                f"⚠️ **Vinted Token abgelaufen!**\n"
                                f"Filter `{filter_id}` ({filter_config.get('keywords', '-')}) ist gestoppt.\n"
                                f"Bitte `.env` aktualisieren und Bot neu starten."
                            )
                        except Exception as dm_err:
                            print(f"[Scraper] DM-Fehler: {dm_err}")
                    return

                elif "RATE_LIMITED" in error_str:
                    print(f"[Scraper] ⏳ Rate-Limit — Filter '{filter_id}' wartet 30s...")
                    await asyncio.sleep(30)

                else:
                    consecutive_errors += 1
                    wait_time = min(10 * consecutive_errors, 120)  # Exponentiell, max 2 Min
                    print(f"[Scraper] ⚠️ Fehler in Filter '{filter_id}': {error_str} — Warte {wait_time}s (Fehler #{consecutive_errors})")
                    await asyncio.sleep(wait_time)


async def start_filter_task(
    filter_config: dict,
    channel,
    cookies: str,
    bot,
    domain: str,
    poll_interval: int,
    bot_owner_id: int
):
    """Erstellt und startet einen asyncio.Task für einen Filter."""
    filter_id = filter_config["filter_id"]

    # Alten Task stoppen falls vorhanden
    if filter_id in running_tasks and not running_tasks[filter_id].done():
        running_tasks[filter_id].cancel()
        await asyncio.sleep(0.1)

    task = asyncio.create_task(
        poll_loop(filter_config, channel, cookies, bot, domain, poll_interval, bot_owner_id),
        name=f"filter_{filter_id}"
    )
    running_tasks[filter_id] = task
    return task


async def stop_filter_task(filter_id: str):
    """Stoppt einen laufenden Filter-Task."""
    if filter_id in running_tasks:
        task = running_tasks[filter_id]
        if not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        del running_tasks[filter_id]


# ─── Vinted Kauf-API ──────────────────────────────────────────────────────────

async def vinted_buy_now(item_id: int, user_cookie: str, domain: str = "vinted.de") -> bool:
    """
    Versucht ein Item sofort zu kaufen.
    Gibt True zurück bei Erfolg, False bei Fehler.
    """
    url = f"https://www.{domain}/api/v2/items/{item_id}/buy_now"
    headers = get_headers(user_cookie, domain)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                print(f"[Buy] Item {item_id} → HTTP {resp.status}")
                return resp.status in [200, 201]
    except Exception as e:
        print(f"[Buy] Fehler bei Item {item_id}: {e}")
        return False


async def vinted_like(item_id: int, user_cookie: str, domain: str = "vinted.de") -> bool:
    """
    Liked ein Item (Favorit setzen).
    Gibt True zurück bei Erfolg, False bei Fehler.
    """
    url = f"https://www.{domain}/api/v2/items/{item_id}/favourite"
    headers = get_headers(user_cookie, domain)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                print(f"[Like] Item {item_id} → HTTP {resp.status}")
                return resp.status in [200, 201]
    except Exception as e:
        print(f"[Like] Fehler bei Item {item_id}: {e}")
        return False


async def vinted_send_offer(
    item_id: int,
    offer_price: float,
    user_cookie: str,
    domain: str = "vinted.de"
) -> bool:
    """
    Sendet ein Preisangebot für ein Item.
    """
    url = f"https://www.{domain}/api/v2/items/{item_id}/offer"
    headers = get_headers(user_cookie, domain)
    headers["Content-Type"] = "application/json"

    payload = {"offer": {"price": str(offer_price), "currency": "EUR"}}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                print(f"[Offer] Item {item_id} @ {offer_price}€ → HTTP {resp.status}")
                return resp.status in [200, 201]
    except Exception as e:
        print(f"[Offer] Fehler bei Item {item_id}: {e}")
        return False
