# minecraft_telegram_bot/world_handlers.py
import asyncio
import html
import os
import shutil
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, WORLD_NAME, get_logger
from user_management import auth_required
from world_management import (
    reset_creative_flag, get_world_directory_path, get_backups_storage_path,
)
from server_handlers import stop_server_command, start_server_command # Import from the new server_handlers

logger = get_logger(__name__)

@auth_required
async def backup_world_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER or not WORLD_NAME:
        await update.message.reply_text("⚠️ CONTAINER o WORLD_NAME non configurati.")
        return
    await update.message.reply_text(f"💾⏳ Avvio backup per '{WORLD_NAME}'...")

    stopped_properly = await stop_server_command(update, context, quiet=True) # quiet=True per gestire messaggi qui
    if not stopped_properly:
        await update.message.reply_text("🛑❌ Backup annullato: server non arrestato correttamente.")
        # Tentiamo comunque un riavvio se il server era attivo
        await _restart_server_after_action(update, context, CONTAINER, "backup (errore stop)", "tentativo riavvio post-errore")
        return
    await update.message.reply_text("🛑✅ Server arrestato per backup.")


    await update.message.reply_text("⏳ Attesa rilascio file...")
    await asyncio.sleep(5)

    world_dir_path = get_world_directory_path(WORLD_NAME)
    backups_storage = get_backups_storage_path()

    if not world_dir_path or not os.path.exists(world_dir_path):
        await update.message.reply_text(f"🌍❓ Directory mondo '{WORLD_NAME}' non trovata. Backup annullato.")
        await _restart_server_after_action(update, context, CONTAINER, "backup (path non trovato)", "riavvio server")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_world_name = "".join(c if c.isalnum() else "_" for c in WORLD_NAME)
    archive_name_base = os.path.join(backups_storage, f"{safe_world_name}_backup_{timestamp}")

    try:
        await update.message.reply_text("🗜️ Creazione archivio zip...")
        await asyncio.to_thread(
            shutil.make_archive,
            base_name=archive_name_base,
            format='zip',
            root_dir=os.path.dirname(world_dir_path),
            base_dir=os.path.basename(world_dir_path)
        )
        final_archive_name = f"{archive_name_base}.zip"
        await update.message.reply_text(f"💾✅ Backup completato: <code>{html.escape(os.path.basename(final_archive_name))}</code>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"💾❌ Errore creazione backup: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore creazione backup: {html.escape(str(e))}")
    finally:
        await _restart_server_after_action(update, context, CONTAINER, "backup", "riavvio server post-backup")

async def _restart_server_after_action(update: Update, context: ContextTypes.DEFAULT_TYPE, container_name: str, action_name: str, message_prefix: str):
    # Usa reply_target per rispondere al messaggio originale o al callback query
    reply_target = update.message or (update.callback_query.message if update.callback_query else None)
    if not reply_target:
        logger.error(f"💬❌ Impossibile determinare target risposta per riavvio post-{action_name}")
        return

    await reply_target.reply_text(f"🚀⏳ {message_prefix} per '{container_name}'...")
    started = await start_server_command(update, context, quiet=True) # Usa start_server_command
    if started:
        await reply_target.reply_text(f"🚀✅ Server '{container_name}' (ri)avviato dopo {action_name}.")
    else:
        await reply_target.reply_text(f"🚀❌ Errore (ri)avvio server '{container_name}' dopo {action_name}. Controlla /logs.")


@auth_required
async def list_backups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    backups_dir = get_backups_storage_path()
    if not os.path.exists(backups_dir):
        await update.message.reply_text(f"📂❓ Directory backup ({backups_dir}) non trovata.")
        return
    try:
        backup_files = sorted(
            [f for f in os.listdir(backups_dir) if f.endswith(".zip")],
            key=lambda f: os.path.getmtime(os.path.join(backups_dir, f)),
            reverse=True
        )
    except Exception as e:
        await update.message.reply_text(f"📂❌ Errore lettura directory backup: {html.escape(str(e))}")
        return

    if not backup_files:
        await update.message.reply_text("📂ℹ️ Nessun backup .zip trovato.")
        return

    buttons = []
    for filename in backup_files[:15]:
        cb_data = f"download_backup_file:{filename}"
        if len(cb_data.encode('utf-8')) <= 64: # Limite Telegram per callback_data
            buttons.append([InlineKeyboardButton(f"📥 {filename}", callback_data=cb_data)])
        else:
            logger.warning(f"💾⚠️ Nome file backup '{filename}' troppo lungo per callback.")

    if not buttons and backup_files: # Se c'erano file ma nessuno convertibile in bottone
        await update.message.reply_text("📂⚠️ Nomi file backup troppo lunghi per bottoni diretti. Impossibile elencarli.")
        return
    elif not buttons: # Se non c'erano file adatti (o la lista era vuota fin dall'inizio, già gestito)
        await update.message.reply_text("📂ℹ️ Nessun backup disponibile per download via bottoni.")
        return

    await update.message.reply_text("📂 Seleziona backup da scaricare (più recenti prima):", reply_markup=InlineKeyboardMarkup(buttons))

@auth_required
async def imnotcreative_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER or not WORLD_NAME:
        await update.message.reply_text("⚠️ CONTAINER o WORLD_NAME non configurati.")
        return

    user_input = " ".join(context.args).strip().lower() # type: ignore
    if user_input != "conferma":
        await update.message.reply_text(
            "🛠️ ATTENZIONE: Modifica file mondo e arresta server.\n"
            f"Mondo target: '{WORLD_NAME}'.\n"
            "Digita `/imnotcreative conferma` per procedere.",
            parse_mode=ParseMode.HTML
        )
        return

    await update.message.reply_text(f"🛠️⏳ Avvio /imnotcreative per '{WORLD_NAME}'...")
    stopped_properly = await stop_server_command(update, context, quiet=True)
    if not stopped_properly:
        await update.message.reply_text("🛑❌ Operazione annullata: server non arrestato.")
        await _restart_server_after_action(update, context, CONTAINER, "imnotcreative (errore stop)", "tentativo riavvio post-errore")
        return
    await update.message.reply_text("🛑✅ Server arrestato.")


    await update.message.reply_text("⏳ Attesa rilascio file...")
    await asyncio.sleep(5)

    success, message = await reset_creative_flag(WORLD_NAME)
    await update.message.reply_text(f"{'✅' if success else '⚠️'} {html.escape(message)}")

    await _restart_server_after_action(update, context, CONTAINER, "imnotcreative", "riavvio server post-imnotcreative")
