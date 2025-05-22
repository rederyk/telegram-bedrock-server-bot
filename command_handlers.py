# minecraft_telegram_bot/command_handlers.py
import asyncio
import subprocess
import re
import html
import os
import shutil
from datetime import datetime
import tempfile # Per la gestione temporanea di file/directory
from typing import cast # Per type casting
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Document
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, WORLD_NAME, get_logger
from world_management import (
    reset_creative_flag, get_world_directory_path, get_backups_storage_path,
)
from user_management import (
    auth_required, authenticate_user, logout_user,
    get_minecraft_username, 
    get_user_data, get_locations
)
from item_management import refresh_items, get_items
from docker_utils import run_docker_command, get_online_players_from_server

from resource_pack_management import (
    ResourcePackError,
    get_world_active_packs_with_details # Importata per il nuovo comando
)

logger = get_logger(__name__)

# --- Funzioni Ausiliarie ---
async def _offer_server_restart(update: Update, context: ContextTypes.DEFAULT_TYPE, reason: str = ""):
    """Invia un messaggio testuale con il comando /restartserver cliccabile."""
    message_text = f"Operazione resource pack completata {reason}."
    message_text += "\nPer applicare le modifiche, puoi usare il comando /restartserver ."
    message_text += "\nSe preferisci, puoi farlo anche più tardi."
    
    # Invia la risposta appropriata se è un callback o un messaggio normale
    if update.callback_query and update.callback_query.message: 
        await update.callback_query.message.reply_text(message_text, parse_mode=ParseMode.HTML) # Usa HTML se vuoi formattare il comando
    elif update.message: 
        await update.message.reply_text(message_text, parse_mode=ParseMode.HTML) # Usa HTML se vuoi formattare il comando


# --- Comandi Esistenti (Aggiornati se necessario) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot Minecraft attivo. Usa /login <password> per iniziare.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Comandi disponibili:\n\n"
        "<b>Autenticazione e Utente:</b>\n"
        "/login &lt;password&gt; - Autenticati\n"
        "/logout - Esci\n"
        "/edituser - Modifica username o cancella posizioni\n"
        "\n<b>Interazione Server Minecraft:</b>\n"
        "/menu - Mostra menu azioni rapide (give, tp, weather)\n"
        "/give - Avvia il flusso per dare un oggetto\n"
        "/tp - Avvia il flusso di teletrasporto\n"
        "/weather - Avvia il flusso per cambiare meteo\n"
        "/saveloc - Salva la tua posizione attuale\n"
        "/cmd &lt;comando_minecraft&gt; - Esegui comandi sulla console\n"
        "/logs - Mostra ultimi log del server\n"
        "\n<b>Gestione Mondo e Server:</b>\n"
        "/startserver - Avvia il server Minecraft\n"
        "/stopserver - Arresta il server Minecraft\n"
        "/restartserver - Riavvia il server Minecraft\n"
        "/imnotcreative - Resetta il flag 'creativo' del mondo\n"
        "/backup_world - Crea un backup del mondo\n"
        "/list_backups - Mostra e scarica i backup\n"
        "/addresourcepack - Aggiunge un nuovo resource pack\n" 
        "/editresourcepacks - Modifica ordine o rimuovi resource pack attivi\n"
        "\n<b>Utility Bot:</b>\n"
        "/scarica_items - Aggiorna lista oggetti Minecraft\n\n"
        "<i>Puoi anche digitare @&lt;nome_bot&gt; + nome oggetto per suggerimenti inline.</i>"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args
    if get_minecraft_username(uid) and get_user_data(uid):
        await update.message.reply_text("Sei già autenticato e il tuo username Minecraft è impostato.")
        return
    if not args:
        await update.message.reply_text("Per favore, fornisci la password. Es: /login MIA_PASSWORD")
        return
    password_attempt = args[0]
    if authenticate_user(uid, password_attempt):
        await update.message.reply_text("Autenticazione avvenuta con successo!")
        if not get_minecraft_username(uid):
            context.user_data["awaiting_mc_username"] = True
            context.user_data["next_action_after_username"] = "post_login_greeting"
            await update.message.reply_text("Per favore, inserisci ora il tuo nome utente Minecraft:")
        else:
            await update.message.reply_text(f"Bentornato! Username Minecraft: {get_minecraft_username(uid)}")
    else:
        await update.message.reply_text("Password errata.")

@auth_required
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logout_user(update.effective_user.id)
    await update.message.reply_text("Logout eseguito.")

@auth_required
async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("Variabile CONTAINER non impostata.")
        return
    try:
        output = await run_docker_command(["docker", "logs", "--tail", "50", CONTAINER], read_output=True, timeout=10)
        safe_output = html.escape(output or "(Nessun output dai log)")
        await update.message.reply_text(f"<b>Ultimi log ({CONTAINER}):</b>\n<pre>{safe_output[:3900]}</pre>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Errore logs_command: {e}", exc_info=True)
        await update.message.reply_text(f"Errore recuperando i log: {html.escape(str(e))}")

@auth_required
async def edituser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cosa vuoi fare?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Modifica username", callback_data="edit_username")],
        [InlineKeyboardButton("🗑️ Cancella posizione", callback_data="delete_location")]
    ]))

@auth_required
async def cmd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("Variabile CONTAINER non impostata.")
        return
    
    if not update.message or not update.message.text:
        logger.warning("cmd_command: update.message o update.message.text è None.")
        await update.message.reply_text("Errore: impossibile leggere il comando.")
        return

    command_entity = next((e for e in update.message.entities or [] if e.type == "bot_command" and e.offset == 0), None)
    
    if not command_entity:
        logger.warning("cmd_command: Nessuna entità bot_command trovata per /cmd.")
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

    await update.message.reply_text(f"Invio di {len(commands_to_run)} comandi...")
    for i, single_command in enumerate(commands_to_run):
        try:
            await run_docker_command(["docker", "exec", CONTAINER, "send-command", single_command], read_output=False)
            await update.message.reply_text(f"Comando {i+1} (<code>{html.escape(single_command)}</code>) inviato.", parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.2) 
        except Exception as e:
            await update.message.reply_text(f"Errore inviando comando {i+1} (<code>{html.escape(single_command)}</code>): {html.escape(str(e))}", parse_mode=ParseMode.HTML)
            logger.error(f"Errore cmd_command '{single_command}': {e}", exc_info=True)
            break


@auth_required
async def scarica_items_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Avvio aggiornamento lista item...")
    updated_items = await asyncio.to_thread(refresh_items)
    await update.message.reply_text(f"Scaricati {len(updated_items)} item." if updated_items else "Errore scaricamento item.")

@auth_required
async def saveloc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not get_minecraft_username(uid):
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action_after_username"] = "saveloc"
        await update.message.reply_text("Inserisci il tuo username Minecraft:")
        return
    context.user_data["awaiting_saveloc_name"] = True
    await update.message.reply_text("Nome per la posizione da salvare:")

@auth_required
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_minecraft_username(update.effective_user.id): 
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action_after_username"] = "menu"
        await update.message.reply_text("Inserisci il tuo username Minecraft:")
        return
    await update.message.reply_text("Scegli un'azione:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Give", callback_data="menu_give")],
        [InlineKeyboardButton("🚀 Teleport", callback_data="menu_tp")],
        [InlineKeyboardButton("☀️ Meteo", callback_data="menu_weather")]
    ]))

@auth_required
async def give_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_minecraft_username(update.effective_user.id):
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action_after_username"] = "give"
        await update.message.reply_text("Inserisci il tuo username Minecraft:")
        return
    context.user_data["awaiting_give_prefix"] = True
    await update.message.reply_text("Nome o ID dell'oggetto da dare:")

@auth_required
async def tp_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not get_minecraft_username(uid):
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action_after_username"] = "tp"
        await update.message.reply_text("Inserisci il tuo username Minecraft:")
        return
    try:
        online_players = await get_online_players_from_server()
        buttons = []
        if online_players:
            buttons.extend([InlineKeyboardButton(p, callback_data=f"tp_player:{p}") for p in online_players])
        buttons.append(InlineKeyboardButton("📍 Inserisci coordinate", callback_data="tp_coords_input"))
        user_locs = get_locations(uid)
        for name_loc in user_locs: 
            buttons.append(InlineKeyboardButton(f"📌 {name_loc}", callback_data=f"tp_saved:{name_loc}"))
        
        if not buttons:
            await update.message.reply_text("Nessuna opzione di teletrasporto rapido disponibile.")
            return
            
        keyboard_layout = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        markup = InlineKeyboardMarkup(keyboard_layout)
        await update.message.reply_text("Scegli destinazione teletrasporto:", reply_markup=markup)

    except Exception as e:
        logger.error(f"Errore in tp_direct_command: {e}", exc_info=True)
        await update.message.reply_text("Errore preparando opzioni di teletrasporto.")


@auth_required
async def weather_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_minecraft_username(update.effective_user.id):
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action_after_username"] = "weather"
        await update.message.reply_text("Inserisci il tuo username Minecraft:")
        return
    await update.message.reply_text("Scegli il meteo:", reply_markup=InlineKeyboardMarkup([
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
    if not quiet and reply_target: await reply_target.reply_text(f"⏳ Arresto '{CONTAINER}'...")
    try:
        await run_docker_command(["docker", "stop", CONTAINER], read_output=True, timeout=45)
        if not quiet and reply_target: await reply_target.reply_text(f"✅ '{CONTAINER}' arrestato.")
        return True 
    except Exception as e:
        logger.error(f"Errore stop_server_command: {e}", exc_info=True)
        if not quiet and reply_target: await reply_target.reply_text(f"❌ Errore arresto: {html.escape(str(e))}")
    return False

@auth_required
async def start_server_command(update: Update, context: ContextTypes.DEFAULT_TYPE, quiet: bool = False) -> bool:
    reply_target = update.message or (update.callback_query.message if update.callback_query else None)
    if not CONTAINER:
        if not quiet and reply_target: await reply_target.reply_text("⚠️ CONTAINER non impostato.")
        return False
    if not quiet and reply_target: await reply_target.reply_text(f"⏳ Avvio '{CONTAINER}'...")
    try:
        await run_docker_command(["docker", "start", CONTAINER], read_output=True, timeout=30)
        if not quiet and reply_target: await reply_target.reply_text(f"✅ '{CONTAINER}' avviato.")
        return True 
    except subprocess.CalledProcessError as e:
        err_str = (e.stderr or str(e.output) or str(e)).lower()
        if "is already started" in err_str:
            if not quiet and reply_target: await reply_target.reply_text(f"ℹ️ '{CONTAINER}' è già avviato.")
            return True
        raise 
    except Exception as e:
        logger.error(f"Errore start_server_command: {e}", exc_info=True)
        if not quiet and reply_target: await reply_target.reply_text(f"❌ Errore avvio: {html.escape(str(e))}")
    return False

@auth_required
async def restart_server_command(update: Update, context: ContextTypes.DEFAULT_TYPE, quiet: bool = False):
    reply_target = update.message or (update.callback_query.message if update.callback_query else None)
    if not CONTAINER:
        if not quiet and reply_target: await reply_target.reply_text("⚠️ CONTAINER non impostato.")
        return
        
    if not reply_target: # Should not happen if called by a command or callback
        logger.error("restart_server_command: Impossibile determinare dove rispondere.")
        return

    if not quiet: await reply_target.reply_text(f"⏳ Riavvio '{CONTAINER}'...")
    try:
        await run_docker_command(["docker", "restart", CONTAINER], read_output=False, timeout=60)
        logger.info(f"Comando 'docker restart {CONTAINER}' inviato.")
        if not quiet: await reply_target.reply_text(f"✅ Comando di riavvio per '{CONTAINER}' inviato. Controlla i /logs per conferma.")
    except Exception as e:
        logger.error(f"Errore restart_server_command: {e}", exc_info=True)
        if not quiet: await reply_target.reply_text(f"❌ Errore riavvio: {html.escape(str(e))}")


@auth_required
async def backup_world_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER or not WORLD_NAME:
        await update.message.reply_text("CONTAINER o WORLD_NAME non configurati.")
        return
    await update.message.reply_text(f"Avvio backup per '{WORLD_NAME}'...")
    
    stopped = await stop_server_command(update, context)
    if not stopped:
        await update.message.reply_text("Backup annullato: impossibile arrestare il server.")
        await _restart_server_after_action(update, context, CONTAINER, "backup (errore stop)")
        return

    await update.message.reply_text("Attesa rilascio file...")
    await asyncio.sleep(5)

    world_dir_path = get_world_directory_path(WORLD_NAME)
    backups_storage = get_backups_storage_path()

    if not world_dir_path or not os.path.exists(world_dir_path):
        await update.message.reply_text(f"Directory del mondo '{WORLD_NAME}' non trovata. Backup annullato.")
        await _restart_server_after_action(update, context, CONTAINER, "backup (path non trovato)")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_world_name = "".join(c if c.isalnum() else "_" for c in WORLD_NAME)
    archive_name_base = os.path.join(backups_storage, f"{safe_world_name}_backup_{timestamp}")
    
    try:
        await update.message.reply_text("Creazione archivio zip...")
        await asyncio.to_thread(
            shutil.make_archive,
            base_name=archive_name_base,
            format='zip',
            root_dir=os.path.dirname(world_dir_path),
            base_dir=os.path.basename(world_dir_path)
        )
        final_archive_name = f"{archive_name_base}.zip"
        await update.message.reply_text(f"✅ Backup completato: <code>{html.escape(os.path.basename(final_archive_name))}</code>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Errore creazione backup: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore creazione backup: {html.escape(str(e))}")
    finally:
        await _restart_server_after_action(update, context, CONTAINER, "backup")


async def _restart_server_after_action(update: Update, context: ContextTypes.DEFAULT_TYPE, container_name: str, action_name: str):
    await restart_server_command(update, context, quiet=False) 


@auth_required
async def list_backups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    backups_dir = get_backups_storage_path()
    if not os.path.exists(backups_dir):
        await update.message.reply_text(f"Directory backup ({backups_dir}) non trovata.")
        return
    try:
        backup_files = sorted(
            [f for f in os.listdir(backups_dir) if f.endswith(".zip")],
            key=lambda f: os.path.getmtime(os.path.join(backups_dir, f)),
            reverse=True
        )
    except Exception as e:
        await update.message.reply_text(f"Errore lettura directory backup: {html.escape(str(e))}")
        return

    if not backup_files:
        await update.message.reply_text("Nessun backup .zip trovato.")
        return

    buttons = []
    for filename in backup_files[:15]: 
        cb_data = f"download_backup_file:{filename}"
        if len(cb_data.encode('utf-8')) <= 64:
            buttons.append([InlineKeyboardButton(f"📥 {filename}", callback_data=cb_data)])
        else:
            logger.warning(f"Nome file backup '{filename}' troppo lungo per callback_data.")
    
    if not buttons and backup_files:
        await update.message.reply_text("Nomi file backup troppo lunghi per bottoni diretti.")
        return
    elif not buttons: 
        await update.message.reply_text("Nessun backup disponibile per download via bottoni.")
        return

    await update.message.reply_text("Seleziona backup da scaricare (più recenti prima):", reply_markup=InlineKeyboardMarkup(buttons))


@auth_required
async def imnotcreative_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER or not WORLD_NAME:
        await update.message.reply_text("CONTAINER o WORLD_NAME non configurati.")
        return
    
    user_input = " ".join(context.args).strip().lower()
    if user_input != "conferma":
        await update.message.reply_text(
            "ATTENZIONE: Questo comando modifica i file del mondo e arresta temporaneamente il server.\n"
            f"Mondo target: '{WORLD_NAME}'.\n"
            "Digita `/imnotcreative conferma` per procedere.",
            parse_mode=ParseMode.HTML 
        )
        return

    await update.message.reply_text(f"Avvio /imnotcreative per '{WORLD_NAME}'...")
    stopped = await stop_server_command(update, context)
    if not stopped:
        await update.message.reply_text("Operazione annullata: impossibile arrestare il server.")
        await _restart_server_after_action(update, context, CONTAINER, "imnotcreative (errore stop)")
        return

    await update.message.reply_text("Attesa rilascio file...")
    await asyncio.sleep(5)
    
    success, message = await reset_creative_flag(WORLD_NAME)
    await update.message.reply_text(f"{'✅' if success else '⚠️'} {html.escape(message)}")
    
    await _restart_server_after_action(update, context, CONTAINER, "imnotcreative")


# --- Comandi per Resource Pack ---
@auth_required
async def add_resourcepack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not WORLD_NAME:
        await update.message.reply_text("⚠️ `WORLD_NAME` non impostato. Impossibile aggiungere resource pack.")
        return
    await update.message.reply_text(
        "Ok! Inviami il file del resource pack (.mcpack o .zip) o un link diretto.\n\n"
        "ℹ️ I nuovi pacchetti vengono aggiunti con priorità più bassa (caricati per primi nel file JSON)." 
    )
    context.user_data["awaiting_resource_pack"] = True

@auth_required
async def edit_resourcepacks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra i resource pack attivi e permette di modificarne l'ordine o rimuoverli."""
    if not WORLD_NAME:
        await update.message.reply_text("⚠️ `WORLD_NAME` non impostato. Impossibile modificare i resource pack.")
        return

    try:
        active_packs_details = await asyncio.to_thread(get_world_active_packs_with_details, WORLD_NAME)
    except Exception as e:
        logger.error(f"Errore ottenendo dettagli dei resource pack attivi: {e}", exc_info=True)
        await update.message.reply_text(f"Errore nel recuperare i dettagli dei pacchetti: {html.escape(str(e))}")
        return

    if not active_packs_details:
        await update.message.reply_text("Nessun resource pack attivo trovato per questo mondo.")
        return

    message_text = "Resource pack attivi (il primo ha priorità più bassa, l'ultimo più alta):\n"
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
        message_text = "Resource pack attivi (lista troppo lunga, vedi bottoni):\n"

    await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
