# minecraft_telegram_bot/command_handlers.py
import asyncio
import subprocess
import re
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, WORLD_NAME, get_logger 

from user_management import (
    auth_required, authenticate_user, logout_user,
    get_minecraft_username, set_minecraft_username,
    get_user_data, get_locations
)
from item_management import refresh_items, get_items
from docker_utils import run_docker_command, get_online_players_from_server
from world_management import reset_creative_flag


logger = get_logger(__name__)


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
        "/cmd &lt;comando_minecraft&gt;\n"
        "#eventuale_altro_comando_su_nuova_riga\n"
        "#eventuale_commento_che_verra_ignorato\n"
        "say Altro comando # con commento a fine riga\n"
        "- Esegui uno o più comandi sulla console del server. "
        "Le righe che iniziano con # sono ignorate. "
        "I commenti a fine riga (testo dopo #) sono ignorati.\n"
        "I comandi Minecraft NON devono iniziare con / dentro questo blocco.\n"
        "/logs - Mostra ultimi log del server\n"
        "\n<b>Gestione Container Server (Richiede autenticazione):</b>\n"
        "/startserver - Avvia il container del server Minecraft\n"
        "/stopserver - Arresta il container del server Minecraft\n"
        "/restartserver - Riavvia il container del server Minecraft\n"
        "/imnotcreative - Resetta il flag 'HasBeenLoadedInCreative' del mondo (richiede conferma)\n"
        "\n<b>Utility Bot:</b>\n"
        "/scarica_items - Aggiorna lista oggetti Minecraft\n\n"
        "<i>Puoi anche digitare @&lt;nome_bot&gt; + nome oggetto per suggerimenti inline.</i>"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


@auth_required
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args
    if get_minecraft_username(uid) and get_user_data(uid):
        await update.message.reply_text("Sei già autenticato e il tuo username è impostato.")
        return
    if not args:
        await update.message.reply_text("Per favore, fornisci la password. Es: /login MIA_PASSWORD")
        return

    password_attempt = args[0]
    if authenticate_user(uid, password_attempt):
        await update.message.reply_text("Autenticazione avvenuta con successo!")
        if not get_minecraft_username(uid):
            context.user_data["awaiting_mc_username"] = True
            await update.message.reply_text(
                "Per favore, inserisci ora il tuo nome utente Minecraft:"
            )
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
        await update.message.reply_text("Variabile CONTAINER non impostata. Impossibile recuperare i log.")
        return
    try:
        command_args = ["docker", "logs", "--tail", "50", CONTAINER]
        output = await run_docker_command(command_args, read_output=True, timeout=10)
        output = output or "(Nessun output dai log)"
        safe_output = html.escape(output)
        msg = f"<b>Ultimi 50 log del server ({CONTAINER}):</b>\n<pre>{safe_output[:3900]}</pre>"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except asyncio.TimeoutError:
        await update.message.reply_text("Errore: Timeout durante il recupero dei log.")
    except subprocess.CalledProcessError as e:
        error_output = html.escape(e.stderr or e.output or str(e))
        await update.message.reply_text(f"Errore nel comando Docker per i log: <pre>{error_output}</pre>", parse_mode=ParseMode.HTML)
    except ValueError as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.error(f"Errore imprevisto logs_command: {e}", exc_info=True)
        await update.message.reply_text(f"Errore imprevisto recuperando i log: {e}")


@auth_required
async def edituser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("✏️ Modifica username",
                              callback_data="edit_username")],
        [InlineKeyboardButton("🗑️ Cancella posizione salvata",
                              callback_data="delete_location")],
    ]
    await update.message.reply_text("Cosa vuoi fare?", reply_markup=InlineKeyboardMarkup(kb))


@auth_required
async def cmd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("Variabile CONTAINER non impostata. Impossibile eseguire comandi.")
        return

    full_message_text = update.message.text
    command_entity = None
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == "bot_command" and entity.offset == 0:
                command_entity = entity
                break
    
    if not command_entity:
        logger.warning("cmd_command: Impossibile trovare l'entità del comando nel messaggio.")
        await update.message.reply_text("Errore interno: impossibile identificare il comando /cmd.")
        return

    raw_command_block = full_message_text[command_entity.length:].strip()

    if not raw_command_block:
        await update.message.reply_text(
            "Specifica uno o più comandi da inviare al server dopo /cmd. Esempio:\n"
            "/cmd list\n"
            "# Questo è un commento ignorato\n"
            "say Ciao a tutti #questo commento a fine riga è ignorato\n"
            "I comandi Minecraft NON devono iniziare con /."
        )
        return

    commands_to_execute = []
    processed_lines_info = [] 

    for line_number, line_content in enumerate(raw_command_block.splitlines(), 1):
        # 1. Pulisci la riga da spazi bianchi esterni
        processed_line = line_content.strip()

        # 2. Ignora righe completamente vuote
        if not processed_line:
            processed_lines_info.append(f"<i>Riga {line_number}: Vuota, ignorata.</i>")
            continue

        # 3. Ignora righe che iniziano con # (commenti interi)
        if processed_line.startswith("#"):
            display_comment = html.escape(processed_line[:50]) + ('...' if len(processed_line) > 50 else '')
            processed_lines_info.append(f"<i>Riga {line_number}: Commento intera riga ('{display_comment}'), ignorata.</i>")
            continue

        # 4. Estrai la parte di comando prima di un eventuale # a fine riga
        command_candidate = processed_line
        hash_index = processed_line.find("#")
        if hash_index != -1:
            command_candidate = processed_line[:hash_index].strip()
        
        # 5. Se la parte di comando è vuota (es. riga era "   # commento"), ignorala
        if not command_candidate:
            display_line_part = html.escape(processed_line[:50]) + ('...' if len(processed_line) > 50 else '')
            processed_lines_info.append(f"<i>Riga {line_number}: Contenuto prima di '#' vuoto ('{display_line_part}'), ignorata.</i>")
            continue
            
        # 6. Rimuovi lo slash iniziale dal comando, se presente
        final_command_text = command_candidate
        if final_command_text.startswith("/"):
            final_command_text = final_command_text[1:].strip()

        # 7. Se il comando finale è vuoto (es. la riga era solo "/" o "/   " prima del commento), ignoralo
        if not final_command_text:
            display_line_part = html.escape(processed_line[:50]) + ('...' if len(processed_line) > 50 else '')
            processed_lines_info.append(f"<i>Riga {line_number}: Comando vuoto dopo pulizia slash ('{display_line_part}'), ignorata.</i>")
            continue
            
        commands_to_execute.append({
            'text': final_command_text, 
            'original_line_number': line_number
        })

    if not commands_to_execute:
        feedback_message = "Nessun comando eseguibile trovato nel messaggio."
        if processed_lines_info:
            feedback_message += "\n\n<b>Dettaglio linee processate:</b>\n" + "\n".join(processed_lines_info)
        await update.message.reply_text(feedback_message, parse_mode=ParseMode.HTML)
        return

    await update.message.reply_text(
        f"Trovati {len(commands_to_execute)} comandi. Inizio elaborazione..."
    )
    
    for cmd_info in commands_to_execute:
        command_text = cmd_info['text']
        line_num = cmd_info['original_line_number']

        try:
            docker_command_args = ["docker", "exec", CONTAINER, "send-command", command_text]
            logger.info(f"Esecuzione comando server da riga {line_num} (multilinea /cmd): {' '.join(docker_command_args)}")
            
            await run_docker_command(docker_command_args, read_output=False, timeout=10)
            
            msg = f"✅ Riga {line_num}: Inviato <code>{html.escape(command_text)}</code>"
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.3) 

        except asyncio.TimeoutError:
            error_msg = f"⌛ Riga {line_num}: Timeout eseguendo <code>{html.escape(command_text)}</code>"
            logger.error(f"Timeout cmd_command (multilinea, riga {line_num}): '{command_text}'.")
            await update.message.reply_text(error_msg, parse_mode=ParseMode.HTML)
        except subprocess.CalledProcessError as e:
            error_details = html.escape(e.stderr or str(e.output) or str(e))
            error_msg = f"❌ Riga {line_num}: Errore Docker eseguendo <code>{html.escape(command_text)}</code>:\n<pre>{error_details[:500]}</pre>"
            logger.error(f"CalledProcessError cmd_command (multilinea, riga {line_num}) '{command_text}': {e.stderr or e.output or e}")
            await update.message.reply_text(error_msg, parse_mode=ParseMode.HTML)
        except ValueError as e: 
            error_msg = f"❗ Riga {line_num}: Errore (ValueError) per <code>{html.escape(command_text)}</code>: {html.escape(str(e))}"
            await update.message.reply_text(error_msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            error_msg = f"🆘 Riga {line_num}: Errore imprevisto per <code>{html.escape(command_text)}</code>:\n<pre>{html.escape(str(e)[:500])}</pre>"
            logger.error(f"Errore imprevisto cmd_command (multilinea, riga {line_num}) '{command_text}': {e}", exc_info=True)
            await update.message.reply_text(error_msg, parse_mode=ParseMode.HTML)
        
    final_summary_parts = ["🏁 Elaborazione comandi multipli completata."]
    if processed_lines_info: 
        final_summary_parts.append("\n<b>Linee ignorate o commenti:</b>")
        final_summary_parts.extend(processed_lines_info)
    
    final_summary_parts.append("\nL'output dei comandi (se presente) apparirà nei log del server (visibili con /logs).")
    await update.message.reply_text("\n".join(final_summary_parts), parse_mode=ParseMode.HTML)


@auth_required
async def scarica_items_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Avvio aggiornamento lista item...")
    updated_items = await asyncio.to_thread(refresh_items)
    if updated_items:
        await update.message.reply_text(f"Scaricati {len(updated_items)} item da Minecraft.")
    else:
        current_items = get_items()
        if current_items:
            await update.message.reply_text(
                f"Errore durante lo scaricamento degli item. Utilizzo la lista precedentemente caricata ({len(current_items)} item). "
                "Controlla i log del bot per dettagli sull'errore di download."
            )
        else:
            await update.message.reply_text(
                "Errore critico: impossibile scaricare o caricare la lista degli item. "
                "La funzionalità di give potrebbe non funzionare. Controlla i log del bot."
            )


@auth_required
async def saveloc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    mc_username = get_minecraft_username(uid)
    if not mc_username:
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action"] = "saveloc"
        await update.message.reply_text(
            "Sembra che il tuo username Minecraft non sia impostato. "
            "Inseriscilo ora, poi riprova /saveloc:"
        )
        return

    context.user_data["awaiting_saveloc_name"] = True
    await update.message.reply_text("Inserisci un nome per la posizione che vuoi salvare:")


@auth_required
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not get_minecraft_username(uid):
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action"] = "menu"
        await update.message.reply_text(
            "Sembra che il tuo username Minecraft non sia impostato. Inseriscilo ora:"
        )
        return

    kb = [
        [InlineKeyboardButton("🎁 Give item", callback_data="menu_give")],
        [InlineKeyboardButton("🚀 Teleport", callback_data="menu_tp")],
        [InlineKeyboardButton("☀️ Meteo", callback_data="menu_weather")]
    ]
    await update.message.reply_text("Scegli un'azione:", reply_markup=InlineKeyboardMarkup(kb))


@auth_required
async def give_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not get_minecraft_username(uid):
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action"] = "give"
        await update.message.reply_text(
            "Sembra che il tuo username Minecraft non sia impostato. "
            "Inseriscilo ora, poi potrai usare /give:"
        )
        return
    context.user_data["awaiting_give_prefix"] = True
    await update.message.reply_text(
        "Ok, inviami il nome (o parte del nome/ID) dell'oggetto che vuoi dare:"
    )


@auth_required
async def tp_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    minecraft_username = get_minecraft_username(uid)
    if not minecraft_username:
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action"] = "tp"
        await update.message.reply_text(
            "Sembra che il tuo username Minecraft non sia impostato. "
            "Inseriscilo ora, poi potrai usare /tp:"
        )
        return

    try:
        online_players = await get_online_players_from_server()
        buttons = []
        if online_players:
            buttons.extend([
                InlineKeyboardButton(p, callback_data=f"tp_player:{p}")
                for p in online_players
            ])
        buttons.append(InlineKeyboardButton(
            "📍 Inserisci coordinate", callback_data="tp_coords_input"))

        user_locs = get_locations(uid)
        for name in user_locs:
            buttons.append(InlineKeyboardButton(
                f"📌 {name}", callback_data=f"tp_saved:{name}"))

        keyboard_layout = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        markup = InlineKeyboardMarkup(keyboard_layout)

        text_reply = "Scegli una destinazione per il teletrasporto:"
        if not online_players and not CONTAINER:
            text_reply = (
                "Impossibile ottenere la lista giocatori (CONTAINER non settato o server non raggiungibile).\n"
                "Puoi usare le posizioni salvate o inserire coordinate manualmente."
            )
        elif not online_players:
            text_reply = (
                "Nessun giocatore online trovato.\n"
                "Puoi usare le posizioni salvate o inserire coordinate manualmente:"
            )
        await update.message.reply_text(text_reply, reply_markup=markup)

    except ValueError as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.error(f"Errore in /tp command: {e}", exc_info=True)
        await update.message.reply_text(
            "Si è verificato un errore durante la preparazione del menu di teletrasporto."
        )


@auth_required
async def weather_direct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not get_minecraft_username(uid):
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action"] = "weather"
        await update.message.reply_text(
            "Sembra che il tuo username Minecraft non sia impostato. "
            "Inseriscilo ora, poi potrai usare /weather:"
        )
        return

    buttons = [
        [InlineKeyboardButton("☀️ Sereno (Clear)",
                              callback_data="weather_set:clear")],
        [InlineKeyboardButton("🌧 Pioggia (Rain)",
                              callback_data="weather_set:rain")],
        [InlineKeyboardButton("⛈ Temporale (Thunder)",
                              callback_data="weather_set:thunder")]
    ]
    await update.message.reply_text(
        "Scegli le condizioni meteo:", reply_markup=InlineKeyboardMarkup(buttons)
    )


@auth_required
async def stop_server_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("⚠️ Variabile CONTAINER non impostata. Impossibile arrestare il server.")
        return

    await update.message.reply_text(f"⏳ Tentativo di arrestare il container '{CONTAINER}'...")
    try:
        await run_docker_command(["docker", "stop", CONTAINER], read_output=True, timeout=30)
        logger.info(
            f"Comando 'docker stop {CONTAINER}' eseguito con successo.")
        await update.message.reply_text(f"✅ Container '{CONTAINER}' arrestato con successo.")
    except asyncio.TimeoutError:
        logger.error(f"Timeout durante l'arresto del container {CONTAINER}.")
        await update.message.reply_text(f"⌛ Timeout: l'arresto del container '{CONTAINER}' sta richiedendo più tempo del previsto. Controlla manualmente lo stato.")
    except subprocess.CalledProcessError as e:
        error_message = html.escape(e.stderr or str(e.output) or str(e))
        logger.error(
            f"Errore durante l'arresto del container {CONTAINER}: {e.stderr or e.output or e}")
        await update.message.reply_text(f"❌ Errore durante l'arresto di '{CONTAINER}':\n<pre>{error_message}</pre>", parse_mode=ParseMode.HTML)
    except ValueError as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.error(
            f"Errore imprevisto in stop_server_command: {e}", exc_info=True)
        await update.message.reply_text(f"🆘 Errore imprevisto durante l'arresto del server: {e}")


@auth_required
async def start_server_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("⚠️ Variabile CONTAINER non impostata. Impossibile avviare il server.")
        return

    await update.message.reply_text(f"⏳ Tentativo di avviare il container '{CONTAINER}'...")
    try:
        await run_docker_command(["docker", "start", CONTAINER], read_output=True, timeout=30)
        logger.info(
            f"Comando 'docker start {CONTAINER}' eseguito con successo.")
        await update.message.reply_text(f"✅ Container '{CONTAINER}' avviato con successo.")
    except asyncio.TimeoutError:
        logger.error(f"Timeout durante l'avvio del container {CONTAINER}.")
        await update.message.reply_text(f"⌛ Timeout: l'avvio del container '{CONTAINER}' sta richiedendo più tempo del previsto. Potrebbe essere già in esecuzione o avere problemi.")
    except subprocess.CalledProcessError as e:
        error_message = html.escape(e.stderr or str(e.output) or str(e))
        logger.error(
            f"Errore durante l'avvio del container {CONTAINER}: {e.stderr or e.output or e}")
        await update.message.reply_text(f"❌ Errore durante l'avvio di '{CONTAINER}':\n<pre>{error_message}</pre>", parse_mode=ParseMode.HTML)
    except ValueError as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.error(
            f"Errore imprevisto in start_server_command: {e}", exc_info=True)
        await update.message.reply_text(f"🆘 Errore imprevisto durante l'avvio del server: {e}")


@auth_required
async def restart_server_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("⚠️ Variabile CONTAINER non impostata. Impossibile riavviare il server.")
        return

    await update.message.reply_text(f"⏳ Tentativo di riavviare il container '{CONTAINER}'...")
    try:
        await run_docker_command(["docker", "restart", CONTAINER], read_output=True, timeout=45)
        logger.info(
            f"Comando 'docker restart {CONTAINER}' eseguito con successo.")
        await update.message.reply_text(f"✅ Container '{CONTAINER}' riavviato con successo.")
    except asyncio.TimeoutError:
        logger.error(f"Timeout durante il riavvio del container {CONTAINER}.")
        await update.message.reply_text(f"⌛ Timeout: il riavvio del container '{CONTAINER}' sta richiedendo più tempo del previsto. Controlla manualmente.")
    except subprocess.CalledProcessError as e:
        error_message = html.escape(e.stderr or str(e.output) or str(e))
        logger.error(
            f"Errore durante il riavvio del container {CONTAINER}: {e.stderr or e.output or e}")
        await update.message.reply_text(f"❌ Errore durante il riavvio di '{CONTAINER}':\n<pre>{error_message}</pre>", parse_mode=ParseMode.HTML)
    except ValueError as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.error(
            f"Errore imprevisto in restart_server_command: {e}", exc_info=True)
        await update.message.reply_text(f"🆘 Errore imprevisto durante il riavvio del server: {e}")


@auth_required
async def imnotcreative_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("⚠️ Variabile CONTAINER non impostata. Impossibile procedere.")
        return
    if not WORLD_NAME:
        await update.message.reply_text("⚠️ Variabile WORLD_NAME non impostata in configurazione. Impossibile trovare il mondo.")
        return

    user_input = " ".join(context.args).strip().lower()
    if user_input != "conferma":
        await update.message.reply_text(
            "Questo comando modificherà i file del mondo per resettare lo stato 'creativo'.\n"
            "🛑 Il server Minecraft verrà arrestato temporaneamente.\n"
            f"🌎 Mondo target: '{WORLD_NAME}'\n\n"
            "Per procedere, digita: `/imnotcreative conferma`",
            parse_mode=ParseMode.HTML
        )
        return

    await update.message.reply_text(f"⏳ Inizio procedura '/imnotcreative' per il mondo '{WORLD_NAME}'...")

    stopped_successfully = False
    try:
        await update.message.reply_text(f"🛑 Arresto del container '{CONTAINER}' in corso...")
        await run_docker_command(["docker", "stop", CONTAINER], read_output=True, timeout=45)
        logger.info(f"Container '{CONTAINER}' arrestato con successo.")
        await update.message.reply_text(f"✅ Container '{CONTAINER}' arrestato.")
        stopped_successfully = True
    except asyncio.TimeoutError:
        logger.error(f"Timeout durante l'arresto del container {CONTAINER} per imnotcreative.")
        await update.message.reply_text(f"⌛ Timeout arresto container '{CONTAINER}'. Potrebbe essere necessario un controllo manuale.")
    except subprocess.CalledProcessError as e:
        error_message = html.escape(e.stderr or str(e.output) or str(e))
        logger.error(
            f"Errore durante l'arresto del container {CONTAINER} per imnotcreative: {e.stderr or e.output or e}")
        await update.message.reply_text(f"❌ Errore arresto container '{CONTAINER}':\n<pre>{error_message}</pre>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(
            f"Errore imprevisto durante l'arresto per imnotcreative: {e}", exc_info=True)
        await update.message.reply_text(f"🆘 Errore imprevisto durante l'arresto: {e}")

    if not stopped_successfully:
        await update.message.reply_text("❌ Procedura '/imnotcreative' interrotta a causa di problemi con l'arresto del server.")
        await update.message.reply_text(f"⚠️ Tentativo di riavviare il server '{CONTAINER}' per sicurezza...")
        try:
            await run_docker_command(["docker", "start", CONTAINER], read_output=True, timeout=30)
            await update.message.reply_text(f"✅ Server '{CONTAINER}' dovrebbe essere in fase di riavvio.")
        except Exception as e_restart:
            await update.message.reply_text(f"❌ Fallito tentativo di riavvio: {e_restart}. Controllare Docker manualmente.")
        return

    await update.message.reply_text("⏱ Attesa di qualche secondo per il rilascio dei file...")
    await asyncio.sleep(5)

    await update.message.reply_text(f"⚙️ Modifica di 'level.dat' per il mondo '{WORLD_NAME}' in corso...")
    success, message = await reset_creative_flag(WORLD_NAME) 
    if success:
        await update.message.reply_text(f"✅ {html.escape(message)}")
    else:
        await update.message.reply_text(f"⚠️ {html.escape(message)}")

    await update.message.reply_text(f"🚀 Riavvio del container '{CONTAINER}' in corso...")
    try:
        await run_docker_command(["docker", "start", CONTAINER], read_output=True, timeout=30)
        logger.info(f"Container '{CONTAINER}' avviato con successo post imnotcreative.")
        await update.message.reply_text(f"✅ Container '{CONTAINER}' avviato. Il server dovrebbe essere di nuovo online.")
    except asyncio.TimeoutError:
        logger.error(f"Timeout durante l'avvio del container {CONTAINER} post imnotcreative.")
        await update.message.reply_text(f"⌛ Timeout avvio '{CONTAINER}'. Controlla manualmente, potrebbe essere già attivo o avere problemi.")
    except subprocess.CalledProcessError as e:
        error_message = html.escape(e.stderr or str(e.output) or str(e))
        logger.error(
            f"Errore durante l'avvio del container {CONTAINER} post imnotcreative: {e.stderr or e.output or e}")
        await update.message.reply_text(f"❌ Errore avvio '{CONTAINER}':\n<pre>{error_message}</pre>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Errore imprevisto durante l'avvio post imnotcreative: {e}", exc_info=True)
        await update.message.reply_text(f"🆘 Errore imprevisto durante l'avvio: {e}")

    await update.message.reply_text("ℹ️ Procedura '/imnotcreative' completata.")