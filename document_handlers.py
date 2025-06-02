import os
import tempfile
import shutil
import html

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import get_logger, WORLD_NAME
from user_management import is_user_authenticated, get_minecraft_username
# Assuming these handlers will be imported from their new files
from structure_wizard_handlers import process_structure_file_wizard
from hologram_handlers import handle_hologram_structure_upload, cleanup_hologram_data # Added cleanup_hologram_data
from resource_pack_management import install_resource_pack_from_file, manage_world_resource_packs_json, ResourcePackError # Added ResourcePackError
from importBuild.lite2Edit import litematica_converter

logger = get_logger(__name__)


async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming document messages."""
    uid = update.effective_user.id
    if not update.message or not update.message.document:
        logger.warning("handle_document_message: No message or document found.")
        # update.message might be None if this handler is called incorrectly
        if update.message:
            await update.message.reply_text("Nessun documento trovato nel messaggio.")
        return

    document = update.message.document
    original_filename = document.file_name

    if not is_user_authenticated(uid):
        await update.message.reply_text("Devi prima effettuare il /login.")
        return

    # Controllo per paste hologram
    if context.user_data.get("awaiting_hologram_structure"):
        if original_filename and (original_filename.lower().endswith((".schematic", ".mcstructure", ".schem"))):
            # Scarica il file per paste hologram
            temp_dir = tempfile.mkdtemp(prefix="tgbot_hologram_")
            downloaded_file_path = os.path.join(temp_dir, original_filename)

            try:
                new_file = await context.bot.get_file(document.file_id)
                await new_file.download_to_drive(custom_path=downloaded_file_path)
                logger.info(f"Hologram structure downloaded: {downloaded_file_path}")

                context.user_data.pop("awaiting_hologram_structure", None)
                await handle_hologram_structure_upload(update, context, downloaded_file_path, original_filename)
                return

            except Exception as e:
                logger.error(f"Error downloading hologram structure: {e}", exc_info=True)
                await update.message.reply_text(f"❌ Errore scaricamento file: {html.escape(str(e))}")
                # Assuming cleanup_hologram_data is a defined function
                cleanup_hologram_data(context)
                return
        else:
            await update.message.reply_text("❌ File non valido. Invia un file .mcstructure, .schematic o .schem")
            return

    # Litematica conversion
    if original_filename and original_filename.lower().endswith(".litematic"):
        # Download the file
        temp_dir = tempfile.mkdtemp(prefix="tgbot_litematica_")
        downloaded_file_path = os.path.join(temp_dir, original_filename)

        try:
            new_file = await context.bot.get_file(document.file_id)
            await new_file.download_to_drive(custom_path=downloaded_file_path)
            logger.info(f"Litematica file downloaded: {downloaded_file_path}")

            # Convert the file
            output_dir = temp_dir  # Save the schematic in the same temp dir
            output_file = litematica_converter.convert_litematica_to_schematic(downloaded_file_path, output_dir)

            if output_file:
                await update.message.reply_document(
                    document=open(output_file, 'rb'),
                    filename=os.path.basename(output_file),
                    caption="✅ Conversione completata!"
                )
                logger.info(f"Litematica file converted to schematic: {output_file}")
            else:
                await update.message.reply_text("❌ Conversione fallita.")
            return
        except Exception as e:
            logger.error(f"Error during litematica conversion: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Errore durante la conversione: {html.escape(str(e))}")
        finally:
            # Clean up the temporary directory
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"Cleaned up temporary directory: {temp_dir}")
            except Exception as cleanup_e:
                logger.error(f"Error cleaning up temporary directory {temp_dir}: {cleanup_e}", exc_info=True)
        return

    # Check for structure file wizard
    if original_filename and (original_filename.lower().endswith((".schematic", ".mcstructure", ".schem"))):
        # Minecraft username is not directly needed for the wizard scripts themselves,
        # but good to inform the user.
        minecraft_username = get_minecraft_username(uid)
        if not minecraft_username:
            await update.message.reply_text(
                "💡 Per alcune funzionalità (come i comandi diretti al server), è necessario il tuo username Minecraft. "
                "Puoi impostarlo con /edituser. L'elaborazione del file procederà comunque."
            )
        # No need to block wizard for username, scripts handle files.

        # Download the file to a temporary path first
        # Create a unique subdirectory within a base temp directory for this operation
        base_temp_dir = tempfile.mkdtemp(prefix="tgbot_base_") # Base dir for this operation
        download_dir = os.path.join(base_temp_dir, "download")
        os.makedirs(download_dir, exist_ok=True)
        downloaded_file_path = os.path.join(download_dir, original_filename)

        try:
            new_file = await context.bot.get_file(document.file_id)
            await new_file.download_to_drive(custom_path=downloaded_file_path)
            logger.info(f"Document '{original_filename}' downloaded to temporary path: {downloaded_file_path} for wizard.")

            # Call the wizard function
            # The wizard itself will create its own processing_dir and clean it up.
            # The downloaded_file_path (and its parent base_temp_dir) should be cleaned up here.
            await process_structure_file_wizard(downloaded_file_path, original_filename, update, context)
        except Exception as e:
            logger.error(f"Error downloading file for wizard or during wizard prep: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error preparing file for processing: {html.escape(str(e))}")
        finally:
            # Cleanup the base_temp_dir which contains the initially downloaded file
            try:
                if os.path.exists(base_temp_dir):
                    shutil.rmtree(base_temp_dir)
                    logger.info(f"Cleaned up base temporary download directory: {base_temp_dir}")
            except Exception as cleanup_e:
                logger.error(f"Error cleaning up base temp download directory {base_temp_dir}: {cleanup_e}", exc_info=True)
        return # Wizard handled this document

    # Existing resource pack logic
    if not WORLD_NAME:
        await update.message.reply_text("Errore: WORLD_NAME non configurato. Impossibile aggiungere resource pack.")
        return

    if not (original_filename.lower().endswith(".zip") or original_filename.lower().endswith(".mcpack")):
        await update.message.reply_text(
            f"Formato file non supportato: {original_filename}. "
            "Invia un file .zip o .mcpack come resource pack, oppure .schematic/.mcstructure/.schem per il wizard strutture."
        )
        return

    await update.message.reply_text(f"Ricevuto file '{original_filename}'. Tentativo di installazione come resource pack...")

    # Use a temporary directory that will be cleaned up
    with tempfile.TemporaryDirectory(prefix="tgbot_rp_download_") as temp_dir_for_rp_download:
        temp_file_path = os.path.join(temp_dir_for_rp_download, original_filename)
        try:
            new_file = await context.bot.get_file(document.file_id)
            await new_file.download_to_drive(custom_path=temp_file_path)
            logger.info(
                f"Resource pack document downloaded to temporary path: {temp_file_path}")

            # install_resource_pack_from_file should handle moving the file to a persistent location
            # and does not need the temp_file_path to persist after it's done.
            installed_pack_path, pack_uuid, pack_version, pack_name = install_resource_pack_from_file(
                temp_file_path, original_filename # WORLD_NAME is used internally by this func
            )
            logger.info(f"Resource pack installed: {pack_name} ({pack_uuid})")

            manage_world_resource_packs_json(
                WORLD_NAME,
                pack_uuid_to_add=pack_uuid,
                pack_version_to_add=pack_version,
                add_at_beginning=True # New packs get higher priority (top of the list in UI, applied last)
            )
            logger.info(
                f"Resource pack {pack_name} ({pack_uuid}) activated for world {WORLD_NAME}.")

            await update.message.reply_text(
                f"✅ Resource pack '{html.escape(pack_name)}' installato e attivato per il mondo '{html.escape(WORLD_NAME)}'.\n"
                "ℹ️ Per applicare le modifiche, esegui il comando: /restartserver\n"
                "ℹ️ Per gestire i resource pack attivi (es. ordine, eliminazione), usa: /editresourcepacks",
                parse_mode=ParseMode.HTML
            )
        except ResourcePackError as e:
            logger.error(
                f"Errore durante l'installazione/attivazione del resource pack: {e}")
            await update.message.reply_text(f"⚠️ Errore durante l'installazione del resource pack: {html.escape(str(e))}")
        except Exception as e:
            logger.error(
                f"Errore imprevisto in handle_document_message (resource pack): {e}", exc_info=True)
            await update.message.reply_text(f"❌ Si è verificato un errore imprevisto durante la gestione del documento: {html.escape(str(e))}")
        # temp_dir_for_rp_download is cleaned up automatically by with statement
