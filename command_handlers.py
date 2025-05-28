# minecraft_telegram_bot/command_handlers.py
import asyncio
import subprocess
import re
import html
import os
import shutil
from datetime import datetime
import tempfile
from typing import cast, Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Document
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, WORLD_NAME, get_logger
from world_management import (
    reset_creative_flag, get_world_directory_path, get_backups_storage_path,
)
from user_management import (
    auth_required, authenticate_user, logout_user,
    get_minecraft_username, save_location,
    get_user_data, get_locations
)
from item_management import refresh_items, get_items
from docker_utils import run_docker_command, get_online_players_from_server

from resource_pack_management import (
    ResourcePackError,
    get_world_active_packs_with_details
)

logger = get_logger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot Minecraft attivo. Usa /login <code>password</code> per iniziare."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 <b>Minecraft Bedrock Admin Bot</b>\n\n"

        "🔐 <b>Autenticazione & Utente</b>\n"
        "<b>/login &lt;password&gt;</b> – Accedi al bot\n"
        "<b>/logout</b> – Esci\n"
        "<b>/edituser</b> – Modifica username o elimina posizioni\n\n"

        "🎒 <b>Azioni Veloci</b> (<b>/menu</b>)\n"
        "• <b>/give</b> – Dai un oggetto\n"
        "• <b>/tp</b> – Teletrasportati\n"
        "• <b>/weather</b> – Cambia il meteo\n\n"

        "🎁 <b>Gestione Inventario</b>\n"
        "<b>/give</b> – Seleziona oggetto e quantità\n"
        "  (supporta ricerca inline: digita <code>@nome_bot</code> + oggetto)\n\n"

        "🚀 <b>Teletrasporto</b>\n"
        "<b>/tp</b> – Scegli tra giocatori online, coordinate o posizioni\n\n"

        "☀️ <b>Meteo</b>\n"
        "<b>/weather</b> – Sereno, Pioggia o Temporale\n\n"

        "📍 <b>Salva Posizione</b>\n"
        "<b>/saveloc</b> – Dai un nome alla tua posizione attuale\n\n"

        "🔍 <b>Rilevamento Armor Stand</b>\n"
        "<b>/detectarmorstand</b> – Rileva posizione e orientamento armor stand\n\n"

        "⚙️ <b>Comandi Avanzati</b>\n"
        "<b>/cmd &lt;comando&gt;</b> – Console server (più righe, # commenti)\n"
        "<b>/logs</b> – Ultime 50 righe di log\n\n"

        "💾 <b>Backup & Ripristino</b>\n"
        "<b>/backup_world</b> – Crea backup (.zip), ferma/riprende server\n"
        "<b>/list_backups</b> – Elenca e scarica gli ultimi 15 backup\n\n"

        "🛠️ <b>Server Control</b>\n"
        "<b>/startserver</b> – Avvia container Docker\n"
        "<b>/stopserver</b> – Arresta container Docker\n"
        "<b>/restartserver</b> – Riavvia container Docker\n\n"

        "🎨 <b>Resource Pack</b>\n"
        "<b>/addresourcepack</b> – Invia file .zip/.mcpack\n"
        "<b>/editresourcepacks</b> – Gestisci ordine o elimina pack attivi\n\n"

        "🛠️ <b>Modalità Creativa</b>\n"
        "<b>/imnotcreative</b> – Resetta flag creativo (richiede conferma)\n\n"

        "🏗️ <b>Strutture e Conversioni</b>\n"
        "<b>/split_structure &lt;file&gt;</b> – Dividi file struttura se troppo grande\n"
        "<b>/convert_structure &lt;file&gt;</b> – Converti .schematic in .mcstructure\n"
        "<b>/create_resourcepack &lt;nome&gt;</b> – Crea resource pack da strutture\n\n"

        "✨ <b>Utility</b>\n"
        "<b>/scarica_items</b> – Aggiorna lista item per <b>/give</b>\n\n"

        "❓ <b>Altri comandi</b>\n"
        "<b>/start</b> – Messaggio di benvenuto\n"
        "<b>/help</b> – Questa guida veloce\n\n"

        "<i>Per suggerimenti inline</i>: digita <code>@nome_bot</code> + nome/ID oggetto"
    )
    logger.info("Invio help completo")
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args
    if get_minecraft_username(uid) and get_user_data(uid): # type: ignore
        await update.message.reply_text("🔑✅ Sei già autenticato e username Minecraft impostato.")
        return
    if not args:
        await update.message.reply_text("Per favore, fornisci la password. Es: /login MIA_PASSWORD")
        return
    password_attempt = args[0]
    if authenticate_user(uid, password_attempt):
        await update.message.reply_text("🔑✅ Autenticazione riuscita!")
        if not get_minecraft_username(uid): # type: ignore
            context.user_data["awaiting_mc_username"] = True # type: ignore
            context.user_data["next_action_after_username"] = "post_login_greeting" # type: ignore
            await update.message.reply_text("👤 Inserisci ora il tuo nome utente Minecraft:")
        else:
            await update.message.reply_text(f"Bentornato! Username Minecraft: {get_minecraft_username(uid)}") # type: ignore
    else:
        await update.message.reply_text("🔑❌ Password errata.")

@auth_required
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logout_user(update.effective_user.id) # type: ignore
    await update.message.reply_text("👋 Logout eseguito.")

@auth_required
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

@auth_required
async def edituser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cosa vuoi fare?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Modifica username", callback_data="edit_username")],
        [InlineKeyboardButton("🗑️ Cancella posizione", callback_data="delete_location")]
    ]))

@auth_required
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

@auth_required
async def scarica_items_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✨🔄 Avvio aggiornamento lista item...")
    updated_items = await asyncio.to_thread(refresh_items)
    await update.message.reply_text(f"✨✅ Scaricati {len(updated_items)} item." if updated_items else "✨❌ Errore scaricamento item.")

@auth_required
async def saveloc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id # type: ignore
    if not get_minecraft_username(uid): # type: ignore
        context.user_data["awaiting_mc_username"] = True # type: ignore
        context.user_data["next_action_after_username"] = "saveloc" # type: ignore
        await update.message.reply_text("👤 Inserisci il tuo username Minecraft:")
        return
    context.user_data["awaiting_saveloc_name"] = True # type: ignore
    await update.message.reply_text("📍 Nome per la posizione da salvare:")








@auth_required
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_minecraft_username(update.effective_user.id): # type: ignore
        context.user_data["awaiting_mc_username"] = True # type: ignore
        context.user_data["next_action_after_username"] = "menu" # type: ignore
        await update.message.reply_text("👤 Inserisci il tuo username Minecraft:")
        return
    await update.message.reply_text("🎒 Scegli un'azione:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Give", callback_data="menu_give")],
        [InlineKeyboardButton("🚀 Teleport", callback_data="menu_tp")],
        [InlineKeyboardButton("☀️ Meteo", callback_data="menu_weather")]
    ]))

@auth_required
async def give_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_minecraft_username(update.effective_user.id): # type: ignore
        context.user_data["awaiting_mc_username"] = True # type: ignore
        context.user_data["next_action_after_username"] = "give" # type: ignore
        await update.message.reply_text("👤 Inserisci il tuo username Minecraft:")
        return
    context.user_data["awaiting_give_prefix"] = True # type: ignore
    await update.message.reply_text("🎁 Nome o ID dell'oggetto da dare:")

@auth_required
async def tp_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id # type: ignore
    if not get_minecraft_username(uid): # type: ignore
        context.user_data["awaiting_mc_username"] = True # type: ignore
        context.user_data["next_action_after_username"] = "tp" # type: ignore
        await update.message.reply_text("👤 Inserisci il tuo username Minecraft:")
        return
    try:
        online_players = await get_online_players_from_server()
        buttons = []
        if online_players:
            buttons.extend([InlineKeyboardButton(p, callback_data=f"tp_player:{p}") for p in online_players])
        buttons.append(InlineKeyboardButton("📍 Inserisci coordinate", callback_data="tp_coords_input"))
        user_locs = get_locations(uid) # type: ignore
        for name_loc in user_locs:
            buttons.append(InlineKeyboardButton(f"📌 {name_loc}", callback_data=f"tp_saved:{name_loc}"))

        if not buttons:
            await update.message.reply_text("Nessuna opzione di teletrasporto rapido disponibile.")
            return

        keyboard_layout = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        markup = InlineKeyboardMarkup(keyboard_layout)
        await update.message.reply_text("🚀 Scegli destinazione teletrasporto:", reply_markup=markup)

    except Exception as e:
        logger.error(f"🚀❌ Errore /tp: {e}", exc_info=True)
        await update.message.reply_text("❌ Errore preparando opzioni di teletrasporto.")

@auth_required
async def weather_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_minecraft_username(update.effective_user.id): # type: ignore
        context.user_data["awaiting_mc_username"] = True # type: ignore
        context.user_data["next_action_after_username"] = "weather" # type: ignore
        await update.message.reply_text("👤 Inserisci il tuo username Minecraft:")
        return
    await update.message.reply_text("☀️ Scegli il meteo:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("☀️ Sereno", callback_data="weather_set:clear")],
        [InlineKeyboardButton("🌧 Pioggia", callback_data="weather_set:rain")],
        [InlineKeyboardButton("⛈ Temporale", callback_data="weather_set:thunder")]
    ]))

@auth_required
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

@auth_required
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

@auth_required
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
async def handle_split_mcstructure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Utilizzo: /split_structure <percorso_file> [--threshold N] [--axis x|y|z]")
        return

    input_path = context.args[0]
    threshold = None
    axis = None

    # Parse optional arguments
    i = 1
    while i < len(context.args):
        if context.args[i] == "--threshold" and i + 1 < len(context.args):
            try:
                threshold = int(context.args[i+1])
                i += 2
            except ValueError:
                await update.message.reply_text("Errore: --threshold richiede un numero intero.")
                return
        elif context.args[i] == "--axis" and i + 1 < len(context.args) and context.args[i+1] in ['x', 'y', 'z']:
            axis = context.args[i+1]
            i += 2
        else:
            await update.message.reply_text(f"Errore: Argomento non riconosciuto o incompleto: {context.args[i]}")
            return
    
    script_path = "/app/importBuild/schem_to_mc_amulet/split_mcstructure.py"
    python_executable = "/app/importBuild/schem_to_mc_amulet/venv/bin/python"

    command = [python_executable, script_path, input_path]
    if threshold is not None:
        command.extend(["--threshold", str(threshold)])
    if axis is not None:
        command.extend(["--axis", axis])

    await update.message.reply_text(f"⏳ Esecuzione split_mcstructure.py per {input_path}...")

    try:
        # Run the script as a subprocess
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            output_message = f"✅ split_mcstructure.py completato.\nOutput:\n<pre>{html.escape(stdout.decode())}</pre>"
            await update.message.reply_text(output_message, parse_mode=ParseMode.HTML)
        else:
            error_message = f"❌ Errore durante l'esecuzione di split_mcstructure.py (Codice {process.returncode}).\nErrore:\n<pre>{html.escape(stderr.decode())}</pre>"
            await update.message.reply_text(error_message, parse_mode=ParseMode.HTML)

    except FileNotFoundError:
        await update.message.reply_text(f"❌ Errore: Eseguibile Python o script non trovato. Verifica i percorsi.")
    except Exception as e:
        logger.error(f"❌ Errore esecuzione split_mcstructure.py: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore generico durante l'esecuzione: {html.escape(str(e))}")

@auth_required
async def handle_convert2mc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Utilizzo: /convert_structure <percorso_file> [--version X.Y.Z]")
        return

    input_path = context.args[0]
    version = None

    # Parse optional arguments
    i = 1
    while i < len(context.args):
        if context.args[i] == "--version" and i + 1 < len(context.args):
            version = context.args[i+1]
            i += 2
        else:
            await update.message.reply_text(f"Errore: Argomento non riconosciuto o incompleto: {context.args[i]}")
            return

    script_path = "/app/importBuild/schem_to_mc_amulet/convert2mc.py"
    python_executable = "/app/importBuild/schem_to_mc_amulet/venv/bin/python"

    command = [python_executable, script_path, input_path]
    if version is not None:
        command.extend(["--version", version])

    await update.message.reply_text(f"⏳ Esecuzione convert2mc.py per {input_path}...")

    try:
        # Run the script as a subprocess
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            output_message = f"✅ convert2mc.py completato.\nOutput:\n<pre>{html.escape(stdout.decode())}</pre>"
            await update.message.reply_text(output_message, parse_mode=ParseMode.HTML)
        else:
            error_message = f"❌ Errore durante l'esecuzione di convert2mc.py (Codice {process.returncode}).\nErrore:\n<pre>{html.escape(stderr.decode())}</pre>"
            await update.message.reply_text(error_message, parse_mode=ParseMode.HTML)

    except FileNotFoundError:
        await update.message.reply_text(f"❌ Errore: Eseguibile Python o script non trovato. Verifica i percorsi.")
    except Exception as e:
        logger.error(f"❌ Errore esecuzione convert2mc.py: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore generico durante l'esecuzione: {html.escape(str(e))}")

@auth_required
async def handle_structura_cli(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Utilizzo: /create_resourcepack <pack_name> --structures <file1.mcstructure> [<file2.mcstructure> ...] "
            "[--nametags <tag1> [<tag2> ...]] [--offsets <x,y,z> [<x,y,z> ...]] "
            "[--opacity N] [--icon <icon_path>] [--list] [--big_build] [--big_offset <x,y,z>]"
        )
        return

    pack_name = None
    structures = []
    nametags = None
    offsets = None
    opacity = None
    icon = None
    list_flag = False
    big_build = False
    big_offset = None

    # Parse arguments
    args = context.args
    i = 0
    while i < len(args):
        if i == 0 and pack_name is None:
            pack_name = args[i]
            i += 1
        elif args[i] == "--structures" and i + 1 < len(args):
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                structures.append(args[i])
                i += 1
        elif args[i] == "--nametags" and i + 1 < len(args):
            nametags = []
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                nametags.append(args[i])
                i += 1
        elif args[i] == "--offsets" and i + 1 < len(args):
            offsets = []
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                offsets.append(args[i])
                i += 1
        elif args[i] == "--opacity" and i + 1 < len(args):
            try:
                opacity = int(args[i+1])
                i += 2
            except ValueError:
                await update.message.reply_text("Errore: --opacity richiede un numero intero.")
                return
        elif args[i] == "--icon" and i + 1 < len(args):
            icon = args[i+1]
            i += 2
        elif args[i] == "--list":
            list_flag = True
            i += 1
        elif args[i] == "--big_build":
            big_build = True
            i += 1
        elif args[i] == "--big_offset" and i + 1 < len(args):
            big_offset = args[i+1]
            i += 2
        else:
            await update.message.reply_text(f"Errore: Argomento non riconosciuto o incompleto: {args[i]}")
            return

    if pack_name is None or not structures:
        await update.message.reply_text("Errore: Nome pacchetto e almeno un file struttura sono obbligatori.")
        return

    script_path = "/app/importBuild/structura_env/structuraCli.py"
    python_executable = "/app/importBuild/structura_env/venv/bin/python"

    command = [python_executable, script_path, pack_name, "--structures"] + structures

    if nametags is not None:
        command.extend(["--nametags"] + nametags)
    if offsets is not None:
        command.extend(["--offsets"] + offsets)
    if opacity is not None:
        command.extend(["--opacity", str(opacity)])
    if icon is not None:
        command.extend(["--icon", icon])
    if list_flag:
        command.append("--list")
    if big_build:
        command.append("--big_build")
    if big_offset is not None:
        command.extend(["--big_offset", big_offset])

    await update.message.reply_text(f"⏳ Esecuzione structuraCli.py per creare il pacchetto '{pack_name}'...")

    structura_script_dir = "/app/importBuild/structura_env/"
    try:
        # Run the script as a subprocess
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=structura_script_dir
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            output_message = f"✅ structuraCli.py completato.\nOutput:\n<pre>{html.escape(stdout.decode())}</pre>"
            await update.message.reply_text(output_message, parse_mode=ParseMode.HTML)
        else:
            error_message = f"❌ Errore durante l'esecuzione di structuraCli.py (Codice {process.returncode}).\nErrore:\n<pre>{html.escape(stderr.decode())}</pre>"
            await update.message.reply_text(error_message, parse_mode=ParseMode.HTML)

    except FileNotFoundError:
        await update.message.reply_text(f"❌ Errore: Eseguibile Python o script non trovato. Verifica i percorsi.")
    except Exception as e:
        logger.error(f"❌ Errore esecuzione structuraCli.py: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore generico durante l'esecuzione: {html.escape(str(e))}")


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

# Sistema completo di rilevamento armor stand aggiornato
# Sostituire le funzioni esistenti con queste versioni

def calculate_distance_3d(pos1: dict, pos2: dict) -> float:
    """Calcola distanza 3D tra due posizioni"""
    return ((pos1['x'] - pos2['x'])**2 + (pos1['y'] - pos2['y'])**2 + (pos1['z'] - pos2['z'])**2)**0.5


# Rilevamento armor stand - 4 blocchi cardinali, 4 orientamenti precisi

@auth_required
async def detect_armor_stand_command_improved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Rileva armor stand nei 4 blocchi cardinali con 4 orientamenti precisi
    """
    uid = update.effective_user.id
    minecraft_username = get_minecraft_username(uid)
    
    if not minecraft_username:
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action_data"] = {"type": "detect_armor_stand", "update": update}
        await update.message.reply_text("👤 Inserisci il tuo username Minecraft:")
        return
    
    if not CONTAINER:
        await update.message.reply_text("⚠️ CONTAINER non impostato.")
        return

    await update.message.reply_text("🔍 **Rilevamento Armor Stand**\nTesto 4 blocchi cardinali...")

    try:
        detected_stands = await test_cardinal_positions(minecraft_username, update)
        
        if not detected_stands:
            await update.message.reply_text("❌ Nessun armor stand trovato nei 4 blocchi cardinali.")
            return
        
        # Mostra risultati
        result_text = f"✅ **{len(detected_stands)} Armor Stand Trovati!**\n\n"
        
        for i, stand in enumerate(detected_stands, 1):
            result_text += (
                f"**{i}. {stand['direction']} - {stand['orientation']}**\n"
                f"📍 X={stand['x']:.1f}, Y={stand['y']:.1f}, Z={stand['z']:.1f}\n\n"
            )
        
        await update.message.reply_text(result_text, parse_mode=ParseMode.MARKDOWN)
        
        # Salva il primo per eventuale uso
        if detected_stands:
            best_stand = detected_stands[0]
            context.user_data["detected_armor_stand"] = {
                "direction": best_stand['direction'],
                "orientation": best_stand['orientation'],
                "armor_stand_coords": {
                    'x': best_stand['x'],
                    'y': best_stand['y'],
                    'z': best_stand['z']
                }
            }
            
            await update.message.reply_text("💾 Vuoi salvare la posizione? Rispondi con un nome o 'no'.")
            context.user_data["awaiting_armor_stand_save"] = True
            
    except Exception as e:
        logger.error(f"🔍❌ Errore rilevamento: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore: {html.escape(str(e))}")

async def test_cardinal_positions(minecraft_username: str, update: Update) -> list:
    """
    Testa i 4 blocchi cardinali per armor stand con 4 orientamenti precisi
    """
    detected_stands = []
    
    # 4 posizioni cardinali
    positions = [
        {"pos": "^ ^ ^1", "dir": "Nord"},
        {"pos": "^1 ^ ^", "dir": "Est"},
        {"pos": "^ ^ ^-1", "dir": "Sud"},
        {"pos": "^-1 ^ ^", "dir": "Ovest"}
    ]
    
    # 4 orientamenti precisi come il tuo comando
    orientations = [
        {"range": "rym=0,ry=0", "name": "Nord (0°)"},
        {"range": "rym=90,ry=90", "name": "Est (90°)"},
        {"range": "rym=180,ry=180", "name": "Sud (180°)"},
        {"range": "rym=270,ry=270", "name": "Ovest (270°)"}
    ]
    
    try:
        for position in positions:
            await update.message.reply_text(f"🧭 Test: {position['dir']}")
            
            for orientation in orientations:
                # Pulisci log
                await run_docker_command(["docker", "exec", CONTAINER, "send-command", "say TEST_START"], read_output=False)
                await asyncio.sleep(0.5)
                
                # Comando di test identico al tuo
                test_cmd = (
                    f"execute at {minecraft_username} positioned {position['pos']} "
                    f"if entity @e[type=armor_stand,dx=0,dy=0,dz=0,{orientation['range']}] run "
                    f"tp {minecraft_username} ~ ~ ~"
                )
                
                await run_docker_command(["docker", "exec", CONTAINER, "send-command", test_cmd], read_output=False)
                await asyncio.sleep(1.5)
                
                # Fine test
                await run_docker_command(["docker", "exec", CONTAINER, "send-command", "say TEST_END"], read_output=False)
                await asyncio.sleep(0.5)
                
                # Controlla se ha trovato (teleport del player)
                log_output = await run_docker_command(["docker", "logs", "--tail", "10", CONTAINER], read_output=True, timeout=3)
                
                if await check_test_success(log_output, minecraft_username):
                    # Armor stand trovato! Estrai coordinate
                    coordinates = await extract_coordinates_from_log(log_output, minecraft_username)
                    if coordinates:
                        detected_stands.append({
                            'x': coordinates['x'],
                            'y': coordinates['y'],
                            'z': coordinates['z'],
                            'direction': position['dir'],
                            'orientation': orientation['name']
                        })
                        
                        await update.message.reply_text(f"✅ {position['dir']} - {orientation['name']}")
                        break  # Trovato, passa alla prossima posizione
        
        return detected_stands
        
    except Exception as e:
        logger.error(f"Errore test: {e}")
        return []

async def check_test_success(log_output: str, minecraft_username: str) -> bool:
    """
    Controlla se test ha successo (teleport trovato tra TEST_START e TEST_END)
    """
    lines = log_output.split('\n')
    capture = False
    
    for line in lines:
        if "TEST_START" in line:
            capture = True
            continue
        elif "TEST_END" in line:
            break
        
        if capture and "Teleported" in line and minecraft_username in line:
            return True
    
    return False

async def extract_coordinates_from_log(log_output: str, minecraft_username: str) -> dict:
    """
    Estrae coordinate dal log di teleport
    """
    lines = log_output.split('\n')
    capture = False
    
    for line in lines:
        if "TEST_START" in line:
            capture = True
            continue
        elif "TEST_END" in line:
            break
        
        if capture and "Teleported" in line and minecraft_username in line:
            teleport_match = re.search(rf"Teleported {re.escape(minecraft_username)} to ([0-9\.\-]+),?\s*([0-9\.\-]+),?\s*([0-9\.\-]+)", line)
            if teleport_match:
                x, y, z = map(float, teleport_match.groups())
                return {"x": x, "y": y, "z": z}
    
    return None

# Versione per hologram
async def detect_armor_stand_for_hologram_improved_mh(update: Update, context: ContextTypes.DEFAULT_TYPE, minecraft_username: str):
    """
    Versione per paste hologram
    """
    try:
        await update.message.reply_text("🔍 Cerco armor stand per hologram...")
        
        detected_stands = await test_cardinal_positions(minecraft_username, update)
        
        if not detected_stands:
            await update.message.reply_text("❌ Nessun armor stand trovato.")
            cleanup_hologram_data(context)
            return
        
        # Usa il primo trovato
        best_stand = detected_stands[0]
        await update.message.reply_text(f"✅ Trovato: {best_stand['direction']} - {best_stand['orientation']}")
        
        # Procedi con paste
        await execute_hologram_paste(
            update, context,
            {'x': best_stand['x'], 'y': best_stand['y'], 'z': best_stand['z']},
            best_stand['direction'].lower(),
            minecraft_username
        )
        
    except Exception as e:
        logger.error(f"Errore hologram: {e}")
        await update.message.reply_text(f"❌ Errore: {html.escape(str(e))}")
        cleanup_hologram_data(context)

def cleanup_hologram_data(context):
    """Pulisce dati hologram"""
    keys_to_remove = ["awaiting_hologram_structure", "hologram_structure_path", "hologram_structure_name"]
    for key in keys_to_remove:
        context.user_data.pop(key, None)

async def execute_hologram_paste(update, context, armor_stand_coords, direction_code, minecraft_username):
    """Placeholder - usa la tua implementazione esistente"""
    await update.message.reply_text(f"🏗️ Paste hologram a {armor_stand_coords['x']:.1f}, {armor_stand_coords['y']:.1f}, {armor_stand_coords['z']:.1f}")
