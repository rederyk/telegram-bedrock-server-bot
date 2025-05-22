# minecraft_telegram_bot/command_handlers.py
import asyncio
import subprocess
import re
import html
import os
import shutil
from datetime import datetime
import tempfile # Per la gestione temporanea di file/directory
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Document
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, WORLD_NAME, get_logger # Assicurati che WORLD_NAME sia importato
from world_management import (
    reset_creative_flag, get_world_directory_path, get_backups_storage_path,
    # Non sono necessarie importazioni dirette da world_management per i resource pack qui,
    # poiché la logica è in resource_pack_management
)
from user_management import (
    auth_required, authenticate_user, logout_user,
    get_minecraft_username, # set_minecraft_username non usato direttamente qui
    get_user_data, get_locations
)
from item_management import refresh_items, get_items
from docker_utils import run_docker_command, get_online_players_from_server

# Importazioni per la gestione dei Resource Pack
from resource_pack_management import (
    ResourcePackError # Non usiamo direttamente le altre funzioni qui, ma l'eccezione sì
    # Le funzioni specifiche sono chiamate in message_handlers
)


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
        "/backup_world - Ferma il server, crea un backup del mondo e lo salva.\n"
        "/list_backups - Mostra i backup disponibili e permette di scaricarli.\n"
        "/addresourcepack - Avvia il processo per aggiungere un nuovo resource pack al mondo.\n" # <<< NUOVA VOCE HELP
        "\n<b>Utility Bot:</b>\n"
        "/scarica_items - Aggiorna lista oggetti Minecraft\n\n"
        "<i>Puoi anche digitare @&lt;nome_bot&gt; + nome oggetto per suggerimenti inline.</i>"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args
    if get_minecraft_username(uid) and get_user_data(uid): # Controlla se l'username è già impostato
        await update.message.reply_text("Sei già autenticato e il tuo username Minecraft è impostato.")
        return
    if not args:
        await update.message.reply_text("Per favore, fornisci la password. Es: /login MIA_PASSWORD")
        return

    password_attempt = args[0]
    if authenticate_user(uid, password_attempt):
        await update.message.reply_text("Autenticazione avvenuta con successo!")
        if not get_minecraft_username(uid): # Controlla di nuovo se l'username è impostato dopo l'autenticazione
            context.user_data["awaiting_mc_username"] = True
            context.user_data["next_action_after_username"] = "post_login_greeting" # Azione generica
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
        msg = f"<b>Ultimi 50 log del server ({CONTAINER}):</b>\n<pre>{safe_output[:3900]}</pre>" # Limita lunghezza messaggio
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except asyncio.TimeoutError:
        await update.message.reply_text("Errore: Timeout durante il recupero dei log.")
    except subprocess.CalledProcessError as e:
        error_output = html.escape(e.stderr or e.output or str(e))
        await update.message.reply_text(f"Errore nel comando Docker per i log: <pre>{error_output}</pre>", parse_mode=ParseMode.HTML)
    except ValueError as e: # Per CONTAINER non configurato
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
        processed_line = line_content.strip()
        if not processed_line:
            processed_lines_info.append(f"<i>Riga {line_number}: Vuota, ignorata.</i>")
            continue
        if processed_line.startswith("#"):
            display_comment = html.escape(processed_line[:50]) + ('...' if len(processed_line) > 50 else '')
            processed_lines_info.append(f"<i>Riga {line_number}: Commento intera riga ('{display_comment}'), ignorata.</i>")
            continue
        
        command_candidate = processed_line
        hash_index = processed_line.find("#")
        if hash_index != -1:
            command_candidate = processed_line[:hash_index].strip()
        
        if not command_candidate: # Se la linea conteneva solo un commento dopo # o era vuota prima di #
            display_line_part = html.escape(processed_line[:50]) + ('...' if len(processed_line) > 50 else '')
            processed_lines_info.append(f"<i>Riga {line_number}: Contenuto prima di '#' vuoto o solo spazi ('{display_line_part}'), ignorata.</i>")
            continue

        final_command_text = command_candidate
        # Non rimuovere lo slash iniziale qui, send-command lo gestisce o lo richiede per alcuni comandi bedrock
        # if final_command_text.startswith("/"):
        #     final_command_text = final_command_text[1:].strip()
        
        if not final_command_text: # Se dopo la pulizia (se ci fosse) il comando è vuoto
            display_line_part = html.escape(processed_line[:50]) + ('...' if len(processed_line) > 50 else '')
            processed_lines_info.append(f"<i>Riga {line_number}: Comando vuoto dopo elaborazione ('{display_line_part}'), ignorata.</i>")
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
            # send-command di Bedrock non sempre restituisce output significativo o codice di errore standard
            # quindi read_output=False è spesso appropriato, e si controllano i log per i risultati.
            await run_docker_command(docker_command_args, read_output=False, timeout=10) 
            msg = f"✅ Riga {line_num}: Inviato <code>{html.escape(command_text)}</code>"
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.3) # Breve pausa per non floodare il server/Docker
        except asyncio.TimeoutError:
            error_msg = f"⌛ Riga {line_num}: Timeout eseguendo <code>{html.escape(command_text)}</code>"
            logger.error(f"Timeout cmd_command (multilinea, riga {line_num}): '{command_text}'.")
            await update.message.reply_text(error_msg, parse_mode=ParseMode.HTML)
        except subprocess.CalledProcessError as e:
            error_details = html.escape(e.stderr or str(e.output) or str(e))
            error_msg = f"❌ Riga {line_num}: Errore Docker eseguendo <code>{html.escape(command_text)}</code>:\n<pre>{error_details[:500]}</pre>"
            logger.error(f"CalledProcessError cmd_command (multilinea, riga {line_num}) '{command_text}': {e.stderr or e.output or e}")
            await update.message.reply_text(error_msg, parse_mode=ParseMode.HTML)
        except ValueError as e: # Per CONTAINER non configurato
            error_msg = f"❗ Riga {line_num}: Errore (ValueError) per <code>{html.escape(command_text)}</code>: {html.escape(str(e))}"
            await update.message.reply_text(error_msg, parse_mode=ParseMode.HTML)
            break # Interrompi se c'è un errore di configurazione
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
    # refresh_items è sincrona, quindi la eseguiamo in un thread per non bloccare asyncio
    updated_items = await asyncio.to_thread(refresh_items)
    if updated_items:
        await update.message.reply_text(f"Scaricati {len(updated_items)} item.")
    else:
        current_items = get_items() # get_items è sincrona ma veloce (legge variabile globale)
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
        context.user_data["next_action_after_username"] = "saveloc" # Salva l'azione per dopo
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
        context.user_data["next_action_after_username"] = "menu" # Salva l'azione
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
        context.user_data["next_action_after_username"] = "give" # Salva l'azione
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
        context.user_data["next_action_after_username"] = "tp" # Salva l'azione
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
        user_locs = get_locations(uid) # Sincrona, veloce
        for name in user_locs:
            buttons.append(InlineKeyboardButton(
                f"📌 {name}", callback_data=f"tp_saved:{name}"))
        
        if not buttons: # Caso in cui non ci sono giocatori e non ci sono locazioni salvate
             await update.message.reply_text(
                "Nessun giocatore online e nessuna posizione salvata. "
                "Non ci sono destinazioni rapide disponibili per il teletrasporto.",
             )
             return

        keyboard_layout = [buttons[i:i+2] for i in range(0, len(buttons), 2)] # Layout a 2 colonne
        markup = InlineKeyboardMarkup(keyboard_layout)
        text_reply = "Scegli una destinazione per il teletrasporto:"
        if not online_players and not CONTAINER: # CONTAINER check è già in get_online_players
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
    except ValueError as e: # Per CONTAINER non configurato da get_online_players
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
        context.user_data["next_action_after_username"] = "weather" # Salva l'azione
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
async def stop_server_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool: # Aggiunto tipo di ritorno
    if not CONTAINER:
        await update.message.reply_text("⚠️ Variabile CONTAINER non impostata. Impossibile arrestare il server.")
        return False
    await update.message.reply_text(f"⏳ Tentativo di arrestare il container '{CONTAINER}'...")
    try:
        # Usare read_output=True può aiutare a catturare messaggi di errore specifici da Docker
        await run_docker_command(["docker", "stop", CONTAINER], read_output=True, timeout=45)
        logger.info(f"Comando 'docker stop {CONTAINER}' eseguito con successo.")
        await update.message.reply_text(f"✅ Container '{CONTAINER}' arrestato con successo.")
        return True 
    except asyncio.TimeoutError:
        logger.error(f"Timeout durante l'arresto del container {CONTAINER}.")
        await update.message.reply_text(f"⌛ Timeout: l'arresto del container '{CONTAINER}' sta richiedendo più tempo del previsto. Controlla manualmente lo stato.")
    except subprocess.CalledProcessError as e:
        error_message = html.escape(e.stderr or str(e.output) or str(e))
        logger.error(f"Errore durante l'arresto del container {CONTAINER}: {e.stderr or e.output or e}")
        await update.message.reply_text(f"❌ Errore durante l'arresto di '{CONTAINER}':\n<pre>{error_message}</pre>", parse_mode=ParseMode.HTML)
    except ValueError as e: # Per CONTAINER non configurato
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.error(f"Errore imprevisto in stop_server_command: {e}", exc_info=True)
        await update.message.reply_text(f"🆘 Errore imprevisto durante l'arresto del server: {e}")
    return False


@auth_required
async def start_server_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool: # Aggiunto tipo di ritorno
    if not CONTAINER:
        await update.message.reply_text("⚠️ Variabile CONTAINER non impostata. Impossibile avviare il server.")
        return False
    await update.message.reply_text(f"⏳ Tentativo di avviare il container '{CONTAINER}'...")
    try:
        await run_docker_command(["docker", "start", CONTAINER], read_output=True, timeout=30)
        logger.info(f"Comando 'docker start {CONTAINER}' eseguito con successo.")
        await update.message.reply_text(f"✅ Container '{CONTAINER}' avviato con successo.")
        return True 
    except asyncio.TimeoutError:
        logger.error(f"Timeout durante l'avvio del container {CONTAINER}.")
        await update.message.reply_text(f"⌛ Timeout: l'avvio del container '{CONTAINER}' sta richiedendo più tempo del previsto. Potrebbe essere già in esecuzione o avere problemi.")
    except subprocess.CalledProcessError as e:
        # Docker start restituisce errore se il container è già avviato.
        # Controlla se il messaggio di errore indica questo.
        err_str = (e.stderr or str(e.output) or str(e)).lower()
        if "is already started" in err_str or "è già avviato" in err_str :
            logger.info(f"Tentativo di avviare il container '{CONTAINER}' che è già in esecuzione.")
            await update.message.reply_text(f"ℹ️ Il container '{CONTAINER}' è già in esecuzione.")
            return True # Consideralo un successo se è già avviato
        error_message = html.escape(e.stderr or str(e.output) or str(e))
        logger.error(f"Errore durante l'avvio del container {CONTAINER}: {error_message}")
        await update.message.reply_text(f"❌ Errore durante l'avvio di '{CONTAINER}':\n<pre>{error_message}</pre>", parse_mode=ParseMode.HTML)
    except ValueError as e: # Per CONTAINER non configurato
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.error(f"Errore imprevisto in start_server_command: {e}", exc_info=True)
        await update.message.reply_text(f"🆘 Errore imprevisto durante l'avvio del server: {e}")
    return False


@auth_required
async def restart_server_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("⚠️ Variabile CONTAINER non impostata. Impossibile riavviare il server.")
        return
    await update.message.reply_text(f"⏳ Tentativo di riavviare il container '{CONTAINER}'...")
    try:
        await run_docker_command(["docker", "restart", CONTAINER], read_output=True, timeout=45) # Timeout più lungo per restart
        logger.info(f"Comando 'docker restart {CONTAINER}' eseguito con successo.")
        await update.message.reply_text(f"✅ Container '{CONTAINER}' riavviato con successo.")
    except asyncio.TimeoutError:
        logger.error(f"Timeout durante il riavvio del container {CONTAINER}.")
        await update.message.reply_text(f"⌛ Timeout: il riavvio del container '{CONTAINER}' sta richiedendo più tempo del previsto. Controlla manualmente.")
    except subprocess.CalledProcessError as e:
        error_message = html.escape(e.stderr or str(e.output) or str(e))
        logger.error(f"Errore durante il riavvio del container {CONTAINER}: {error_message}")
        await update.message.reply_text(f"❌ Errore durante il riavvio di '{CONTAINER}':\n<pre>{error_message}</pre>", parse_mode=ParseMode.HTML)
    except ValueError as e: # Per CONTAINER non configurato
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.error(f"Errore imprevisto in restart_server_command: {e}", exc_info=True)
        await update.message.reply_text(f"🆘 Errore imprevisto durante il riavvio del server: {e}")

@auth_required
async def backup_world_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONTAINER:
        await update.message.reply_text("⚠️ Variabile CONTAINER non impostata. Impossibile procedere con il backup.")
        return
    if not WORLD_NAME:
        await update.message.reply_text("⚠️ Variabile WORLD_NAME non impostata in configurazione. Impossibile identificare il mondo per il backup.")
        return

    await update.message.reply_text(f"⏳ Inizio procedura di backup per il mondo '{WORLD_NAME}'...")

    stopped_successfully = False
    await update.message.reply_text(f"🛑 Arresto del container '{CONTAINER}' in corso...")
    stopped_successfully = await stop_server_command(update, context) # Riusa la funzione di stop

    if not stopped_successfully:
        await update.message.reply_text("❌ Procedura di backup interrotta a causa di problemi con l'arresto del server.")
        # Tenta di riavviare il server se l'arresto è fallito ma era per backup
        await _restart_server_after_action(update, context, CONTAINER, "backup (errore stop)")
        return

    await update.message.reply_text("⏱ Attesa di qualche secondo per il rilascio dei file...")
    await asyncio.sleep(5) # Attesa standard

    world_to_backup_path = get_world_directory_path(WORLD_NAME) # Sincrona, veloce
    backups_storage_path = get_backups_storage_path()  # Sincrona, veloce

    if not world_to_backup_path or not os.path.exists(world_to_backup_path): # Verifica esistenza
        await update.message.reply_text(f"❌ Impossibile trovare la directory del mondo '{WORLD_NAME}' in '{world_to_backup_path}'. Backup annullato.")
        await _restart_server_after_action(update, context, CONTAINER, "backup (errore path mondo)")
        return

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Pulisci il nome del mondo per usarlo nel nome del file
    safe_world_name = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in WORLD_NAME).rstrip().replace(" ", "_")
    backup_filename_base = f"{safe_world_name}_backup_{timestamp_str}"
    # shutil.make_archive si aspetta il percorso base dell'archivio SENZA estensione
    archive_base_path_for_shutil = os.path.join(backups_storage_path, backup_filename_base)
    
    # Il nome finale dell'archivio includerà .zip
    final_archive_path_on_disk = f"{archive_base_path_for_shutil}.zip"
    backup_filename_for_message = os.path.basename(final_archive_path_on_disk)


    await update.message.reply_text(f"🗜 Creazione dell'archivio zip per '{WORLD_NAME}' in corso...")
    try:
        logger.info(f"Tentativo di archiviare '{world_to_backup_path}' in '{final_archive_path_on_disk}'")
        # shutil.make_archive è bloccante, eseguila in un thread
        await asyncio.to_thread(
            shutil.make_archive,
            base_name=archive_base_path_for_shutil, # Senza .zip qui
            format='zip',
            root_dir=os.path.dirname(world_to_backup_path), # Directory genitore del mondo
            base_dir=os.path.basename(world_to_backup_path)  # Nome della cartella del mondo
        )
        
        logger.info(f"Archivio '{final_archive_path_on_disk}' creato con successo.")
        try:
            # Imposta permessi leggibili, se necessario (dipende da umask)
            os.chmod(final_archive_path_on_disk, 0o644) 
            logger.info(f"Permessi per '{final_archive_path_on_disk}' impostati a 0o644.")
        except OSError as e_chmod:
            logger.warning(f"Attenzione: Impossibile impostare i permessi per '{final_archive_path_on_disk}': {e_chmod}")
            # Non è un errore fatale per il backup stesso

        await update.message.reply_text(
            f"✅ Backup del mondo '{WORLD_NAME}' completato e salvato come:\n"
            f"<code>{html.escape(backup_filename_for_message)}</code>\n\n"
            f"Usa il comando /list_backups per vedere tutti i backup e scaricarli.",
            parse_mode=ParseMode.HTML
        )

    except FileNotFoundError: # Può accadere se il path del mondo scompare
        logger.error(f"Errore durante la creazione dell'archivio: la directory del mondo '{world_to_backup_path}' non è stata trovata.")
        await update.message.reply_text(f"❌ Errore: la directory del mondo '{world_to_backup_path}' non esiste. Backup fallito.")
    except Exception as e:
        logger.error(f"Errore durante la fase di archiviazione del backup: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore durante la creazione del backup ZIP: {e}")
    finally: # Assicurati di riavviare il server in ogni caso dopo il tentativo di backup
        await _restart_server_after_action(update, context, CONTAINER, "backup")
    
    # Il messaggio finale di completamento procedura è implicito nel riavvio
    # await update.message.reply_text(f"ℹ️ Procedura di backup per '{WORLD_NAME}' completata.")


async def _restart_server_after_action(update: Update, context: ContextTypes.DEFAULT_TYPE, container_name: str, action_name: str):
    await update.message.reply_text(f"🚀 Riavvio del container '{container_name}' dopo {action_name}...")
    # Riusa la funzione start_server_command
    started = await start_server_command(update, context)
    if started:
        # Il messaggio di successo è già in start_server_command
        logger.info(f"Container '{container_name}' avviato con successo post-{action_name}.")
    else:
        # Il messaggio di errore è già in start_server_command
        logger.error(f"Fallimento riavvio container '{container_name}' post-{action_name}.")


@auth_required
async def list_backups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    backups_dir = get_backups_storage_path() # Sincrona, veloce
    try:
        if not os.path.exists(backups_dir):
            await update.message.reply_text(f"La directory dei backup ({backups_dir}) non è stata ancora creata. Nessun backup disponibile.")
            logger.info(f"Directory dei backup non trovata (normale se non sono stati fatti backup): {backups_dir}")
            return

        backup_files = [f for f in os.listdir(backups_dir) if f.endswith(".zip")]
    except Exception as e:
        await update.message.reply_text(f"Errore leggendo la directory dei backup: {e}")
        logger.error(f"Errore leggendo la directory dei backup {backups_dir}: {e}", exc_info=True)
        return

    if not backup_files:
        await update.message.reply_text("Nessun backup .zip trovato nella directory.")
        return

    # Ordina i file per data di modifica (i più recenti prima)
    try:
        backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(backups_dir, f)), reverse=True)
    except Exception as e_sort: # Se un file scompare durante l'ordinamento
        logger.warning(f"Errore durante l'ordinamento dei file di backup: {e_sort}. Si procede con l'elenco non ordinato.")


    buttons = []
    max_backups_to_show = 15 # Limita per evitare messaggi troppo lunghi
    for filename in backup_files[:max_backups_to_show]:
        callback_data = f"download_backup_file:{filename}"
        # La lunghezza di callback_data è limitata a 64 byte.
        if len(callback_data.encode('utf-8')) <= 64:
            buttons.append([InlineKeyboardButton(f"📥 {filename}", callback_data=callback_data)])
        else:
            logger.warning(f"Nome file '{filename}' troppo lungo per callback_data nel comando /list_backups. Impossibile creare bottone di download.")
            # Potresti aggiungere un bottone non cliccabile o un testo
            # buttons.append([InlineKeyboardButton(f"{filename} (nome troppo lungo)", callback_data="noop_filename_too_long")])

    if not buttons and backup_files: # Se ci sono file ma nessuno ha un bottone (improbabile)
        file_list_text = "\n".join([f"- <code>{html.escape(f)}</code>" for f in backup_files])
        await update.message.reply_text(
            f"Elenco dei backup disponibili (nomi file troppo lunghi per bottoni diretti):\n{file_list_text}\n\n"
            "Per scaricare, potrebbe essere necessario accedere manualmente al server.",
            parse_mode=ParseMode.HTML
        )
        return
    elif not buttons and not backup_files: # Dovrebbe essere già gestito da "Nessun backup .zip trovato"
        await update.message.reply_text("Nessun backup disponibile per il download tramite bottoni.")
        return


    reply_markup = InlineKeyboardMarkup(buttons)
    message_text = "Seleziona un backup da scaricare (i più recenti prima):"
    if len(backup_files) > max_backups_to_show:
        message_text += f"\n(Mostrati i primi {max_backups_to_show} di {len(backup_files)} backup)"
    
    await update.message.reply_text(message_text, reply_markup=reply_markup)


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
            parse_mode=ParseMode.HTML # Usa HTML per grassetto e nuova riga
        )
        return

    await update.message.reply_text(f"⏳ Inizio procedura '/imnotcreative' per il mondo '{WORLD_NAME}'...")

    stopped_successfully = False
    await update.message.reply_text(f"🛑 Arresto del container '{CONTAINER}' in corso...")
    stopped_successfully = await stop_server_command(update, context) # Riusa

    if not stopped_successfully:
        await update.message.reply_text("❌ Procedura '/imnotcreative' interrotta a causa di problemi con l'arresto del server.")
        await _restart_server_after_action(update, context, CONTAINER, "imnotcreative (errore stop)")
        return

    await update.message.reply_text("⏱ Attesa di qualche secondo per il rilascio dei file...")
    await asyncio.sleep(5)

    await update.message.reply_text(f"⚙️ Modifica di 'level.dat' per il mondo '{WORLD_NAME}' in corso...")
    # reset_creative_flag è ora asincrona
    success, message = await reset_creative_flag(WORLD_NAME) 
    if success:
        await update.message.reply_text(f"✅ {html.escape(message)}")
    else:
        await update.message.reply_text(f"⚠️ {html.escape(message)}")
    
    # Riavvia il server indipendentemente dal successo della modifica NBT, poiché è stato fermato
    await _restart_server_after_action(update, context, CONTAINER, "imnotcreative")
    # await update.message.reply_text("ℹ️ Procedura '/imnotcreative' completata.") # Messaggio già in _restart_server_after_action


# <<< NUOVO COMANDO PER RESOURCE PACK >>>
@auth_required
async def add_resourcepack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Avvia il processo di aggiunta di un nuovo resource pack."""
    # Verifica se WORLD_NAME è configurato, altrimenti non si può procedere
    if not WORLD_NAME:
        await update.message.reply_text(
            "⚠️ La variabile `WORLD_NAME` non è impostata nella configurazione del bot. "
            "Impossibile aggiungere resource pack senza specificare un mondo di destinazione."
        )
        return
        
    await update.message.reply_text(
        "Ok! Per favore, inviami ora il file del resource pack (.mcpack o .zip) "
        "oppure invia un messaggio con il link diretto per scaricarlo.\n\n"
        "Il pacchetto verrà aggiunto alla fine della lista dei pacchetti attivi "
        "(quindi avrà priorità più alta rispetto ai pacchetti esistenti)."
    )
    context.user_data["awaiting_resource_pack"] = True
    # context.user_data["awaiting_resource_pack_timestamp"] = time.time() # Per timeout opzionale
# <<< FINE NUOVO COMANDO PER RESOURCE PACK >>>
