"""
embeds.py — Discord Embed Builder und Button Views
"""

import discord
from datetime import datetime, timezone
from scraper import vinted_buy_now, vinted_like, vinted_send_offer
from storage import get_user_token


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def calculate_buyer_fee(price: float) -> str:
    """
    Berechnet Vinted Käuferschutz-Gebühr:
    0,70 € + 5% des Preises, mindestens 0,70 €, maximal 8,00 €
    """
    fee = round(0.70 + (price * 0.05), 2)
    fee = max(0.70, min(fee, 8.00))
    total = round(price + fee, 2)
    return f"{total:.2f} € (inkl. {fee:.2f} € Gebühr)"


def reputation_to_stars(reputation) -> str:
    """
    Wandelt Vinted Reputation (0.0 bis 1.0) in Sterne-String um.
    """
    try:
        rep = float(reputation or 0)
        stars = round(rep * 5)
        stars = max(0, min(5, stars))
        return "⭐" * stars + "☆" * (5 - stars)
    except (ValueError, TypeError):
        return "☆☆☆☆☆"


def condition_translate(condition: str) -> str:
    """Übersetzt Vinted-Zustandsbezeichnungen auf Deutsch."""
    mapping = {
        "new_with_tags":     "🏷️ Neu mit Etikett",
        "new_without_tags":  "✈ Neu ohne Etikett",
        "very_good":         "👍 Sehr gut",
        "good":              "✅ Gut",
        "satisfactory":      "👌 Befriedigend",
        "for_parts":         "🔧 Als Ersatzteile",
    }
    return mapping.get(condition, condition or "Unbekannt")


def format_time_ago(updated_at: str) -> str:
    """Gibt aus, wie lange ein Item schon online ist."""
    try:
        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        diff = int((datetime.now(timezone.utc) - dt).total_seconds())
        if diff < 60:
            return f"vor {diff}s"
        elif diff < 3600:
            return f"vor {diff // 60}min"
        elif diff < 86400:
            return f"vor {diff // 3600}h"
        else:
            return f"vor {diff // 86400}d"
    except Exception:
        return "Unbekannt"


# ─── Embed Builder ────────────────────────────────────────────────────────────

async def build_embed(item: dict, vinted_domain: str = "vinted.de") -> tuple[discord.Embed, discord.ui.View]:
    """
    Erstellt Discord Embed + Button-View für ein Vinted Item.
    Gibt (embed, view) zurück.
    """
    item_id = item.get("id", 0)
    price = float(item.get("price", 0))
    item_url = f"https://www.{vinted_domain}/items/{item_id}"

    embed = discord.Embed(
        title=item.get("title", "Unbekannter Artikel"),
        url=item_url,
        color=0x00C853,
        timestamp=datetime.now(timezone.utc)
    )

    # Hauptbild
    photos = item.get("photos", [])
    if photos:
        photo_url = photos[0].get("url") or photos[0].get("full_size_url", "")
        if photo_url:
            embed.set_image(url=photo_url)

    # Preis-Felder
    embed.add_field(name="💰 Preis", value=f"**{price:.2f} €**", inline=True)
    embed.add_field(name="💳 Mit Gebühren", value=calculate_buyer_fee(price), inline=True)

    # Zustand
    condition = item.get("status") or item.get("condition", "")
    embed.add_field(name="📦 Zustand", value=condition_translate(condition), inline=True)

    # Größe
    size = item.get("size_title") or item.get("size", "")
    if size:
        embed.add_field(name="📏 Größe", value=str(size), inline=True)

    # Marke
    brand = item.get("brand_title") or (item.get("brand") or {}).get("title", "")
    if brand:
        embed.add_field(name="🏷️ Marke", value=brand, inline=True)

    # Land
    country = (item.get("country") or {}).get("title", "")
    if country:
        embed.add_field(name="🌍 Versand aus", value=country, inline=True)

    # Verkäufer
    user = item.get("user") or {}
    seller_name = user.get("login", "Unbekannt")
    seller_id = user.get("id", "")
    reputation = user.get("feedback_reputation", 0)
    feedback_count = user.get("feedback_count", 0)
    seller_url = f"https://www.{vinted_domain}/member/{seller_id}"

    embed.add_field(
        name="👤 Verkäufer",
        value=f"[{seller_name}]({seller_url})",
        inline=True
    )
    embed.add_field(
        name="⭐ Bewertung",
        value=f"{reputation_to_stars(reputation)} ({feedback_count})",
        inline=True
    )

    # Online-Zeit
    updated_at = item.get("updated_at_ts") or item.get("created_at_ts", "")
    if updated_at:
        embed.add_field(name="🕐 Online", value=format_time_ago(str(updated_at)), inline=True)

    embed.set_footer(
        text=f"Vinted Sniper • ID: {item_id}",
        icon_url="https://www.vinted.de/favicon.ico"
    )

    # Button-View
    view = ItemView(item_id=item_id, item_url=item_url, vinted_domain=vinted_domain)

    return embed, view


# ─── Button View ──────────────────────────────────────────────────────────────

class ItemView(discord.ui.View):
    """
    Persistente Button-View für ein Vinted Item.
    timeout=None damit Buttons nach Neustart noch funktionieren.
    Jeder Button hat eine eindeutige custom_id für Persistenz.
    """

    def __init__(self, item_id: int, item_url: str, vinted_domain: str = "vinted.de"):
        super().__init__(timeout=None)
        self.item_id = item_id
        self.item_url = item_url
        self.vinted_domain = vinted_domain

    @discord.ui.button(
        label="🛒 Sofort kaufen",
        style=discord.ButtonStyle.green,
        custom_id="vinted_buy"
    )
    async def buy_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Kauft das Item direkt über die Vinted API."""
        user_cookie = get_user_token(interaction.user.id)
        if not user_cookie:
            await interaction.response.send_message(
                "❌ Bitte erst `/setup` ausführen und deinen Vinted Cookie eingeben.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        success = await vinted_buy_now(self.item_id, user_cookie, self.vinted_domain)
        if success:
            await interaction.followup.send(
                f"✅ **Kauf erfolgreich!** Du kaufst: {self.item_url}",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"❌ Kauf fehlgeschlagen (Item bereits verkauft oder anderer Fehler).\n"
                f"Direkt kaufen: {self.item_url}",
                ephemeral=True
            )

    @discord.ui.button(
        label="❤️ Liken",
        style=discord.ButtonStyle.red,
        custom_id="vinted_like"
    )
    async def like_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Setzt das Item als Favorit."""
        user_cookie = get_user_token(interaction.user.id)
        if not user_cookie:
            await interaction.response.send_message(
                "❌ Bitte erst `/setup` ausführen.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        success = await vinted_like(self.item_id, user_cookie, self.vinted_domain)
        if success:
            await interaction.followup.send("✅ Item geliked!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Fehler beim Liken.", ephemeral=True)

    @discord.ui.button(
        label="👁️ Ansehen",
        style=discord.ButtonStyle.blurple,
        custom_id="vinted_view"
    )
    async def view_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Gibt den direkten Link zum Item."""
        await interaction.response.send_message(
            f"🔗 {self.item_url}",
            ephemeral=True
        )

    @discord.ui.button(
        label="💬 Angebot",
        style=discord.ButtonStyle.grey,
        custom_id="vinted_offer"
    )
    async def send_offer(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Öffnet Modal für Preisangebot."""
        user_cookie = get_user_token(interaction.user.id)
        if not user_cookie:
            await interaction.response.send_message(
                "❌ Bitte erst `/setup` ausføhren.",
                ephemeral=True
            )
            return

        # Modal für Preiseingabe
        modal = OfferModal(item_id=self.item_id, user_cookie=user_cookie, vinted_domain=self.vinted_domain)
        await interaction.response.send_modal(modal)


class OfferModal(discord.ui.Modal, title="Preisangebot senden"):
    """Modal-Dialog für Preisangebote."""

    price_input = discord.ui.TextInput(
        label="Dein Angebot (in Euro)",
        placeholder="z.B. 15.00",
        required=True,
        max_length=10
    )

    def __init__(self, item_id: int, user_cookie: str, vinted_domain: str = "vinted.de"):
        super().__init__()
        self.item_id = item_id
        self.user_cookie = user_cookie
        self.vinted_domain = vinted_domain

    async def on_submit(self, interaction: discord.Interaction):
        """Verarbeitet das Angebot nach Eingabe."""
        try:
            offer_price = float(self.price_input.value.replace(",", "."))
        except ValueError:
            await interaction.response.send_message(
                "❌ Ungültiger Preis. Bitte eine Zahl eingeben (z.B. 15.00).",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        success = await vinted_send_offer(self.item_id, offer_price, self.user_cookie, self.vinted_domain)
        if success:
            await interaction.followup.send(
                f"✅ Angebot über **{offer_price:.2f} €** gesendet!",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ Angebot konnte nicht gesendet werden (Verkäufer akzeptiert möglicherweise keine Angebote).",
                ephemeral=True
            )
