# minecraft_telegram_bot/world_handlers.py
import asyncio
import html
import os
import shutil
from datetime import datetime
import tempfile

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
        cb_data_download = f"download_backup_file:{filename}"
        cb_data_restore = f"restore_backup_file:{filename}"
        
        row_buttons = []
        
        if len(cb_data_download.encode('utf-8')) <= 64: # Limite Telegram per callback_data
            row_buttons.append(InlineKeyboardButton(f"📥 {filename}", callback_data=cb_data_download))
        else:
            logger.warning(f"💾⚠️ Nome file backup '{filename}' troppo lungo per download callback.")
        
        if len(cb_data_restore.encode('utf-8')) <= 64: # Limite Telegram per callback_data
            row_buttons.append(InlineKeyboardButton(f"🔄 {filename}", callback_data=cb_data_restore))
        else:
            logger.warning(f"💾⚠️ Nome file backup '{filename}' troppo lungo per download callback.")

        if row_buttons:
            buttons.append(row_buttons)

    if not buttons and backup_files: # Se c'erano file ma nessuno convertibile in bottone
        await update.message.reply_text("📂⚠️ Nomi file backup troppo lunghi per bottoni diretti. Impossibile elencarli.")
        return
    elif not buttons: # Se non c'erano file adatti (o la lista era vuota fin dall'inizio, già gestito)
        await update.message.reply_text("📂ℹ️ Nessun backup disponibile per download via bottoni.")
        return

    await update.message.reply_text("📂 Seleziona backup da scaricare o ripristinare (più recenti prima):", reply_markup=InlineKeyboardMarkup(buttons))

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

async def restore_backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE, filename: str):
    message = update.message or update.callback_query.message
    if not CONTAINER or not WORLD_NAME:
        await message.reply_text("⚠️ CONTAINER o WORLD_NAME non configurati.")
        return
    
    await message.reply_text(f"🔄⏳ Avvio ripristino backup '{filename}' per '{WORLD_NAME}'...")

    stopped_properly = await stop_server_command(update, context, quiet=True)
    if not stopped_properly:
        await message.reply_text("🛑❌ Ripristino annullato: server non arrestato correttamente.")
        await _restart_server_after_action(update, context, CONTAINER, "restore (errore stop)", "tentativo riavvio post-errore")
        return
    await message.reply_text("🛑✅ Server arrestato per ripristino.")

    await message.reply_text("⏳ Attesa rilascio file...")
    await asyncio.sleep(5)

    world_dir_path = get_world_directory_path(WORLD_NAME)
    backups_storage = get_backups_storage_path()
    backup_file_path = os.path.join(backups_storage, filename)

    if not world_dir_path or not os.path.exists(world_dir_path):
        await message.reply_text(f"🌍❓ Directory mondo '{WORLD_NAME}' non trovata. Ripristino annullato.")
        await _restart_server_after_action(update, context, CONTAINER, "restore (path non trovato)", "riavvio server")
        return
    
    if not os.path.exists(backup_file_path):
        await message.reply_text(f"💾❓ File backup '{filename}' non trovato. Ripristino annullato.")
        await _restart_server_after_action(update, context, CONTAINER, "restore (backup non trovato)", "riavvio server")
        return

    try:
        await message.reply_text(f"🔄 Estrazione archivio '{filename}' in area temporanea...")
        # Create a temporary directory
        temp_dir = tempfile.mkdtemp(dir=os.path.dirname(world_dir_path), prefix="restore_temp_")
        # Extract the backup to the temporary directory
        shutil.unpack_archive(backup_file_path, temp_dir)

        await message.reply_text(f"🔄 Spostamento mondo ripristinato in posizione originale...")
        # Remove existing world directory
        shutil.rmtree(world_dir_path)
        # Rename the extracted directory to the original world name
        extracted_path = temp_dir
        extracted_dir = os.path.join(extracted_path, os.listdir(extracted_path)[0])

        # Check if the extracted directory has the same name as the world directory
        if os.path.basename(extracted_dir) != os.path.basename(world_dir_path):
            logger.warning(f"🔄⚠️ La directory estratta '{os.path.basename(extracted_dir)}' non corrisponde al nome del mondo '{os.path.basename(world_dir_path)}'. Tentativo di correzione...")
            new_extracted_dir = os.path.join(extracted_path, os.path.basename(world_dir_path))
            os.rename(extracted_dir, new_extracted_dir)
            extracted_dir = new_extracted_dir
        os.rename(extracted_dir, world_dir_path)

        # Clean up the temporary directory
        shutil.rmtree(temp_dir)

        await message.reply_text(f"🔄✅ Ripristino completato da: <code>{html.escape(filename)}</code>", parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"🔄❌ Errore durante il ripristino del backup '{filename}': {e}", exc_info=True)
        await message.reply_text(f"❌ Errore durante il ripristino del backup: {html.escape(str(e))}")
    finally:
        await _restart_server_after_action(update, context, CONTAINER, "restore", "riavvio server post-restore")
