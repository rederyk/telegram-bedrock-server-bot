# minecraft_telegram_bot/item_handlers.py
import asyncio
import html

from telegram import Update
from telegram.ext import ContextTypes

from config import get_logger
from user_management import auth_required
from item_management import refresh_items

logger = get_logger(__name__)

@auth_required
async def scarica_items_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✨🔄 Avvio aggiornamento lista item...")
    updated_items = await asyncio.to_thread(refresh_items)
    await update.message.reply_text(f"✨✅ Scaricati {len(updated_items)} item." if updated_items else "✨❌ Errore scaricamento item.")
