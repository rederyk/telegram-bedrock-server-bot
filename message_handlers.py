# minecraft_telegram_bot/message_handlers.py
import asyncio
import subprocess
import uuid
import re
import os
import html # Importa html se non già presente per escape
import tempfile
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent
)
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, get_logger, WORLD_NAME
from user_management import (
    is_user_authenticated, get_minecraft_username, set_minecraft_username,
    save_location, get_user_data, get_locations, delete_location,
    users_data
)
from item_management import get_items
from docker_utils import run_docker_command, get_online_players_from_server
from world_management import get_backups_storage_path # Assicurati che sia importato
from command_handlers import menu_command, give_direct_command, tp_direct_command, weather_direct_command, saveloc_command
from resource_pack_management import install_resource_pack_from_file, manage_world_resource_packs_json, ResourcePackError


logger = get_logger(__name__)

# ... (codice esistente per handle_text_message e inline_query_handler)
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if not is_user_authenticated(uid):
        await update.message.reply_text("Devi prima effettuare il /login.")
        return

    # Gestione inserimento username Minecraft
    if context.user_data.get("awaiting_mc_username"):
        if not text:
            await update.message.reply_text("Nome utente Minecraft non valido. Riprova.")
            return
        set_minecraft_username(uid, text)
        context.user_data.pop("awaiting_mc_username")
        await update.message.reply_text(f"Username Minecraft '{text}' salvato.")

        next_action = context.user_data.pop("next_action", None)
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
        else:
            await update.message.reply_text("Ora puoi usare i comandi che richiedono l'username (es. /menu).")
        return

    minecraft_username = get_minecraft_username(uid)
    if not minecraft_username:
        context.user_data["awaiting_mc_username"] = True
        await update.message.reply_text("Per favore, inserisci prima il tuo username Minecraft:")
        return

    # Gestione modifica username
    if context.user_data.get("awaiting_username_edit"):
        if not text:
            await update.message.reply_text("Nome utente non valido. Riprova.")
            return
        users_data[uid]["minecraft_username"] = text
        from user_management import save_users
        save_users()
        context.user_data.pop("awaiting_username_edit")
        await update.message.reply_text(f"Username aggiornato a: {text}")
        return

    # Gestione salvataggio nome posizione
    if context.user_data.get("awaiting_saveloc_name"):
        location_name = text
        if not location_name:
            await update.message.reply_text("Nome posizione non valido. Riprova.")
            return
        context.user_data.pop("awaiting_saveloc_name")

        if not CONTAINER:
            await update.message.reply_text("Impossibile salvare la posizione: CONTAINER non configurato.")
            return
        docker_cmd_get_pos = [
            "docker", "exec", CONTAINER, "send-command",
            f"execute as {minecraft_username} at @s run tp @s ~ ~ ~0.0001"
        ]
        try:
            logger.info(f"Esecuzione per ottenere coordinate: {' '.join(docker_cmd_get_pos)}")
            await run_docker_command(docker_cmd_get_pos, read_output=False, timeout=10)
            await asyncio.sleep(1.0)

            log_args = ["docker", "logs", "--tail", "100", CONTAINER]
            output = await run_docker_command(log_args, read_output=True, timeout=5)

            pattern = rf"Teleported {re.escape(minecraft_username)} to ([0-9\.\-]+),\s*([0-9\.\-]+),\s*([0-9\.\-]+)"
            matches = re.findall(pattern, output)
            if not matches:
                pattern_bedrock = rf"Teleported {re.escape(minecraft_username)} to ([0-9\.\-]+), ([0-9\.\-]+), ([0-9\.\-]+)"
                matches = re.findall(pattern_bedrock, output)

            if not matches:
                logger.warning(f"Nessuna coordinata trovata nei log per {minecraft_username} dopo /saveloc.")
                logger.debug(f"Output log per saveloc: {output}")
                await update.message.reply_text(
                    "Impossibile trovare le coordinate nei log. Assicurati di essere in gioco, che i comandi siano abilitati e che l'output del comando 'tp' sia visibile nei log. Riprova più tardi."
                )
                return

            x_str, y_str, z_str = matches[-1]
            coords = {"x": float(x_str), "y": float(y_str), "z": float(z_str)}

            save_location(uid, location_name, coords)
            await update.message.reply_text(
                f"✅ Posizione '{location_name}' salvata: X={coords['x']:.2f}, Y={coords['y']:.2f}, Z={coords['z']:.2f}"
            )
        except asyncio.TimeoutError:
            await update.message.reply_text("Timeout durante il salvataggio della posizione. Riprova.")
        except subprocess.CalledProcessError as e:
            await update.message.reply_text(
                f"Errore del server Minecraft durante il salvataggio: {e.stderr or e.output or e}. "
                "Potrebbe essere necessario abilitare i comandi o verificare l'username."
            )
        except ValueError as e:
             await update.message.reply_text(str(e))
        except Exception as e:
            logger.error(f"Errore in /saveloc (esecuzione comando): {e}", exc_info=True)
            await update.message.reply_text("Si è verificato un errore salvando la posizione.")
        return

    # Gestione prefisso item per /give
    if context.user_data.get("awaiting_give_prefix"):
        prefix = text.lower()
        all_items = get_items()
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
                ) for i in matches[:20]
            ]
            keyboard = [buttons[j:j+1] for j in range(len(buttons))]
            await update.message.reply_text(
                f"Ho trovato {len(matches)} item (mostro i primi {len(buttons)}). Scegli un item:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        context.user_data.pop("awaiting_give_prefix")
        return

    # Gestione quantità item
    if context.user_data.get("awaiting_item_quantity"):
        if not CONTAINER:
            await update.message.reply_text("Errore: CONTAINER non configurato per il comando give.")
            context.user_data.pop("awaiting_item_quantity", None)
            context.user_data.pop("selected_item_for_give", None)
            return

        try:
            quantity = int(text)
            if quantity <= 0:
                raise ValueError("La quantità deve essere positiva.")

            item_id = context.user_data.get("selected_item_for_give")
            if not item_id:
                await update.message.reply_text(
                    "Errore interno: item non selezionato. Riprova da /menu o /give."
                )
                context.user_data.pop("awaiting_item_quantity", None)
                return

            cmd_text = f"give {minecraft_username} {item_id} {quantity}"
            docker_cmd_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await update.message.reply_text(f"Comando eseguito: /give {minecraft_username} {item_id} {quantity}")

        except ValueError as e:
            if "La quantità deve essere positiva" in str(e):
                 await update.message.reply_text("Inserisci un numero valido (intero, maggiore di zero) per la quantità.")
            else:
                 await update.message.reply_text(str(e))
        except asyncio.TimeoutError:
            await update.message.reply_text("Timeout eseguendo il comando give.")
        except subprocess.CalledProcessError as e:
            await update.message.reply_text(f"Errore dal server Minecraft: {e.stderr or e.output or e}")
        except Exception as e:
            logger.error(f"Errore imprevisto in handle_message (give quantity): {e}", exc_info=True)
            await update.message.reply_text(f"Errore imprevisto: {e}")
        finally:
            context.user_data.pop("selected_item_for_give", None)
            context.user_data.pop("awaiting_item_quantity", None)
        return

    # Gestione nuova posizione resource pack
    if context.user_data.get("awaiting_rp_new_position"):
        pack_uuid_to_move = context.user_data.pop("awaiting_rp_new_position", None)
        if not pack_uuid_to_move:
            await update.message.reply_text("Errore interno: UUID del resource pack da spostare non trovato.")
            return

        try:
            new_position = int(text)
            if new_position <= 0:
                raise ValueError("La posizione deve essere un numero positivo.")

            # Adjust for 0-based index
            new_index = new_position - 1

            manage_world_resource_packs_json(
                WORLD_NAME,
                pack_uuid_to_move=pack_uuid_to_move,
                new_index_for_move=new_index
            )

            # Log & suggerimento riavvio
            logger.info(
                f"Resource pack {pack_uuid_to_move} spostato alla posizione {new_position}; "
                "ricordati di /restartserver per applicare le modifiche"
            )
            await update.message.reply_text(
                f"✅ Resource pack (<code>{pack_uuid_to_move[:8]}...</code>) spostato alla posizione {new_position}.\n"
                "ℹ️ Per applicare le modifiche, esegui il comando: /restartserver",
                parse_mode=ParseMode.HTML
            )

        except ValueError:
            await update.message.reply_text("Inserisci un numero valido per la posizione.")
            context.user_data["awaiting_rp_new_position"] = pack_uuid_to_move  # Restore if input is invalid
        except ResourcePackError as e:
            logger.error(f"📦❌ Errore spostamento RP {pack_uuid_to_move}: {e}")
            await update.message.reply_text(f"❌ Errore spostamento resource pack: {html.escape(str(e))}")
        except Exception as e:
            logger.error(f"🆘 Errore imprevisto spostamento RP {pack_uuid_to_move}: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Errore imprevisto durante lo spostamento: {html.escape(str(e))}")
        return

    # Gestione coordinate TP
    if context.user_data.get("awaiting_tp_coords_input"):
        if not CONTAINER:
            await update.message.reply_text("Errore: CONTAINER non configurato per il comando teleport.")
            context.user_data.pop("awaiting_tp_coords_input", None)
            return

        parts = text.split()
        if len(parts) != 3:
            await update.message.reply_text(
                "Formato coordinate non valido. Usa: x y z (es. 100 64 -200). Riprova o /menu, /tp."
            )
        else:
            try:
                x, y, z = map(float, parts)
                cmd_text = f"tp {minecraft_username} {x} {y} {z}"
                docker_cmd_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
                await run_docker_command(docker_cmd_args, read_output=False)
                await update.message.reply_text(f"Comando eseguito: /tp {minecraft_username} {x} {y} {z}")
            except ValueError as e:
                if "could not convert string to float" in str(e).lower() or "invalid literal for int" in str(e).lower():
                    await update.message.reply_text(
                        "Le coordinate devono essere numeri validi (es. 100 64.5 -200). Riprova o /menu, /tp."
                    )
                else:
                    await update.message.reply_text(str(e))
            except asyncio.TimeoutError:
                await update.message.reply_text("Timeout eseguendo il comando teleport.")
            except subprocess.CalledProcessError as e:
                await update.message.reply_text(f"Errore dal server Minecraft: {e.stderr or e.output or e}")
            except Exception as e:
                logger.error(f"Errore imprevisto in handle_message (tp coords): {e}", exc_info=True)
                await update.message.reply_text(f"Errore imprevisto: {e}")
            finally:
                context.user_data.pop("awaiting_tp_coords_input", None)
        return
    if not text.startswith('/'):
        await update.message.reply_text(
            "Comando testuale non riconosciuto o stato non attivo. "
            "Usa /menu per vedere le opzioni o /help per la lista comandi."
        )

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    results = []
    if query:
        all_items = get_items()
        if not all_items:
            logger.warning("Inline query: lista ITEMS vuota o non disponibile.")
        else:
            matches = [
                i for i in all_items
                if query in i["id"].lower() or query in i["name"].lower()
            ]
            results = [
                InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    title=i["name"],
                    description=f'ID: {i["id"]}',
                    input_message_content=InputTextMessageContent(
                        f'/give {{MINECRAFT_USERNAME}} {i["id"]} 1'
                    )
                ) for i in matches[:20]
            ]
    await update.inline_query.answer(results, cache_time=10)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    data = query.data

    if not is_user_authenticated(uid):
        await query.edit_message_text("Errore: non sei autenticato. Usa /login.")
        return

    minecraft_username = get_minecraft_username(uid)
    # Modifica: download_backup_file non richiede username Minecraft, quindi la condizione cambia
    if not minecraft_username and \
       not data.startswith("edit_username") and \
       not data.startswith("download_backup_file:"): # <<< MODIFICATO PREFISSO
        context.user_data["awaiting_mc_username"] = True
        await query.edit_message_text(
            "Il tuo username Minecraft non è impostato. Per favore, invialo in chat."
        )
        return

    actions_requiring_container = [
        "give_item_select:", "tp_player:", "tp_coords_input", "weather_set:",
        "tp_saved:", "menu_give", "menu_tp", "menu_weather"
    ]
    is_action_requiring_container = any(data.startswith(action_prefix) for action_prefix in actions_requiring_container)

    if not CONTAINER and is_action_requiring_container:
        if not (data == "delete_location" or data.startswith("delete_loc:") or data == "edit_username"):
            await query.edit_message_text(
                "Errore: La variabile CONTAINER non è impostata nel bot. "
                "Impossibile eseguire questa azione."
            )
            return

    try:
        if data == "edit_username":
            context.user_data["awaiting_username_edit"] = True
            await query.edit_message_text("Ok, inserisci il nuovo username Minecraft:")

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

        elif data.startswith("delete_loc:"):
            name_to_delete = data.split(":", 1)[1]
            if delete_location(uid, name_to_delete):
                await query.edit_message_text(f"Posizione «{name_to_delete}» cancellata 🔥")
            else:
                await query.edit_message_text(f"Posizione «{name_to_delete}» non trovata.")

        elif data == "menu_give":
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
                    "Puoi solo inserire le coordinate manualmente.",
                    reply_markup=InlineKeyboardMarkup([[buttons[0]]])
                 )
                 return

            keyboard_layout = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
            markup = InlineKeyboardMarkup(keyboard_layout)
            text_reply = "Scegli una destinazione:"
            if not online_players and not CONTAINER:
                 text_reply = ("Impossibile ottenere lista giocatori (CONTAINER non settato).\n"
                               "Scegli tra posizioni salvate o coordinate.")
            elif not online_players:
                 text_reply = "Nessun giocatore online.\nScegli tra posizioni salvate o coordinate:"
            await query.edit_message_text(text_reply, reply_markup=markup)


        elif data.startswith("tp_saved:"):
            location_name = data.split(":", 1)[1]
            user_locs = get_locations(uid)
            loc_coords = user_locs.get(location_name)
            if not loc_coords:
                await query.edit_message_text(f"Posizione '{location_name}' non trovata.")
                return
            x, y, z = loc_coords["x"], loc_coords["y"], loc_coords["z"]
            cmd_text = f"tp {minecraft_username} {x} {y} {z}" # Assicurati che minecraft_username sia disponibile
            docker_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_args, read_output=False)
            await query.edit_message_text(f"Teleport eseguito su '{location_name}': {x:.2f}, {y:.2f}, {z:.2f}")

        elif data == "tp_coords_input":
            context.user_data["awaiting_tp_coords_input"] = True
            await query.edit_message_text("Inserisci le coordinate nel formato: `x y z` (es. `100 64 -200`)")

        elif data.startswith("tp_player:"):
            target_player = data.split(":", 1)[1]
            cmd_text = f"tp {minecraft_username} {target_player}" # Assicurati che minecraft_username sia disponibile
            docker_cmd_args = ["docker", "exec", CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await query.edit_message_text(f"Teleport verso {target_player} eseguito!")

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

        # <<< MODIFICA PREFISSO E LOGICA DI DOWNLOAD >>>
        elif data.startswith("download_backup_file:"): # Nuovo prefisso
            backup_filename_from_callback = data.split(":", 1)[1]

            backups_dir = get_backups_storage_path()
            backup_file_path = os.path.join(backups_dir, backup_filename_from_callback)
            logger.info(f"Tentativo di scaricare il file di backup da: {backup_file_path} (richiesto da callback: {data})")

            if os.path.exists(backup_file_path):
                try:
                    # Invia un messaggio di attesa e modifica il messaggio precedente (quello con la lista dei backup)
                    # per rimuovere i bottoni o indicare che il download è in corso per quel file.
                    original_message_text = query.message.text
                    await query.edit_message_text(f"{original_message_text}\n\n⏳ Preparazione invio di '{html.escape(backup_filename_from_callback)}'...")

                    with open(backup_file_path, "rb") as backup_file:
                        await context.bot.send_document(
                            chat_id=query.message.chat_id,
                            document=backup_file,
                            filename=os.path.basename(backup_file_path),
                            caption=f"Backup del mondo: {os.path.basename(backup_file_path)}"
                        )
                    # Dopo l'invio, si potrebbe ripristinare il messaggio originale o aggiornarlo.
                    # Per semplicità, lo lasciamo modificato con "Preparazione invio..."
                    # oppure si può inviare un ulteriore messaggio di conferma:
                    await query.message.reply_text(f"✅ File '{html.escape(backup_filename_from_callback)}' inviato!")

                except Exception as e:
                    logger.error(f"Errore inviando il file di backup '{backup_file_path}': {e}", exc_info=True)
                    await query.message.reply_text(f"⚠️ Impossibile inviare il file di backup '{html.escape(backup_filename_from_callback)}': {e}")
            else:
                logger.warning(f"File di backup non trovato per il download: {backup_file_path}")
                await query.edit_message_text(f"⚠️ File di backup non trovato: <code>{html.escape(backup_filename_from_callback)}</code>. Potrebbe essere stato spostato o cancellato.", parse_mode=ParseMode.HTML)
        # <<< FINE MODIFICA >>>

        elif data.startswith("rp_manage:"):
            pack_uuid = data.split(":", 1)[1]
            # Find the pack name to display in the next message
            try:
                active_packs_details = await asyncio.to_thread(get_world_active_packs_with_details, WORLD_NAME)
                pack_details = next((p for p in active_packs_details if p['uuid'] == pack_uuid), None)
                pack_name = pack_details.get('name', 'Nome Sconosciuto') if pack_details else 'Nome Sconosciuto'
            except Exception:
                pack_name = 'Nome Sconosciuto' # Fallback in case of error

            buttons = [
                [InlineKeyboardButton("🗑️ Elimina", callback_data=f"rp_action:delete:{pack_uuid}")],
                [InlineKeyboardButton("↕️ Sposta", callback_data=f"rp_action:move:{pack_uuid}")],
                [InlineKeyboardButton("↩️ Annulla", callback_data="rp_action:cancel_manage")]
            ]
            reply_markup = InlineKeyboardMarkup(buttons)
            await query.edit_message_text(
                f"Gestisci resource pack: <b>{html.escape(pack_name)}</b> (<code>{pack_uuid[:8]}...</code>)",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )

        elif data.startswith("rp_action:delete:"):
            pack_uuid_to_delete = data.split(":", 2)[2]
            try:
                manage_world_resource_packs_json(
                    WORLD_NAME,
                    pack_uuid_to_remove=pack_uuid_to_delete
                )
                # Log & suggerimento riavvio
                logger.info(f"Resource pack {pack_uuid_to_delete} rimosso — ricordati di /restartserver per applicare.")
                await query.edit_message_text(
                    f"✅ Resource pack <code>{pack_uuid_to_delete[:8]}...</code> eliminato dalla lista attiva.\n"
                    "ℹ️ Per applicare le modifiche, esegui il comando: /restartserver",
                    parse_mode=ParseMode.HTML
                )

            except ResourcePackError as e:
                logger.error(f"📦❌ Errore eliminazione RP {pack_uuid_to_delete}: {e}")
                await query.edit_message_text(f"❌ Errore eliminazione resource pack: {html.escape(str(e))}")
            except Exception as e:
                logger.error(f"🆘 Errore imprevisto eliminazione RP {pack_uuid_to_delete}: {e}", exc_info=True)
                await query.edit_message_text(f"❌ Errore imprevisto durante l'eliminazione: {html.escape(str(e))}")

        elif data.startswith("rp_action:move:"):
            pack_uuid_to_move = data.split(":", 2)[2]
            context.user_data["awaiting_rp_new_position"] = pack_uuid_to_move
            await query.edit_message_text(
                "Inserisci la nuova posizione (numero) per questo resource pack nella lista attiva.\n"
                "La posizione 1 è la più bassa priorità, l'ultima è la più alta."
            )

        elif data == "rp_action:cancel_manage":
            await query.edit_message_text("Gestione resource pack annullata.")

        else:
            await query.edit_message_text("Azione non riconosciuta o scaduta.")

    except asyncio.TimeoutError:
        await query.edit_message_text("Timeout eseguendo l'azione richiesta. Riprova.")
    except subprocess.CalledProcessError as e:
        error_detail = e.stderr or e.output or str(e)
        await query.edit_message_text(f"Errore dal server Minecraft: {error_detail}. Riprova o contatta un admin.")
        logger.error(f"CalledProcessError in button_handler for data '{data}': {e}", exc_info=True)
    except ValueError as e:
        await query.edit_message_text(str(e))
    except Exception as e:
        logger.error(f"Errore imprevisto in button_handler for data '{data}': {e}", exc_info=True)
        await query.edit_message_text("Si è verificato un errore imprevisto. Riprova più tardi.")

async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming document messages, attempting to install them as resource packs."""
    uid = update.effective_user.id
    document = update.message.document

    if not is_user_authenticated(uid):
        await update.message.reply_text("Devi prima effettuare il /login.")
        return

    if not WORLD_NAME:
        await update.message.reply_text("Errore: WORLD_NAME non configurato. Impossibile aggiungere resource pack.")
        return

    if not document:
        await update.message.reply_text("Nessun documento trovato nel messaggio.")
        return

    original_filename = document.file_name
    if not original_filename or not (original_filename.lower().endswith(".zip") or original_filename.lower().endswith(".mcpack")):
        await update.message.reply_text(
            f"Formato file non supportato: {original_filename}. "
            "Invia un file .zip o .mcpack come resource pack."
        )
        return

    await update.message.reply_text(f"Ricevuto file '{original_filename}'. Tentativo di installazione come resource pack...")

    try:
        # Create a temporary directory to save the file
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file_path = os.path.join(temp_dir, original_filename)

            # Download the file
            new_file = await context.bot.get_file(document.file_id)
            await new_file.download_to_drive(custom_path=temp_file_path)
            logger.info(f"Document downloaded to temporary path: {temp_file_path}")

            # Install the resource pack
            installed_pack_path, pack_uuid, pack_version, pack_name = install_resource_pack_from_file(
                temp_file_path, original_filename
            )
            logger.info(f"Resource pack installed: {pack_name} ({pack_uuid})")

            # Activate the resource pack in world_resource_packs.json
            # Add at the beginning (higher priority) as per typical user expectation for new packs
            manage_world_resource_packs_json(
                WORLD_NAME,
                pack_uuid_to_add=pack_uuid,
                pack_version_to_add=pack_version,
                add_at_beginning=True
            )
            logger.info(f"Resource pack {pack_name} ({pack_uuid}) activated for world {WORLD_NAME}.")

            # Log & suggerimento riavvio
            logger.info(f"Resource pack {pack_uuid} aggiunto — ricordati di /restartserver per applicare.")
            await update.message.reply_text(
                f"✅ Resource pack '{pack_name}' installato e attivato per il mondo '{WORLD_NAME}'.\n"
                "ℹ️ Per applicare le modifiche, esegui il comando: /restartserver"
            )

    except ResourcePackError as e:
        logger.error(f"Errore durante l'installazione/attivazione del resource pack: {e}")
        await update.message.reply_text(f"⚠️ Errore durante l'installazione del resource pack: {e}")
    except Exception as e:
        logger.error(f"Errore imprevisto in handle_document_message: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Si è verificato un errore imprevisto durante la gestione del documento: {e}")
