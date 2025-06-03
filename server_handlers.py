# minecraft_telegram_bot/server_handlers.py
import asyncio
import subprocess
import html

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, get_logger
from user_management import auth_required
from docker_utils import run_docker_command

logger = get_logger(__name__)

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("⚠️ CONTAINER non impostato.")
        return
    try:
        output = await run_docker_command(["docker", "logs", "--tail", "50", CONTAINER], read_output=True, timeout=10)
        safe_output = html.escape(output or "(Nessun output dai log)")
        await update.message.reply_text(f"📄 <b>Ultimi log ({CONTAINER}):</b>\n<pre>{safe_output[:3900]}</pre>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"📄❌ Errore /logs: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore recuperando i log: {html.escape(str(e))}")

async def cmd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("⚠️ CONTAINER non impostato.")
        return

    if not update.message or not update.message.text:
        logger.warning("💬⚠️ /cmd: Messaggio o testo mancante.")
        await update.message.reply_text("Errore: impossibile leggere il comando.")
        return

    command_entity = next((e for e in update.message.entities or [] if e.type == "bot_command" and e.offset == 0), None)

    if not command_entity:
        logger.warning("💬⚠️ /cmd: Entità comando non trovata.")
        await update.message.reply_text("Specifica comandi dopo /cmd.")
        return

    raw_command_block = update.message.text[command_entity.length:].strip()
    if not raw_command_block:
        await update.message.reply_text("Specifica comandi dopo /cmd.")
        return

    commands_to_run = [cmd.strip() for cmd in raw_command_block.splitlines() if cmd.strip() and not cmd.strip().startswith("#")]

    if not commands_to_run:
        await update.message.reply_text("Nessun comando valido da eseguire (ignora commenti e righe vuote).")
        return

    await update.message.reply_text(f"⚙️ Invio di {len(commands_to_run)} comandi...")
    for i, single_command in enumerate(commands_to_run):
        try:
            await run_docker_command(["docker", "exec", CONTAINER, "send-command", single_command], read_output=False)
            await update.message.reply_text(f"⚙️✅ Comando {i+1} (<code>{html.escape(single_command)}</code>) inviato.", parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.2)
        except Exception as e:
            await update.message.reply_text(f"⚙️❌ Errore comando {i+1} (<code>{html.escape(single_command)}</code>): {html.escape(str(e))}", parse_mode=ParseMode.HTML)
            logger.error(f"⚙️❌ Errore /cmd '{single_command}': {e}", exc_info=True)
            break

async def stop_server_command(update: Update, context: ContextTypes.DEFAULT_TYPE, quiet: bool = False) -> bool:
    reply_target = update.message or (update.callback_query.message if update.callback_query else None)
    if not CONTAINER:
        if not quiet and reply_target: await reply_target.reply_text("⚠️ CONTAINER non impostato.")
        return False
    if not quiet and reply_target: await reply_target.reply_text(f"🛑⏳ Arresto '{CONTAINER}'...")
    try:
        await run_docker_command(["docker", "stop", CONTAINER], read_output=True, timeout=45)
        if not quiet and reply_target: await reply_target.reply_text(f"🛑✅ '{CONTAINER}' arrestato.")
        return True
    except Exception as e:
        logger.error(f"🛑❌ Errore /stopserver: {e}", exc_info=True)
        if not quiet and reply_target: await reply_target.reply_text(f"❌ Errore arresto: {html.escape(str(e))}")
    return False

async def start_server_command(update: Update, context: ContextTypes.DEFAULT_TYPE, quiet: bool = False) -> bool:
    reply_target = update.message or (update.callback_query.message if update.callback_query else None)
    if not CONTAINER:
        if not quiet and reply_target: await reply_target.reply_text("⚠️ CONTAINER non impostato.")
        return False
    if not quiet and reply_target: await reply_target.reply_text(f"🚀⏳ Avvio '{CONTAINER}'...")
    try:
        await run_docker_command(["docker", "start", CONTAINER], read_output=True, timeout=30)
        if not quiet and reply_target: await reply_target.reply_text(f"🚀✅ '{CONTAINER}' avviato.")
        return True
    except subprocess.CalledProcessError as e:
        err_str = (e.stderr or str(e.output) or str(e)).lower()
        if "is already started" in err_str:
            if not quiet and reply_target: await reply_target.reply_text(f"🚀ℹ️ '{CONTAINER}' è già avviato.")
            return True
        raise
    except Exception as e:
        logger.error(f"🚀❌ Errore /startserver: {e}", exc_info=True)
        if not quiet and reply_target: await reply_target.reply_text(f"❌ Errore avvio: {html.escape(str(e))}")
    return False

async def restart_server_command(update: Update, context: ContextTypes.DEFAULT_TYPE, quiet: bool = False):
    reply_target = update.message or (update.callback_query.message if update.callback_query else None)
    if not CONTAINER:
        if not quiet and reply_target: await reply_target.reply_text("⚠️ CONTAINER non impostato.")
        return

    if not reply_target:
        logger.error("💬❌ /restartserver: Impossibile determinare target risposta.")
        return

    if not quiet: await reply_target.reply_text(f"🔄⏳ Riavvio '{CONTAINER}'...")
    try:
        await run_docker_command(["docker", "restart", CONTAINER], read_output=False, timeout=60)
        logger.info(f"🐳🔄 Comando 'docker restart {CONTAINER}' inviato.")
        if not quiet: await reply_target.reply_text(f"🔄✅ Comando riavvio per '{CONTAINER}' inviato. Controlla /logs.")
    except Exception as e:
        logger.error(f"🔄❌ Errore /restartserver: {e}", exc_info=True)
        if not quiet: await reply_target.reply_text(f"❌ Errore riavvio: {html.escape(str(e))}")
