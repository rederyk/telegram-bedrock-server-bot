# minecraft_telegram_bot/message_handlers.py
import asyncio
import subprocess
import uuid
import re
import os 
import html # Importa html se non già presente per escape
import shutil # Per shutil.rmtree
import tempfile # Per la gestione di directory temporanee
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent, Document # Aggiunto Document
)
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, get_logger, WORLD_NAME # Assicurati che WORLD_NAME sia importato
from user_management import (
    is_user_authenticated, get_minecraft_username, set_minecraft_username,
    save_location, get_user_data, get_locations, delete_location,
    users_data, save_users # Aggiunto save_users se necessario direttamente
)
from item_management import get_items
from docker_utils import run_docker_command, get_online_players_from_server
from world_management import get_backups_storage_path # Assicurati che sia importato

# Importazioni per la gestione dei Resource Pack
from resource_pack_management import (
    ResourcePackError,
    download_resource_pack_from_url,
    install_resource_pack_from_file,
    manage_world_resource_packs_json
)

from command_handlers import menu_command, give_direct_command, tp_direct_command, weather_direct_command, saveloc_command


logger = get_logger(__name__)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip() if update.message and update.message.text else "" # Gestisci messaggi vuoti

    if not is_user_authenticated(uid):
        await update.message.reply_text("Devi prima effettuare il /login.")
        return

    # Gestione inserimento username Minecraft
    if context.user_data.get("awaiting_mc_username"):
        if not text: # Ignora se l'utente invia un messaggio vuoto invece dell'username
            await update.message.reply_text("Nome utente Minecraft non valido. Riprova o invia un nome valido.")
            return
        
        set_minecraft_username(uid, text) # Questa funzione salva già gli utenti
        await update.message.reply_text(f"Username Minecraft '{text}' salvato.")
        
        next_action = context.user_data.pop("next_action_after_username", None) # Nome chiave corretto
        context.user_data.pop("awaiting_mc_username") # Rimuovi lo stato

        if next_action == "menu":
            await menu_command(update, context)
        elif next_action == "give":
            await give_direct_command(update, context)
        elif next_action == "tp":
            await tp_direct_command(update, context)
        elif next_action == "weather":
            await weather_direct_command(update, context)
        elif next_action == "saveloc":
             await saveloc_command(update,context)
        elif next_action == "post_login_greeting": # Gestisci il caso post-login
            await update.message.reply_text("Ora puoi usare i comandi che richiedono l'username (es. /menu).")
        # Altri casi specifici per next_action se necessario
        else: # Fallback se next_action non è gestito o è None
            await update.message.reply_text("Ora puoi usare i comandi che richiedono l'username (es. /menu).")
        return # Importante ritornare dopo aver gestito lo stato

    minecraft_username = get_minecraft_username(uid)
    if not minecraft_username and not context.user_data.get("awaiting_mc_username"): 
        # Se l'username non è impostato E non siamo già in attesa di esso, richiedilo.
        # Questo previene richieste multiple se l'utente invia più messaggi.
        context.user_data["awaiting_mc_username"] = True
        context.user_data["next_action_after_username"] = "general_usage" # Azione generica
        await update.message.reply_text("Per favore, inserisci prima il tuo username Minecraft:")
        return

    # Gestione modifica username
    if context.user_data.get("awaiting_username_edit"):
        if not text:
            await update.message.reply_text("Nome utente non valido. Riprova.")
            return
        # users_data è un dict globale in user_management, la modifica qui è sicura
        # ma è meglio usare una funzione se disponibile per incapsulamento.
        # Per ora, usiamo set_minecraft_username che fa la stessa cosa e salva.
        set_minecraft_username(uid, text)
        context.user_data.pop("awaiting_username_edit")
        await update.message.reply_text(f"Username aggiornato a: {text}")
        return

    # Gestione salvataggio nome posizione
    if context.user_data.get("awaiting_saveloc_name"):
        location_name = text
        if not location_name:
            await update.message.reply_text("Nome posizione non valido. Riprova.")
            return
        # Rimuovi lo stato *prima* delle operazioni asincrone per evitare race conditions
        # se l'utente invia un altro messaggio.
        context.user_data.pop("awaiting_saveloc_name") 

        if not CONTAINER:
            await update.message.reply_text("Impossibile salvare la posizione: CONTAINER non configurato.")
            return
        if not minecraft_username: # Dovrebbe essere già gestito, ma per sicurezza
            await update.message.reply_text("Username Minecraft non impostato. Impossibile salvare la posizione.")
            return

        # Comando per ottenere le coordinate (Bedrock Edition)
        # Esegue un tp relativo per forzare l'output delle coordinate nei log
        docker_cmd_get_pos = [
            "docker", "exec", CONTAINER, "send-command",
            f"execute as {minecraft_username} at @s run tp @s ~ ~ ~" 
            # Potrebbe essere necessario un piccolo offset per garantire che il comando venga registrato in modo diverso
            # f"execute as {minecraft_username} at @s run tp @s ~ ~ ~0.0001" 
        ]
        try:
            logger.info(f"Esecuzione per ottenere coordinate: {' '.join(docker_cmd_get_pos)}")
            await run_docker_command(docker_cmd_get_pos, read_output=False, timeout=10)
            await asyncio.sleep(1.0) # Attendi che i log si aggiornino

            log_args = ["docker", "logs", "--tail", "100", CONTAINER] # Aumenta tail se necessario
            output = await run_docker_command(log_args, read_output=True, timeout=5)

            # Pattern per Bedrock: "Teleported <username> to <x>, <y>, <z>"
            # Il pattern deve essere robusto a spazi variabili e possibili caratteri speciali nell'username
            pattern_bedrock = rf"Teleported {re.escape(minecraft_username)} to ([0-9\.\-]+),\s*([0-9\.\-]+),\s*([0-9\.\-]+)"
            matches = re.findall(pattern_bedrock, output)
            
            if not matches: # Fallback per un formato leggermente diverso o log meno verbosi
                pattern_bedrock_simple = rf"{re.escape(minecraft_username)} to ([0-9\.\-]+), ([0-9\.\-]+), ([0-9\.\-]+)"
                matches = re.findall(pattern_bedrock_simple, output)


            if not matches:
                logger.warning(f"Nessuna coordinata trovata nei log per {minecraft_username} dopo /saveloc.")
                logger.debug(f"Output log per saveloc: {output[-500:]}") # Logga l'ultima parte dell'output
                await update.message.reply_text(
                    "Impossibile trovare le coordinate nei log. Assicurati di essere in gioco, "
                    "che i comandi siano abilitati e che l'output del comando 'tp' sia visibile nei log. "
                    "Potrebbe essere necessario che il server abbia `gamerule sendcommandfeedback true`."
                )
                return

            x_str, y_str, z_str = matches[-1] # Prendi l'ultima corrispondenza
            coords = {"x": float(x_str), "y": float(y_str), "z": float(z_str)}

            save_location(uid, location_name, coords) # Sincrona, veloce
            await update.message.reply_text(
                f"✅ Posizione '{html.escape(location_name)}' salvata: X={coords['x']:.2f}, Y={coords['y']:.2f}, Z={coords['z']:.2f}"
            )
        except asyncio.TimeoutError:
            await update.message.reply_text("Timeout durante il salvataggio della posizione. Riprova.")
        except subprocess.CalledProcessError as e:
            err_msg = html.escape(e.stderr or e.output or str(e))
            await update.message.reply_text(
                f"Errore del server Minecraft durante il salvataggio: <pre>{err_msg}</pre> "
                "Potrebbe essere necessario abilitare i comandi o verificare l'username.",
                parse_mode=ParseMode.HTML
            )
        except ValueError as e: # Per conversioni float fallite o CONTAINER non configurato
             await update.message.reply_text(html.escape(str(e)))
        except Exception as e:
            logger.error(f"Errore in /saveloc (esecuzione comando): {e}", exc_info=True)
            await update.message.reply_text(f"Si è verificato un errore salvando la posizione: {html.escape(str(e))}")
        return

    # Gestione prefisso item per /give
    if context.user_data.get("awaiting_give_prefix"):
        prefix = text.lower()
        context.user_data.pop("awaiting_give_prefix") # Rimuovi stato

        all_items = get_items() # Sincrona, veloce
        matches = [
            i for i in all_items
            if prefix in i["id"].lower() or prefix in i["name"].lower() 
        ]
        if not matches:
            await update.message.reply_text("Nessun item trovato con quel nome/ID. Riprova o usa /menu.")
        else:
            buttons = [
                InlineKeyboardButton(
                    f'{i["name"]} ({i["id"]})', callback_data=f'give_item_select:{i["id"]}'
                ) for i in matches[:20] # Limita il numero di bottoni
            ]
            # Layout a colonna singola per leggibilità
            keyboard = [[button] for button in buttons] 
            await update.message.reply_text(
                f"Ho trovato {len(matches)} item (mostro i primi {len(buttons)}). Scegli un item:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        return

    # Gestione quantità item
    if context.user_data.get("awaiting_item_quantity"):
        # Rimuovi stato prima, specialmente prima di operazioni che possono fallire
        item_id = context.user_data.pop("selected_item_for_give", None)
        context.user_data.pop("awaiting_item_quantity", None)

        if not CONTAINER:
            await update.message.reply_text("Errore: CONTAINER non configurato per il comando give.")
            return
        if not minecraft_username:
            await update.message.reply_text("Errore: Username Minecraft non impostato per il comando give.")
            return
        if not item_id:
            await update.message.reply_text(
                "Errore interno: item non selezionato. Riprova da /menu o /give."
            )
            return
            
        try:
            quantity = int(text)
            if quantity <= 0:
                raise ValueError("La quantità deve essere un numero intero positivo.")

            cmd_text = f"give {minecraft_username} {item_id} {quantity}"
            docker_cmd_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False) # read_output=False è ok per give
            await update.message.reply_text(f"Comando eseguito: /give {minecraft_username} {item_id} {quantity}")

        except ValueError as e:
            # if "La quantità deve essere positiva" in str(e):
            #      await update.message.reply_text("Inserisci un numero valido (intero, maggiore di zero) per la quantità.")
            # else: 
            await update.message.reply_text(f"Quantità non valida: {html.escape(str(e))}. Inserisci un numero intero positivo.")
        except asyncio.TimeoutError:
            await update.message.reply_text("Timeout eseguendo il comando give.")
        except subprocess.CalledProcessError as e:
            err_msg = html.escape(e.stderr or e.output or str(e))
            await update.message.reply_text(f"Errore dal server Minecraft: <pre>{err_msg}</pre>", parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Errore imprevisto in handle_message (give quantity): {e}", exc_info=True)
            await update.message.reply_text(f"Errore imprevisto: {html.escape(str(e))}")
        return

    # Gestione coordinate TP
    if context.user_data.get("awaiting_tp_coords_input"):
        context.user_data.pop("awaiting_tp_coords_input", None) # Rimuovi stato

        if not CONTAINER:
            await update.message.reply_text("Errore: CONTAINER non configurato per il comando teleport.")
            return
        if not minecraft_username:
            await update.message.reply_text("Errore: Username Minecraft non impostato per il comando teleport.")
            return

        parts = text.split()
        if len(parts) != 3:
            await update.message.reply_text(
                "Formato coordinate non valido. Usa: `x y z` (es. `100 64 -200`). Riprova o usa /menu, /tp."
            )
        else:
            try:
                # Tilde expansion for relative coordinates (e.g. ~10 ~ ~-5)
                # This is complex for Bedrock as `send-command` might not directly support it
                # in the same way as in-game commands. For now, assume absolute.
                # If relative coords are needed, the `execute as ... run tp ...` structure is better.
                x_str, y_str, z_str = parts
                # Non è necessario convertire in float qui se il server li accetta come stringhe
                # x, y, z = map(float, parts) 
                cmd_text = f"tp {minecraft_username} {x_str} {y_str} {z_str}"
                docker_cmd_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
                await run_docker_command(docker_cmd_args, read_output=False)
                await update.message.reply_text(f"Comando eseguito: /tp {minecraft_username} {x_str} {y_str} {z_str}")
            except ValueError: # Se si usasse map(float, ...) e fallisse
                await update.message.reply_text(
                    "Le coordinate devono essere numeri validi (es. `100 64.5 -200`). Riprova o usa /menu, /tp."
                )
            except asyncio.TimeoutError:
                await update.message.reply_text("Timeout eseguendo il comando teleport.")
            except subprocess.CalledProcessError as e:
                err_msg = html.escape(e.stderr or e.output or str(e))
                await update.message.reply_text(f"Errore dal server Minecraft: <pre>{err_msg}</pre>", parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"Errore imprevisto in handle_message (tp coords): {e}", exc_info=True)
                await update.message.reply_text(f"Errore imprevisto: {html.escape(str(e))}")
        return
        
    # <<< INIZIO GESTIONE RESOURCE PACK DA TESTO (URL) >>>
    if context.user_data.get("awaiting_resource_pack"):
        # Rimuovi lo stato *prima* di operazioni potenzialmente lunghe o fallibili
        # per evitare che messaggi successivi vengano interpretati erroneamente.
        # Lo stato verrà ripristinato dal comando /addresourcepack se l'utente vuole riprovare.
        context.user_data.pop("awaiting_resource_pack", None) 
        
        if not text: # Ignora messaggi vuoti
            return
        
        if not WORLD_NAME: # Controllo critico
            await update.message.reply_text("⚠️ Errore: `WORLD_NAME` non configurato. Impossibile installare resource pack.")
            return

        if text.startswith("http://") or text.startswith("https://"):
            await update.message.reply_text(f"Ricevuto URL: {text}\nTentativo di download e installazione in corso...")
            temp_dir = tempfile.mkdtemp() # Crea una directory temporanea
            downloaded_file_path_local = None # Percorso del file scaricato
            try:
                # download_resource_pack_from_url è ora asincrona
                downloaded_file_path_local = await download_resource_pack_from_url(text, temp_dir)
                original_filename = os.path.basename(downloaded_file_path_local)

                # install_resource_pack_from_file e manage_world_resource_packs_json sono sincrone
                _, pack_uuid, pack_version, pack_name = await asyncio.to_thread(
                    install_resource_pack_from_file, downloaded_file_path_local, original_filename
                )
                
                await asyncio.to_thread(
                    manage_world_resource_packs_json, 
                    WORLD_NAME, 
                    pack_uuid_to_add=pack_uuid, 
                    pack_version_to_add=pack_version
                    # add_to_top=False (default) aggiunge in fondo, priorità più alta
                )
                await update.message.reply_text(
                    f"✅ Resource pack '{html.escape(pack_name)}' (UUID: {pack_uuid}) installato e attivato per il mondo '{WORLD_NAME}'!\n"
                    "I giocatori potrebbero aver bisogno di riconnettersi per vedere le modifiche."
                )
            except ResourcePackError as rpe:
                logger.error(f"Errore resource pack (URL {text}): {rpe}")
                await update.message.reply_text(f"⚠️ Errore: {html.escape(str(rpe))}")
            except Exception as e:
                logger.error(f"Errore imprevisto processando resource pack (URL {text}): {e}", exc_info=True)
                await update.message.reply_text(f"🆘 Si è verificato un errore imprevisto: {html.escape(str(e))}")
            finally:
                # Pulisci la directory temporanea e il suo contenuto
                if os.path.exists(temp_dir):
                    try:
                        shutil.rmtree(temp_dir)
                        logger.info(f"Directory temporanea {temp_dir} rimossa.")
                    except Exception as e_clean:
                        logger.error(f"Errore durante la pulizia della directory temporanea {temp_dir}: {e_clean}")
            return # Fine gestione URL resource pack
        else:
            await update.message.reply_text(
                "Questo non sembra un URL valido. Se volevi inviare un file, allegalo direttamente. "
                "Per riprovare ad aggiungere un resource pack, usa di nuovo il comando /addresourcepack."
            )
        return # Fine gestione stato awaiting_resource_pack
    # <<< FINE GESTIONE RESOURCE PACK DA TESTO (URL) >>>

    # Se nessun altro stato ha gestito il messaggio e non è un comando
    if not text.startswith('/'):
        await update.message.reply_text(
            "Comando testuale non riconosciuto o stato non attivo. "
            "Usa /menu per vedere le opzioni o /help per la lista comandi."
        )


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    results = []
    if query: 
        all_items = get_items() # Sincrona, veloce
        if not all_items: 
            logger.warning("Inline query: lista ITEMS vuota o non disponibile.")
        else:
            matches = [
                i for i in all_items
                if query in i["id"].lower() or query in i["name"].lower()
            ]
            # Costruisci il messaggio di input per includere l'username del giocatore
            # Questo richiede che l'utente sostituisca {MINECRAFT_USERNAME}
            # o che il bot lo faccia se l'username è noto.
            # Per semplicità, lasciamo un placeholder.
            results = [
                InlineQueryResultArticle(
                    id=str(uuid.uuid4()), 
                    title=i["name"],
                    description=f'ID: {i["id"]}',
                    input_message_content=InputTextMessageContent(
                        # f'/give {{MINECRAFT_USERNAME}} {i["id"]} 1' # Placeholder per l'utente
                        # Oppure, se si potesse ottenere l'username qui (difficile in inline mode)
                        # f'/cmd give {get_minecraft_username(update.inline_query.from_user.id) or "{PLAYER}"} {i["id"]} 1'
                        f'Dai: {i["name"]} (ID: {i["id"]})' # Messaggio più generico
                    )
                ) for i in matches[:20] # Limita risultati
            ]
    await update.inline_query.answer(results, cache_time=10)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Rispondi subito al callback

    uid = query.from_user.id
    data = query.data

    if not is_user_authenticated(uid):
        await query.edit_message_text("Errore: non sei autenticato. Usa /login.")
        return

    minecraft_username = get_minecraft_username(uid) # Sincrona, veloce
    
    # Azioni che non richiedono username Minecraft o container
    if data == "edit_username":
        context.user_data["awaiting_username_edit"] = True
        await query.edit_message_text("Ok, inserisci il nuovo username Minecraft:")
        return
    elif data == "delete_location":
        user_locs = get_locations(uid)
        if not user_locs:
            await query.edit_message_text("Non hai posizioni salvate.")
            return
        buttons = [
            [InlineKeyboardButton(f"❌ {name}", callback_data=f"delete_loc:{name}")]
            for name in user_locs
        ]
        await query.edit_message_text(
            "Seleziona la posizione da cancellare:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return
    elif data.startswith("delete_loc:"):
        name_to_delete = data.split(":", 1)[1]
        if delete_location(uid, name_to_delete): # Sincrona, veloce
            await query.edit_message_text(f"Posizione «{html.escape(name_to_delete)}» cancellata 🔥")
        else:
            await query.edit_message_text(f"Posizione «{html.escape(name_to_delete)}» non trovata.")
        return
    elif data.startswith("download_backup_file:"):
        # Questa azione non richiede username Minecraft né CONTAINER
        backup_filename_from_callback = data.split(":", 1)[1]
        backups_dir = get_backups_storage_path() 
        backup_file_path = os.path.join(backups_dir, backup_filename_from_callback)
        logger.info(f"Tentativo di scaricare il file di backup da: {backup_file_path}")

        if os.path.exists(backup_file_path):
            try:
                original_message_text = query.message.text # Salva testo originale
                await query.edit_message_text(
                    f"{original_message_text}\n\n⏳ Preparazione invio di '{html.escape(backup_filename_from_callback)}'..."
                )
                
                with open(backup_file_path, "rb") as backup_file:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=backup_file,
                        filename=os.path.basename(backup_file_path), 
                        caption=f"Backup del mondo: {html.escape(os.path.basename(backup_file_path))}"
                    )
                # Ripristina il messaggio originale o invia conferma
                await query.message.reply_text(f"✅ File '{html.escape(backup_filename_from_callback)}' inviato!")
                # Potresti voler rieditare il messaggio originale per rimuovere "Preparazione invio..."
                # await query.edit_message_text(original_message_text) # Opzionale
            except Exception as e:
                logger.error(f"Errore inviando il file di backup '{backup_file_path}': {e}", exc_info=True)
                await query.message.reply_text(f"⚠️ Impossibile inviare il file '{html.escape(backup_filename_from_callback)}': {html.escape(str(e))}")
        else:
            logger.warning(f"File di backup non trovato per il download: {backup_file_path}")
            await query.edit_message_text(f"⚠️ File di backup non trovato: <code>{html.escape(backup_filename_from_callback)}</code>. Potrebbe essere stato spostato o cancellato.", parse_mode=ParseMode.HTML)
        return # Fine gestione download backup

    # Da qui in poi, la maggior parte delle azioni richiede username e/o CONTAINER
    if not minecraft_username:
        context.user_data["awaiting_mc_username"] = True
        # Salva l'azione richiesta per eseguirla dopo l'inserimento dell'username
        context.user_data["next_action_after_username"] = f"callback:{data}" 
        await query.edit_message_text(
            "Il tuo username Minecraft non è impostato. Per favore, invialo in chat."
        )
        return

    # Verifica CONTAINER per azioni che lo richiedono
    actions_requiring_container = [
        "give_item_select:", "tp_player:", "tp_coords_input", "weather_set:",
        "tp_saved:", "menu_give", "menu_tp", "menu_weather"
    ]
    is_action_requiring_container = any(data.startswith(action_prefix) for action_prefix in actions_requiring_container)
    
    if not CONTAINER and is_action_requiring_container:
        await query.edit_message_text(
            "Errore: La variabile CONTAINER non è impostata nel bot. "
            "Impossibile eseguire questa azione."
        )
        return

    # Gestione delle azioni specifiche
    try:
        if data == "menu_give": 
            context.user_data["awaiting_give_prefix"] = True
            await query.edit_message_text(
                "Ok, inviami il nome (o parte del nome/ID) dell'oggetto che vuoi dare:"
            )

        elif data.startswith("give_item_select:"): 
            item_id = data.split(":", 1)[1]
            context.user_data["selected_item_for_give"] = item_id
            context.user_data["awaiting_item_quantity"] = True
            await query.edit_message_text(f"Item selezionato: {item_id}.\nInserisci la quantità desiderata:")

        elif data == "menu_tp": 
            online_players = await get_online_players_from_server()
            buttons = []
            if online_players: 
                buttons.extend([
                    InlineKeyboardButton(p, callback_data=f"tp_player:{p}")
                    for p in online_players
                ])
            buttons.append(InlineKeyboardButton("📍 Inserisci coordinate", callback_data="tp_coords_input"))
            user_locs = get_locations(uid)
            for name in user_locs:
                buttons.append(InlineKeyboardButton(f"📌 {name}", callback_data=f"tp_saved:{name}"))

            if not buttons: 
                 await query.edit_message_text(
                    "Nessun giocatore online e nessuna posizione salvata. "
                    "Non ci sono destinazioni rapide disponibili.",
                 )
                 return

            keyboard_layout = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
            markup = InlineKeyboardMarkup(keyboard_layout)
            text_reply = "Scegli una destinazione:"
            if not online_players and not CONTAINER : # CONTAINER check è in get_online_players
                 text_reply = ("Impossibile ottenere lista giocatori.\n"
                               "Scegli tra posizioni salvate o coordinate.")
            elif not online_players:
                 text_reply = "Nessun giocatore online.\nScegli tra posizioni salvate o coordinate:"
            await query.edit_message_text(text_reply, reply_markup=markup)


        elif data.startswith("tp_saved:"):
            location_name = data.split(":", 1)[1]
            user_locs = get_locations(uid)
            loc_coords = user_locs.get(location_name)
            if not loc_coords:
                await query.edit_message_text(f"Posizione '{html.escape(location_name)}' non trovata.")
                return
            x, y, z = loc_coords["x"], loc_coords["y"], loc_coords["z"]
            cmd_text = f"tp {minecraft_username} {x} {y} {z}"
            docker_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_args, read_output=False)
            await query.edit_message_text(f"Teleport eseguito su '{html.escape(location_name)}': {x:.2f}, {y:.2f}, {z:.2f}")

        elif data == "tp_coords_input": 
            context.user_data["awaiting_tp_coords_input"] = True
            await query.edit_message_text("Inserisci le coordinate nel formato: `x y z` (es. `100 64 -200`)")

        elif data.startswith("tp_player:"):
            target_player = data.split(":", 1)[1]
            cmd_text = f"tp {minecraft_username} {target_player}"
            docker_cmd_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await query.edit_message_text(f"Teleport verso {html.escape(target_player)} eseguito!")

        elif data == "menu_weather": 
            buttons = [
                [InlineKeyboardButton("☀️ Sereno (Clear)", callback_data="weather_set:clear")],
                [InlineKeyboardButton("🌧 Pioggia (Rain)", callback_data="weather_set:rain")],
                [InlineKeyboardButton("⛈ Temporale (Thunder)", callback_data="weather_set:thunder")]
            ]
            await query.edit_message_text(
                "Scegli le condizioni meteo:", reply_markup=InlineKeyboardMarkup(buttons)
            )

        elif data.startswith("weather_set:"):
            weather_condition = data.split(":", 1)[1]
            cmd_text = f"weather {weather_condition}"
            docker_cmd_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await query.edit_message_text(f"Meteo impostato su: {weather_condition.capitalize()}")
        
        else: # Fallback per callback non riconosciuti
            await query.edit_message_text("Azione non riconosciuta o scaduta.")

    except asyncio.TimeoutError:
        await query.edit_message_text("Timeout eseguendo l'azione richiesta. Riprova.")
    except subprocess.CalledProcessError as e:
        error_detail = html.escape(e.stderr or e.output or str(e))
        await query.edit_message_text(f"Errore dal server Minecraft: <pre>{error_detail}</pre>. Riprova o contatta un admin.", parse_mode=ParseMode.HTML)
        logger.error(f"CalledProcessError in callback_query_handler for data '{data}': {error_detail}")
    except ValueError as e: # Per CONTAINER non configurato o altri errori di valore
        await query.edit_message_text(html.escape(str(e)))
    except Exception as e:
        logger.error(f"Errore imprevisto in callback_query_handler for data '{data}': {e}", exc_info=True)
        await query.edit_message_text(f"Si è verificato un errore imprevisto: {html.escape(str(e))}. Riprova più tardi.")


# <<< NUOVO HANDLER PER DOCUMENTI (RESOURCE PACK) >>>
async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_user_authenticated(uid):
        logger.warning(f"Documento ricevuto da utente non autenticato {uid}")
        # Non inviare messaggi a utenti non autenticati per non dare feedback indesiderato
        return

    if context.user_data.get("awaiting_resource_pack"):
        # Rimuovi lo stato *prima* per evitare elaborazioni multiple
        context.user_data.pop("awaiting_resource_pack", None)
        
        doc = update.message.document
        if not doc.file_name:
            await update.message.reply_text("⚠️ Il file inviato non ha un nome. Impossibile processarlo.")
            return

        if not (doc.file_name.lower().endswith(".zip") or doc.file_name.lower().endswith(".mcpack")):
            await update.message.reply_text(f"⚠️ Formato file '{html.escape(doc.file_name)}' non supportato. Invia un file .zip o .mcpack.")
            return
        
        if not WORLD_NAME: # Controllo critico
            await update.message.reply_text("⚠️ Errore: `WORLD_NAME` non configurato. Impossibile installare resource pack.")
            return
            
        await update.message.reply_text(f"Ricevuto file: {html.escape(doc.file_name)}\nTentativo di download e installazione in corso...")
        
        temp_dir = tempfile.mkdtemp() # Crea directory temporanea
        # Costruisci un percorso univoco per il file scaricato nella directory temporanea
        # per evitare conflitti se il nome del file da Telegram non è unico o contiene caratteri problematici.
        # Usiamo l'UUID del file di Telegram se disponibile, altrimenti un UUID casuale.
        telegram_file_unique_id = doc.file_unique_id or str(uuid.uuid4())
        # Mantieni l'estensione originale per chiarezza, ma il nome base è univoco.
        _, ext = os.path.splitext(doc.file_name)
        local_temp_filename = f"telegram_dl_{telegram_file_unique_id}{ext if ext else '.tmp'}"
        downloaded_telegram_file_path = os.path.join(temp_dir, local_temp_filename)
        
        try:
            file_on_telegram = await context.bot.get_file(doc.file_id)
            await file_on_telegram.download_to_drive(custom_path=downloaded_telegram_file_path)
            logger.info(f"File Telegram '{doc.file_name}' (ID: {doc.file_id}) scaricato in '{downloaded_telegram_file_path}'")

            # install_resource_pack_from_file e manage_world_resource_packs_json sono sincrone
            _, pack_uuid, pack_version, pack_name = await asyncio.to_thread(
                install_resource_pack_from_file, downloaded_telegram_file_path, doc.file_name # Usa nome originale per logica estensione
            )
            
            await asyncio.to_thread(
                manage_world_resource_packs_json,
                WORLD_NAME,
                pack_uuid_to_add=pack_uuid,
                pack_version_to_add=pack_version
            )
            await update.message.reply_text(
                f"✅ Resource pack '{html.escape(pack_name)}' (UUID: {pack_uuid}) installato e attivato per il mondo '{WORLD_NAME}'!\n"
                "I giocatori potrebbero aver bisogno di riconnettersi per vedere le modifiche."
            )
        except ResourcePackError as rpe:
            logger.error(f"Errore resource pack (file {doc.file_name}): {rpe}")
            await update.message.reply_text(f"⚠️ Errore: {html.escape(str(rpe))}")
        except Exception as e:
            logger.error(f"Errore imprevisto processando resource pack (file {doc.file_name}): {e}", exc_info=True)
            await update.message.reply_text(f"🆘 Si è verificato un errore imprevisto: {html.escape(str(e))}")
        finally:
            # Pulisci la directory temporanea e il suo contenuto
            if os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.info(f"Directory temporanea {temp_dir} rimossa.")
                except Exception as e_clean:
                     logger.error(f"Errore durante la pulizia della directory temporanea {temp_dir}: {e_clean}")
        return # Fine gestione documento resource pack
    else:
        # Se non siamo in attesa di un resource pack, potresti informare l'utente o ignorare.
        logger.info(f"Documento '{doc.file_name if update.message and update.message.document else 'N/D'}' ricevuto ma non in attesa di un resource pack.")
        # await update.message.reply_text("Non stavo aspettando un file. Se vuoi aggiungere un resource pack, usa prima /addresourcepack.")
# <<< FINE NUOVO HANDLER PER DOCUMENTI >>>
