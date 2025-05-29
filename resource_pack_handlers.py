# minecraft_telegram_bot/resource_pack_handlers.py
import asyncio
import html

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import WORLD_NAME, get_logger
from user_management import auth_required
from resource_pack_management import (
    ResourcePackError,
    get_world_active_packs_with_details
)

logger = get_logger(__name__)

@auth_required
async def add_resourcepack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not WORLD_NAME:
        await update.message.reply_text("⚠️ `WORLD_NAME` non impostato. Impossibile aggiungere resource pack.")
        return
    await update.message.reply_text(
        "📦🖼️ Ok! Inviami il file RP (.mcpack o .zip) o un link diretto.\n\n"
        "ℹ️ Nuovi pack aggiunti con priorità più alta (ultimi nel JSON)."
    )
    context.user_data["awaiting_resource_pack"] = True # type: ignore

@auth_required
async def edit_resourcepacks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not WORLD_NAME:
        await update.message.reply_text("⚠️ `WORLD_NAME` non impostato.")
        return

    try:
        active_packs_details = await asyncio.to_thread(get_world_active_packs_with_details, WORLD_NAME)
    except Exception as e:
        logger.error(f"📦❌ Errore dettagli RP attivi: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore recupero dettagli pacchetti: {html.escape(str(e))}")
        return

    if not active_packs_details:
        await update.message.reply_text("📦ℹ️ Nessun resource pack attivo per questo mondo.")
        return

    message_text = "📦 Resource pack attivi (primo=priorità alt, ultimo=bassa):\n"
    buttons = []
    for pack in active_packs_details:
        display_order = pack['order'] + 1
        pack_name = pack.get('name', 'Nome Sconosciuto')
        pack_uuid = pack['uuid']
        display_name = (pack_name[:25] + '...') if len(pack_name) > 28 else pack_name

        message_text += f"\n{display_order}. {html.escape(pack_name)} (<code>{pack_uuid[:8]}...</code>)"
        buttons.append([
            InlineKeyboardButton(f"{display_order}. {html.escape(display_name)}", callback_data=f"rp_manage:{pack_uuid}")
        ])

    buttons.append([InlineKeyboardButton("↩️ Annulla", callback_data="rp_action:cancel_edit")])
    reply_markup = InlineKeyboardMarkup(buttons)

    if len(message_text) > 4000 :
        message_text = "📦 Resource pack attivi (lista troppo lunga, vedi bottoni):\n"

    await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
