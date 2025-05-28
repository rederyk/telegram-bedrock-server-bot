import asyncio
import subprocess
import html
import uuid
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, get_logger, WORLD_NAME
from user_management import (
    is_user_authenticated, get_minecraft_username, get_locations,
    delete_location, users_data, save_users # Added save_users
)
from docker_utils import run_docker_command, get_online_players_from_server
from world_management import get_backups_storage_path, get_world_directory_path
from resource_pack_management import manage_world_resource_packs_json, ResourcePackError, get_world_active_packs_with_details
# Assuming these command handlers will be imported or called from here
# from command_handlers import show_main_menu_buttons, resource_packs_command

logger = get_logger(__name__)

# Assuming these handlers will be imported from their new files
# from structure_wizard_handlers import handle_wizard_download_split_files, handle_wizard_create_mcpack_split, handle_wizard_create_mcpack_original, handle_structura_opacity_input
# from user_input_handlers import handle_username_input # Although username input is handled in text_message_handler, the resume logic might need this


async def handle_edit_username_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the callback to initiate username editing."""
    query = update.callback_query
    uid = query.from_user.id
    context.user_data["awaiting_username_edit"] = True
    await query.edit_message_text("Ok, inserisci il nuovo username Minecraft:")


async def handle_delete_location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the callback to initiate location deletion."""
    query = update.callback_query
    uid = query.from_user.id
    user_locs = get_locations(uid)
    if not user_locs:
        await query.edit_message_text("Non hai posizioni salvate.")
        return
    buttons = [
        [InlineKeyboardButton(
            f"❌ {name}", callback_data=f"delete_loc:{name}")]
        for name in user_locs
    ]
    buttons.append([InlineKeyboardButton("↩️ Annulla", callback_data="cancel_delete_loc")])
    await query.edit_message_text(
        "Seleziona la posizione da cancellare:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_confirm_delete_location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, location_name: str):
    """Handles the callback to confirm deleting a location."""
    query = update.callback_query
    uid = query.from_user.id
    if delete_location(uid, location_name):
        await query.edit_message_text(f"Posizione «{location_name}» cancellata 🔥")
    else:
        await query.edit_message_text(f"Posizione «{location_name}» non trovata.")


async def handle_cancel_delete_location_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the callback to cancel location deletion."""
    query = update.callback_query
    await query.edit_message_text("Cancellazione posizione annullata.")
    # Potentially show main menu or previous state. For now, just confirm.
    # from command_handlers import show_main_menu_buttons # Example
    # await show_main_menu_buttons(update, context, query.message)


async def handle_menu_give_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the callback for the /give menu."""
    query = update.callback_query
    if not CONTAINER:
         await query.edit_message_text("Errore: CONTAINER non configurato per il comando give.")
         return
    context.user_data["awaiting_give_prefix"] = True
    await query.edit_message_text(
        "Ok, inviami il nome (o parte del nome/ID) dell'oggetto che vuoi dare:"
    )


async def handle_give_item_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, item_id: str):
    """Handles the callback for selecting an item after typing a prefix."""
    query = update.callback_query
    if not CONTAINER:
         await query.edit_message_text("Errore: CONTAINER non configurato per il comando give.")
         return
    context.user_data["selected_item_for_give"] = item_id
    context.user_data["awaiting_item_quantity"] = True
    await query.edit_message_text(f"Item selezionato: {item_id}.\nInserisci la quantità desiderata:")


async def handle_menu_tp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the callback for the /tp menu."""
    query = update.callback_query
    uid = query.from_user.id
    online_players = []
    if CONTAINER: # Only try to get players if CONTAINER is set
        online_players = await get_online_players_from_server()
    else: # If CONTAINER is not set, we can't get players
         await query.edit_message_text(
            "Funzione Teleport limitata: CONTAINER non configurato. "
            "Impossibile visualizzare giocatori online. Puoi usare posizioni salvate o coordinate."
         )
         # Continue to show other TP options

    buttons = []
    if online_players: # This implies CONTAINER was set and call was successful
        buttons.extend([
            InlineKeyboardButton(p, callback_data=f"tp_player:{p}")
            for p in online_players
        ])
    buttons.append(InlineKeyboardButton(
        "📍 Inserisci coordinate", callback_data="tp_coords_input"))
    user_locs = get_locations(uid) # Does not require CONTAINER
    for name_loc in user_locs:
        buttons.append(InlineKeyboardButton(
            f"📌 {name_loc}", callback_data=f"tp_saved:{name_loc}"))

    if not buttons: # Should at least have "Inserisci coordinate"
        await query.edit_message_text(
            "Nessun giocatore online (o CONTAINER non configurato) e nessuna posizione salvata. "
            "Puoi solo inserire le coordinate manualmente.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📍 Inserisci coordinate", callback_data="tp_coords_input")]])
        )
        return

    keyboard_layout = [buttons[i:i+2]
                        for i in range(0, len(buttons), 2)] # 2 buttons per row
    markup = InlineKeyboardMarkup(keyboard_layout)
    text_reply = "Scegli una destinazione:"
    if not online_players and CONTAINER: # CONTAINER set, but no players
        text_reply = "Nessun giocatore online.\nScegli tra posizioni salvate o coordinate:"
    elif not CONTAINER and not online_players: # CONTAINER not set
         text_reply = ("Impossibile ottenere lista giocatori (CONTAINER non settato).\n"
                       "Scegli tra posizioni salvate o coordinate:")
    await query.edit_message_text(text_reply, reply_markup=markup)


async def handle_tp_saved_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, location_name: str):
    """Handles the callback to teleport to a saved location."""
    query = update.callback_query
    uid = query.from_user.id
    minecraft_username = get_minecraft_username(uid) # Get username here
    if not CONTAINER:
         await query.edit_message_text("Errore: CONTAINER non configurato per il comando teleport.")
         return
    user_locs = get_locations(uid)
    loc_coords = user_locs.get(location_name)
    if not loc_coords:
        await query.edit_message_text(f"Posizione '{location_name}' non trovata.")
        return
    x, y, z = loc_coords["x"], loc_coords["y"], loc_coords["z"]
    cmd_text = f"tp {minecraft_username} {x} {y} {z}"
    docker_args = ["docker", "exec",
                    CONTAINER, "send-command", cmd_text]
    await run_docker_command(docker_args, read_output=False)
    await query.edit_message_text(f"Teleport eseguito su '{location_name}': {x:.2f}, {y:.2f}, {z:.2f}")


async def handle_tp_coords_input_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the callback to initiate teleport by coordinates input."""
    query = update.callback_query
    if not CONTAINER:
         await query.edit_message_text("Errore: CONTAINER non configurato per il comando teleport.")
         return
    context.user_data["awaiting_tp_coords_input"] = True
    await query.edit_message_text("Inserisci le coordinate nel formato: `x y z` (es. `100 64 -200`)", parse_mode=ParseMode.MARKDOWN)


async def handle_tp_player_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, target_player: str):
    """Handles the callback to teleport to another player."""
    query = update.callback_query
    uid = query.from_user.id
    minecraft_username = get_minecraft_username(uid) # Get username here
    if not CONTAINER:
         await query.edit_message_text("Errore: CONTAINER non configurato per il comando teleport.")
         return
    cmd_text = f"tp {minecraft_username} {target_player}"
    docker_cmd_args = ["docker", "exec",
                        CONTAINER, "send-command", cmd_text]
    await run_docker_command(docker_cmd_args, read_output=False)
    await query.edit_message_text(f"Teleport verso {target_player} eseguito!")


async def handle_menu_weather_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the callback for the /weather menu."""
    query = update.callback_query
    if not CONTAINER:
        await query.edit_message_text("Errore: CONTAINER non configurato per il comando weather.")
        return
    buttons = [
        [InlineKeyboardButton(
            "☀️ Sereno (Clear)", callback_data="weather_set:clear")],
        [InlineKeyboardButton("🌧 Pioggia (Rain)",
                                callback_data="weather_set:rain")],
        [InlineKeyboardButton(
            "⛈ Temporale (Thunder)", callback_data="weather_set:thunder")]
    ]
    await query.edit_message_text(
        "Scegli le condizioni meteo:", reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_weather_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, weather_condition: str):
    """Handles the callback to set the weather."""
    query = update.callback_query
    if not CONTAINER:
        await query.edit_message_text("Errore: CONTAINER non configurato per il comando weather.")
        return
    cmd_text = f"weather {weather_condition}"
    docker_cmd_args = ["docker", "exec",
                        CONTAINER, "send-command", cmd_text]
    await run_docker_command(docker_cmd_args, read_output=False)
    await query.edit_message_text(f"Meteo impostato su: {weather_condition.capitalize()}")


async def handle_download_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, backup_filename: str):
    """Handles the callback to download a backup file."""
    query = update.callback_query
    backups_dir = get_backups_storage_path() # This function should handle if path is not configured
    if not backups_dir:
        await query.edit_message_text("Errore: Percorso dei backup non configurato nel bot.")
        return

    backup_file_path = os.path.join(
        backups_dir, backup_filename)
    logger.info(
        f"Tentativo di scaricare il file di backup da: {backup_file_path} (richiesto da callback: {query.data})")

    if os.path.exists(backup_file_path) and os.path.isfile(backup_file_path): # also check if it's a file
        try:
            original_message_text = query.message.text
            original_reply_markup = query.message.reply_markup # Save for potential restore
            await query.edit_message_text(f"{original_message_text}\n\n⏳ Preparazione invio di '{html.escape(backup_filename)}'...", reply_markup=None) # Remove buttons during processing

            with open(backup_file_path, "rb") as backup_file:
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=backup_file,
                    filename=os.path.basename(backup_file_path),
                    caption=f"Backup del mondo: {os.path.basename(backup_file_path)}"
                )
            # Optionally, restore the original message text and buttons or send a new confirmation.
            # For simplicity, just send a new message:
            await query.message.reply_text(f"✅ File '{html.escape(backup_filename)}' inviato!")
            # If you want to edit the "Preparazione invio" message:
            # await query.edit_message_text(f"✅ File '{html.escape(backup_filename)}' inviato!", reply_markup=original_reply_markup)

        except Exception as e:
            logger.error(
                f"Errore inviando il file di backup '{backup_file_path}': {e}", exc_info=True)
            # Try to restore original message and buttons if sending failed
            await query.edit_message_text(original_message_text, reply_markup=original_reply_markup)
            await query.message.reply_text(f"⚠️ Impossibile inviare il file di backup '{html.escape(backup_filename)}': {html.escape(str(e))}")
    else:
        logger.warning(
            f"File di backup non trovato o non è un file: {backup_file_path}")
        await query.edit_message_text(f"⚠️ File di backup non trovato: <code>{html.escape(backup_filename)}</code>. Potrebbe essere stato spostato o cancellato.", parse_mode=ParseMode.HTML)


async def handle_rp_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, pack_uuid: str):
    """Handles the callback to manage a specific resource pack."""
    query = update.callback_query
    try:
        active_packs_details = await asyncio.to_thread(get_world_active_packs_with_details, WORLD_NAME)
        pack_details = next(
            (p for p in active_packs_details if p['uuid'] == pack_uuid), None)
        pack_name = pack_details.get(
            'name', 'Nome Sconosciuto') if pack_details else 'Nome Sconosciuto'
    except Exception as e: # Catch broad exceptions for pack detail fetching
        logger.error(f"Error fetching pack details for {pack_uuid}: {e}", exc_info=True)
        pack_name = 'Nome Sconosciuto (errore dettagli)'


    buttons = [
        [InlineKeyboardButton(
            "🗑️ Elimina", callback_data=f"rp_action:delete:{pack_uuid}")],
        [InlineKeyboardButton(
            "↕️ Sposta", callback_data=f"rp_action:move:{pack_uuid}")],
        [InlineKeyboardButton(
            "↩️ Annulla", callback_data="rp_action:cancel_manage")]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(
        f"Gestisci resource pack: <b>{html.escape(pack_name)}</b> (<code>{pack_uuid[:8]}...</code>)",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


async def handle_rp_action_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, pack_uuid_to_delete: str):
    """Handles the callback to delete a resource pack."""
    query = update.callback_query
    try:
        manage_world_resource_packs_json(
            WORLD_NAME,
            pack_uuid_to_remove=pack_uuid_to_delete
        )
        logger.info(
            f"Resource pack {pack_uuid_to_delete} rimosso — ricordati di /restartserver per applicare.")
        await query.edit_message_text(
            f"✅ Resource pack <code>{pack_uuid_to_delete[:8]}...</code> eliminato dalla lista attiva.\n"
            "ℹ️ Per applicare le modifiche, esegui il comando: /restartserver",
            parse_mode=ParseMode.HTML
        )
    except ResourcePackError as e:
        logger.error(
            f"📦❌ Errore eliminazione RP {pack_uuid_to_delete}: {e}")
        await query.edit_message_text(f"❌ Errore eliminazione resource pack: {html.escape(str(e))}")
    except Exception as e:
        logger.error(
            f"🆘 Errore imprevisto eliminazione RP {pack_uuid_to_delete}: {e}", exc_info=True)
        await query.edit_message_text(f"❌ Errore imprevisto durante l'eliminazione: {html.escape(str(e))}")


async def handle_rp_action_move_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, pack_uuid_to_move: str):
    """Handles the callback to initiate moving a resource pack."""
    query = update.callback_query
    context.user_data["awaiting_rp_new_position"] = pack_uuid_to_move
    await query.edit_message_text(
        "Inserisci la nuova posizione (numero) per questo resource pack nella lista attiva.\n"
        "La posizione 1 è la più bassa priorità (in fondo alla lista applicata), l'ultima è la più alta (in cima)."
    )


async def handle_rp_action_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the callback to cancel resource pack management/editing."""
    query = update.callback_query
    await query.edit_message_text("Gestione resource pack annullata.")
    # from command_handlers import resource_packs_command # Example to go back
    # await resource_packs_command(update, context) # This would re-trigger the list


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Answer callback query quickly

    uid = query.from_user.id
    data = query.data

    if not is_user_authenticated(uid):
        await query.edit_message_text("Errore: non sei autenticato. Usa /login.")
        return

    # Handle wizard actions first as they manage their own state/cleanup
    # Import wizard handlers locally to avoid circular dependencies
    from structure_wizard_handlers import (
        handle_wizard_download_split_files, handle_wizard_create_mcpack_split,
        handle_wizard_create_mcpack_original, handle_structura_opacity_input
    )

    if data == "wizard_action:download_split":
        await handle_wizard_download_split_files(update, context)
        return
    elif data == "wizard_action:create_mcpack_split":
        await handle_wizard_create_mcpack_split(update, context)
        return
    elif data == "wizard_action:create_mcpack_original":
        await handle_wizard_create_mcpack_original(update, context)
        return

    # Handle structura opacity from buttons
    if data.startswith("structura_opacity:"):
        try:
            opacity_value = int(data.split(":", 1)[1])
            if 1 <= opacity_value <= 100:
                # We need to ensure the context is set up as handle_structura_opacity_input expects
                # If this callback is hit directly without going through continue_wizard_with_conversion,
                # structura_mcstructure_files and structura_processing_dir might be missing.
                # This usually means the wizard flow was interrupted or state was lost.
                if not context.user_data.get("structura_mcstructure_files") or \
                   not context.user_data.get("structura_processing_dir"):
                    logger.error(f"Structura opacity callback ({data}) called without prior wizard state.")
                    await query.edit_message_text("❌ Errore: Stato del wizard per l'opacità non trovato. Riprova il caricamento del file.")
                    return
                await handle_structura_opacity_input(update, context, opacity_value)
            else:
                await query.edit_message_text("Valore di opacità non valido. Scegli tra i bottoni o invia un numero tra 1 e 100.")
        except ValueError:
            await query.edit_message_text("Valore di opacità non valido (callback). Scegli tra i bottoni o invia un numero tra 1 e 100.")
        return # Consume callback

    # Centralized Minecraft username check for most actions
    actions_not_requiring_mc_username = [
        "edit_username", "download_backup_file:",
        "rp_action:cancel_manage", "rp_action:cancel_edit",
        # Wizard actions are handled above and manage their own username needs.
        # Structura opacity is also handled above.
        "cancel_delete_loc" # Simple cancellation
    ]
    requires_mc_username = not any(data.startswith(prefix) or data == prefix for prefix in actions_not_requiring_mc_username)

    minecraft_username = get_minecraft_username(uid)
    if requires_mc_username and not minecraft_username:
        context.user_data["awaiting_mc_username"] = True
        # Store the callback data so we can resume after username input
        context.user_data["next_action_data"] = {"type": "callback", "data": data, "update": update} # Storing entire update object
        await query.edit_message_text( # Use edit_message_text for callbacks
            "Il tuo username Minecraft non è impostato. Per favore, invialo in chat. "
            "L'azione verrà ripresa automaticamente."
        )
        return

    actions_requiring_container = [
        "give_item_select:", "tp_player:", "tp_coords_input", "weather_set:",
        "tp_saved:", "menu_give", "menu_tp", "menu_weather"
        # Note: 'saveloc' (via /saveloc command) is handled in text_message_handler and checks CONTAINER there.
        # Here we are checking for callback actions that would lead to CONTAINER use.
    ]
    is_action_requiring_container = any(data.startswith(
        action_prefix) for action_prefix in actions_requiring_container)

    # Specific check for "menu_tp" as it calls get_online_players_from_server
    if data == "menu_tp":
        is_action_requiring_container = True


    if not CONTAINER and is_action_requiring_container:
        # Allow delete_location and edit_username even if CONTAINER is not set, as they are user data ops
        # delete_loc: is for deleting, not directly interacting with server.
        if not (data == "delete_location" or data.startswith("delete_loc:") or data == "edit_username"):
            await query.edit_message_text(
                "Errore: La variabile CONTAINER non è impostata nel bot. "
                "Impossibile eseguire questa azione."
            )
            return

    try:
        if data == "edit_username":
            await handle_edit_username_callback(update, context)

        elif data == "delete_location":
            await handle_delete_location_callback(update, context)

        elif data == "cancel_delete_loc":
            await handle_cancel_delete_location_callback(update, context)

        elif data.startswith("delete_loc:"):
            name_to_delete = data.split(":", 1)[1]
            await handle_confirm_delete_location_callback(update, context, name_to_delete)

        elif data == "menu_give":
            await handle_menu_give_callback(update, context)

        elif data.startswith("give_item_select:"):
            item_id = data.split(":", 1)[1]
            await handle_give_item_select_callback(update, context, item_id)

        elif data == "menu_tp":
            await handle_menu_tp_callback(update, context)

        elif data.startswith("tp_saved:"):
            location_name = data.split(":", 1)[1]
            await handle_tp_saved_callback(update, context, location_name)

        elif data == "tp_coords_input":
            await handle_tp_coords_input_callback(update, context)

        elif data.startswith("tp_player:"):
            target_player = data.split(":", 1)[1]
            await handle_tp_player_callback(update, context, target_player)

        elif data == "menu_weather":
            await handle_menu_weather_callback(update, context)

        elif data.startswith("weather_set:"):
            weather_condition = data.split(":", 1)[1]
            await handle_weather_set_callback(update, context, weather_condition)

        elif data.startswith("download_backup_file:"):
            backup_filename_from_callback = data.split(":", 1)[1]
            await handle_download_backup_callback(update, context, backup_filename_from_callback)

        elif data.startswith("rp_manage:"):
            pack_uuid = data.split(":", 1)[1]
            await handle_rp_manage_callback(update, context, pack_uuid)

        elif data.startswith("rp_action:delete:"):
            pack_uuid_to_delete = data.split(":", 2)[2]
            await handle_rp_action_delete_callback(update, context, pack_uuid_to_delete)

        elif data.startswith("rp_action:move:"):
            pack_uuid_to_move = data.split(":", 2)[2]
            await handle_rp_action_move_callback(update, context, pack_uuid_to_move)

        elif data == "rp_action:cancel_manage" or data == "rp_action:cancel_edit":
            await handle_rp_action_cancel_callback(update, context)

        else:
            logger.warning(f"Unhandled callback_query data: {data}")
            await query.edit_message_text("Azione non riconosciuta o scaduta.")

    except asyncio.TimeoutError:
        await query.edit_message_text("Timeout eseguendo l'azione richiesta. Riprova.")
    except subprocess.CalledProcessError as e:
        error_detail = e.stderr or e.output or str(e)
        await query.edit_message_text(f"Errore dal server Minecraft: {html.escape(error_detail)}. Riprova o contatta un admin.")
        logger.error(
            f"CalledProcessError in callback_query_handler for data '{data}': {e}", exc_info=True)
    except ValueError as e: # Catch general ValueErrors that might not be handled by specific blocks
        await query.edit_message_text(f"Errore nei dati forniti: {html.escape(str(e))}")
        logger.error(f"ValueError in callback_query_handler for data '{data}': {e}", exc_info=True)
    except Exception as e:
        logger.error(
            f"Errore imprevisto in callback_query_handler for data '{data}': {e}", exc_info=True)
        await query.edit_message_text("Si è verificato un errore imprevisto. Riprova più tardi.")
