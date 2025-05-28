import asyncio
import subprocess
import html

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, get_logger, WORLD_NAME
from user_management import (
    get_minecraft_username, set_minecraft_username, save_location,
    get_locations, delete_location, users_data, save_users # Added save_users
)
from item_management import get_items
from docker_utils import run_docker_command, get_online_players_from_server
from world_management import get_backups_storage_path, get_world_directory_path
# Assuming these command handlers will be imported or called from here
# from command_handlers import menu_command, give_direct_command, tp_direct_command, weather_direct_command, saveloc_command, paste_hologram_command
# from resource_pack_management import manage_world_resource_packs_json, ResourcePackError
# from callback_handlers import callback_query_handler # Assuming this will be created

logger = get_logger(__name__)


async def handle_username_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handles the input for setting/editing the Minecraft username."""
    uid = update.effective_user.id
    if not text:
        await update.message.reply_text("Nome utente Minecraft non valido. Riprova.")
        return
    set_minecraft_username(uid, text)
    context.user_data.pop("awaiting_mc_username", None)
    await update.message.reply_text(f"Username Minecraft '{text}' salvato.")

    next_action_data = context.user_data.pop("next_action_data", None)
    if next_action_data:
        action_type = next_action_data.get("type")
        original_update_obj = next_action_data.get("update")
        original_context_args = next_action_data.get("args", [])

        if original_update_obj is None:
            logger.error("next_action_data missing original_update_obj")
            await update.message.reply_text("Errore interno, azione successiva non chiara.")
            return

        # Reconstruct the context for the original command if necessary
        # This part is tricky and depends on what 'original_update_obj' and 'context' are needed for.
        # For simplicity, we assume the current 'update' and 'context' are sufficient
        # or the specific handlers know how to use 'original_update_obj'.

        # Import command handlers locally to avoid circular dependencies if they also import message_handlers
        from command_handlers import (
            menu_command, give_direct_command, tp_direct_command,
            weather_direct_command, saveloc_command, paste_hologram_command
        )
        from callback_handlers import callback_query_handler # Assuming this will be created

        if action_type == "menu":
            await menu_command(original_update_obj, context)
        elif action_type == "give":
            await give_direct_command(original_update_obj, context)
        elif action_type == "tp":
            await tp_direct_command(original_update_obj, context)
        elif action_type == "weather":
            await weather_direct_command(original_update_obj, context)
        elif action_type == "saveloc":
            await saveloc_command(original_update_obj, context)
        elif action_type == "paste_hologram":
            await paste_hologram_command(original_update_obj, context)
        elif action_type == "handle_document_wizard":
             # This case needs careful handling. If the document data was stored,
             # you'd re-trigger the wizard. Otherwise, inform the user.
             # For now, assume re-upload is needed if data isn't explicitly stored.
             await update.message.reply_text("File info not found to resume wizard. Please upload again.")
        elif action_type == "callback": # Handle resumed callback queries
            original_callback_data = next_action_data.get("data")
            if original_callback_data and original_update_obj.callback_query:
                 # Restore the original callback data for the handler
                original_update_obj.callback_query.data = original_callback_data
                await callback_query_handler(original_update_obj, context)
            else:
                logger.error("Callback action resume failed: missing data or original callback_query")
                await update.message.reply_text("Errore riprendendo l'azione precedente.")
        else:
            await update.message.reply_text("Ora puoi usare i comandi che richiedono l'username (es. /menu).")
    else:
        await update.message.reply_text("Ora puoi usare i comandi che richiedono l'username (es. /menu).")


async def handle_username_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handles the input for editing the Minecraft username after /edituser."""
    uid = update.effective_user.id
    if not text:
        await update.message.reply_text("Nome utente non valido. Riprova.")
        return
    users_data[uid]["minecraft_username"] = text
    save_users() # Assuming save_users is accessible
    context.user_data.pop("awaiting_username_edit", None)
    await update.message.reply_text(f"Username aggiornato a: {text}")


async def handle_saveloc_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handles the input for the saveloc name."""
    uid = update.effective_user.id
    location_name = text
    if not location_name:
        await update.message.reply_text("Nome posizione non valido. Riprova.")
        return
    context.user_data.pop("awaiting_saveloc_name", None)

    if not CONTAINER:
        await update.message.reply_text("Impossibile salvare la posizione: CONTAINER non configurato.")
        return
    minecraft_username = get_minecraft_username(uid) # Get username here
    if not minecraft_username:
        await update.message.reply_text("Username Minecraft non impostato. Non posso salvare la posizione.")
        # Consider re-prompting for username or guiding the user
        return

    docker_cmd_get_pos = [
        "docker", "exec", CONTAINER, "send-command",
        f"execute as {minecraft_username} at @s run tp @s ~ ~ ~0.0001"
    ]
    try:
        logger.info(
            f"Esecuzione per ottenere coordinate: {' '.join(docker_cmd_get_pos)}")
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
            logger.warning(
                f"Nessuna coordinata trovata nei log per {minecraft_username} dopo /saveloc.")
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
        logger.error(f"ValueError in saveloc parsing coordinates: {e} from output: {output}", exc_info=True)
        await update.message.reply_text(f"Errore interpretando le coordinate dai log: {str(e)}")
    except Exception as e:
        logger.error(
            f"Errore in /saveloc (esecuzione comando): {e}", exc_info=True)
        await update.message.reply_text("Si è verificato un errore salvando la posizione.")


async def handle_give_prefix_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handles the input for the item prefix for the /give command."""
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
            ) for i in matches[:20] # Show max 20 items
        ]
        keyboard = [[button] for button in buttons] # One button per row

        await update.message.reply_text(
            f"Ho trovato {len(matches)} item (mostro i primi {len(buttons)}). Scegli un item:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    context.user_data.pop("awaiting_give_prefix", None)


async def handle_item_quantity_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handles the input for the item quantity for the /give command."""
    uid = update.effective_user.id
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

        minecraft_username = get_minecraft_username(uid) # Get username here
        if not minecraft_username:
            await update.message.reply_text("Username Minecraft non impostato. Non posso eseguire /give.")
            return

        cmd_text = f"give {minecraft_username} {item_id} {quantity}"
        docker_cmd_args = ["docker", "exec",
                            CONTAINER, "send-command", cmd_text]
        await run_docker_command(docker_cmd_args, read_output=False)
        await update.message.reply_text(f"Comando eseguito: /give {minecraft_username} {item_id} {quantity}")

    except ValueError as e:
        if "La quantità deve essere positiva" in str(e):
            await update.message.reply_text("Inserisci un numero valido (intero, maggiore di zero) per la quantità.")
        else:
            await update.message.reply_text("Quantità non valida. Inserisci un numero intero.")
        # Don't clear state if input is invalid, user should retry quantity
    except asyncio.TimeoutError:
        await update.message.reply_text("Timeout eseguendo il comando give.")
        context.user_data.pop("selected_item_for_give", None)
        context.user_data.pop("awaiting_item_quantity", None)
    except subprocess.CalledProcessError as e:
        await update.message.reply_text(f"Errore dal server Minecraft: {e.stderr or e.output or e}")
        context.user_data.pop("selected_item_for_give", None)
        context.user_data.pop("awaiting_item_quantity", None)
    except Exception as e:
        logger.error(
            f"Errore imprevisto in handle_item_quantity_input: {e}", exc_info=True)
        await update.message.reply_text(f"Errore imprevisto: {e}")
        context.user_data.pop("selected_item_for_give", None)
        context.user_data.pop("awaiting_item_quantity", None)
    finally:
        # Clear state only on success or unrecoverable error, not on simple invalid input for quantity
        if "quantity" in locals() or isinstance(e, (asyncio.TimeoutError, subprocess.CalledProcessError, Exception)):
             context.user_data.pop("selected_item_for_give", None)
             context.user_data.pop("awaiting_item_quantity", None)


async def handle_rp_new_position_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handles the input for the new resource pack position."""
    pack_uuid_to_move = context.user_data.pop(
        "awaiting_rp_new_position", None) # Clear state immediately
    if not pack_uuid_to_move: # Should not happen if state was set correctly
        await update.message.reply_text("Errore interno: UUID del resource pack da spostare non trovato.")
        return

    try:
        new_position = int(text)
        if new_position <= 0:
            raise ValueError(
                "La posizione deve essere un numero positivo.")

        new_index = new_position - 1 # Adjust for 0-based index

        # Assuming manage_world_resource_packs_json and ResourcePackError are accessible
        from resource_pack_management import manage_world_resource_packs_json, ResourcePackError
        manage_world_resource_packs_json(
            WORLD_NAME,
            pack_uuid_to_move=pack_uuid_to_move,
            new_index_for_move=new_index
        )

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
        context.user_data["awaiting_rp_new_position"] = pack_uuid_to_move # Restore state if input is invalid
    except ResourcePackError as e:
        logger.error(f"📦❌ Errore spostamento RP {pack_uuid_to_move}: {e}")
        await update.message.reply_text(f"❌ Errore spostamento resource pack: {html.escape(str(e))}")
    except Exception as e:
        logger.error(
            f"🆘 Errore imprevisto spostamento RP {pack_uuid_to_move}: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore imprevisto durante lo spostamento: {html.escape(str(e))}")


async def handle_tp_coords_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handles the input for teleport coordinates."""
    uid = update.effective_user.id
    if not CONTAINER:
        await update.message.reply_text("Errore: CONTAINER non configurato per il comando teleport.")
        context.user_data.pop("awaiting_tp_coords_input", None)
        return

    parts = text.split()
    if len(parts) != 3:
        await update.message.reply_text(
            "Formato coordinate non valido. Usa: x y z (es. 100 64 -200). Riprova o /menu, /tp."
        )
        # Don't clear state, let user retry
    else:
        try:
            x, y, z = map(float, parts)
            minecraft_username = get_minecraft_username(uid) # Get username here
            if not minecraft_username:
                await update.message.reply_text("Username Minecraft non impostato. Non posso eseguire /tp.")
                return

            cmd_text = f"tp {minecraft_username} {x} {y} {z}"
            docker_cmd_args = ["docker", "exec",
                                CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await update.message.reply_text(f"Comando eseguito: /tp {minecraft_username} {x} {y} {z}")
            context.user_data.pop("awaiting_tp_coords_input", None) # Clear on success

        except ValueError as e: # Catches map(float, parts) error
            await update.message.reply_text(
                "Le coordinate devono essere numeri validi (es. 100 64.5 -200). Riprova o /menu, /tp."
            )
            # Don't clear state, let user retry
        except asyncio.TimeoutError:
            await update.message.reply_text("Timeout eseguendo il comando teleport.")
            context.user_data.pop("awaiting_tp_coords_input", None) # Clear on this error
        except subprocess.CalledProcessError as e:
            await update.message.reply_text(f"Errore dal server Minecraft: {e.stderr or e.output or e}")
            context.user_data.pop("awaiting_tp_coords_input", None) # Clear on this error
        except Exception as e:
            logger.error(
                f"Errore imprevisto in handle_tp_coords_input: {e}", exc_info=True)
            await update.message.reply_text(f"Errore imprevisto: {e}")
            context.user_data.pop("awaiting_tp_coords_input", None) # Clear on this error
