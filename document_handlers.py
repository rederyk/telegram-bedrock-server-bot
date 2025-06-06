import os
import tempfile
import shutil
import html
import zipfile

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


def check_zip_for_minecraft_content(zip_path):
    """
    Analizza un file ZIP per determinare il tipo di contenuto.
    Ritorna: 'resource_pack', 'structures', 'litematic', 'mixed', o 'unknown'
    """
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_file:
            file_list = zip_file.namelist()
            
            # Controlla se è un resource pack (presenza di manifest.json)
            has_manifest = any('manifest.json' in f for f in file_list)
            if has_manifest:
                return 'resource_pack'
            
            # Cerca file di strutture
            structure_extensions = ('.schematic', '.mcstructure', '.schem')
            structure_files = [f for f in file_list if f.lower().endswith(structure_extensions)]
            
            # Cerca file litematic
            litematic_files = [f for f in file_list if f.lower().endswith('.litematic')]
            
            if structure_files and litematic_files:
                return 'mixed'
            elif structure_files:
                return 'structures'
            elif litematic_files:
                return 'litematic'
            else:
                return 'unknown'
    except Exception as e:
        logger.error(f"Error analyzing ZIP file {zip_path}: {e}")
        return 'unknown'


def extract_files_from_zip(zip_path, target_extensions, extract_to_dir):
    """
    Estrae file con estensioni specifiche da un ZIP.
    Ritorna una lista di percorsi dei file estratti.
    """
    extracted_files = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_file:
            for file_info in zip_file.infolist():
                if not file_info.is_dir() and file_info.filename.lower().endswith(target_extensions):
                    # Estrai solo il nome del file senza directory annidate
                    filename = os.path.basename(file_info.filename)
                    if filename:  # Assicurati che non sia vuoto
                        extract_path = os.path.join(extract_to_dir, filename)
                        with zip_file.open(file_info) as source, open(extract_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
                        extracted_files.append(extract_path)
                        logger.info(f"Extracted {filename} from ZIP to {extract_path}")
    except Exception as e:
        logger.error(f"Error extracting files from ZIP: {e}")
    
    return extracted_files


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

    # Check for structure file wizard (singoli file)
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

    # Gestione file ZIP e MCPACK
    if original_filename and (original_filename.lower().endswith(".zip") or original_filename.lower().endswith(".mcpack")):
        
        # Download del file per analisi
        temp_base_dir = tempfile.mkdtemp(prefix="tgbot_zip_analysis_")
        downloaded_file_path = os.path.join(temp_base_dir, original_filename)
        
        try:
            new_file = await context.bot.get_file(document.file_id)
            await new_file.download_to_drive(custom_path=downloaded_file_path)
            logger.info(f"ZIP/MCPACK file downloaded for analysis: {downloaded_file_path}")
            
            # Analizza il contenuto del file ZIP
            zip_content_type = check_zip_for_minecraft_content(downloaded_file_path)
            logger.info(f"ZIP content type detected: {zip_content_type}")
            
            if zip_content_type == 'resource_pack':
                # È un resource pack valido, procedi con la logica esistente
                if not WORLD_NAME:
                    await update.message.reply_text("Errore: WORLD_NAME non configurato. Impossibile aggiungere resource pack.")
                    return
                
                await update.message.reply_text(f"Ricevuto resource pack '{original_filename}'. Tentativo di installazione...")
                
                try:
                    installed_pack_path, pack_uuid, pack_version, pack_name = install_resource_pack_from_file(
                        downloaded_file_path, original_filename
                    )
                    logger.info(f"Resource pack installed: {pack_name} ({pack_uuid})")

                    manage_world_resource_packs_json(
                        WORLD_NAME,
                        pack_uuid_to_add=pack_uuid,
                        pack_version_to_add=pack_version,
                        add_at_beginning=True
                    )
                    logger.info(f"Resource pack {pack_name} ({pack_uuid}) activated for world {WORLD_NAME}.")

                    await update.message.reply_text(
                        f"✅ Resource pack '{html.escape(pack_name)}' installato e attivato per il mondo '{html.escape(WORLD_NAME)}'.\n"
                        "ℹ️ Per applicare le modifiche, esegui il comando: /restartserver\n"
                        "ℹ️ Per gestire i resource pack attivi (es. ordine, eliminazione), usa: /editresourcepacks",
                        parse_mode=ParseMode.HTML
                    )
                except ResourcePackError as e:
                    logger.error(f"Errore durante l'installazione/attivazione del resource pack: {e}")
                    await update.message.reply_text(f"⚠️ Errore durante l'installazione del resource pack: {html.escape(str(e))}")
                
            elif zip_content_type in ['structures', 'litematic', 'mixed']:
                # Il ZIP contiene strutture o file litematic
                await update.message.reply_text(f"📦 Analizzando il contenuto di '{original_filename}'...")
                
                # Directory per estrarre i file
                extract_dir = os.path.join(temp_base_dir, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                
                processed_files = []
                
                if zip_content_type in ['structures', 'mixed']:
                    # Estrai file di strutture
                    structure_files = extract_files_from_zip(
                        downloaded_file_path, 
                        ('.schematic', '.mcstructure', '.schem'), 
                        extract_dir
                    )
                    
                    if structure_files:
                        await update.message.reply_text(f"🏗️ Trovati {len(structure_files)} file di strutture. Elaborazione...")
                        
                        for structure_file in structure_files:
                            try:
                                filename = os.path.basename(structure_file)
                                await process_structure_file_wizard(structure_file, filename, update, context)
                                processed_files.append(f"✅ {filename} (struttura)")
                            except Exception as e:
                                logger.error(f"Error processing structure file {structure_file}: {e}")
                                processed_files.append(f"❌ {os.path.basename(structure_file)} (errore struttura)")
                
                if zip_content_type in ['litematic', 'mixed']:
                    # Estrai e converti file litematic
                    litematic_files = extract_files_from_zip(
                        downloaded_file_path, 
                        ('.litematic',), 
                        extract_dir
                    )
                    
                    if litematic_files:
                        await update.message.reply_text(f"🔧 Trovati {len(litematic_files)} file Litematic. Conversione...")
                        
                        for litematic_file in litematic_files:
                            try:
                                filename = os.path.basename(litematic_file)
                                # Converti il file litematic
                                output_file = litematica_converter.convert_litematica_to_schematic(litematic_file, extract_dir)
                                
                                if output_file:
                                    await update.message.reply_document(
                                        document=open(output_file, 'rb'),
                                        filename=os.path.basename(output_file),
                                        caption=f"✅ Conversione completata: {filename}"
                                    )
                                    processed_files.append(f"✅ {filename} (convertito)")
                                else:
                                    processed_files.append(f"❌ {filename} (conversione fallita)")
                            except Exception as e:
                                logger.error(f"Error processing litematic file {litematic_file}: {e}")
                                processed_files.append(f"❌ {os.path.basename(litematic_file)} (errore conversione)")
                
                # Riepilogo elaborazione
                if processed_files:
                    summary = "\n".join(processed_files)
                    await update.message.reply_text(
                        f"📋 **Riepilogo elaborazione di '{original_filename}':**\n\n{summary}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await update.message.reply_text("❌ Nessun file valido trovato nel ZIP.")
                    
            else:
                # Contenuto sconosciuto
                await update.message.reply_text(
                    f"❓ Il file '{original_filename}' non contiene un manifest per resource pack "
                    "né file di strutture o Litematic riconoscibili.\n"
                    "Formati supportati:\n"
                    "• Resource pack: file .zip/.mcpack con manifest.json\n"
                    "• Strutture: .schematic, .mcstructure, .schem\n"
                    "• Litematic: .litematic"
                )
        
        except Exception as e:
            logger.error(f"Error processing ZIP/MCPACK file: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Errore durante l'elaborazione del file: {html.escape(str(e))}")
        
        finally:
            # Pulizia directory temporanea
            try:
                if os.path.exists(temp_base_dir):
                    shutil.rmtree(temp_base_dir)
                    logger.info(f"Cleaned up temporary directory: {temp_base_dir}")
            except Exception as cleanup_e:
                logger.error(f"Error cleaning up temp directory {temp_base_dir}: {cleanup_e}", exc_info=True)
        
        return  # File ZIP/MCPACK gestito
    
    # Se arriviamo qui, il file non è supportato
    await update.message.reply_text(
        f"❌ Formato file non supportato: {original_filename}\n\n"
        "Formati supportati:\n"
        "• Resource pack: .zip/.mcpack (con manifest.json)\n"
        "• Strutture: .schematic/.mcstructure/.schem\n"
        "• Litematic: .litematic\n"
        "• Archivi: .zip (contenenti strutture o file litematic)"
    )