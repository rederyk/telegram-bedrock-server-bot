# minecraft_telegram_bot/message_handlers.py
import asyncio
import subprocess
import uuid
import re
import os
import html
import tempfile
import shutil
from pathlib import Path

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
from world_management import get_backups_storage_path, get_world_directory_path
from command_handlers import menu_command, give_direct_command, tp_direct_command, weather_direct_command, saveloc_command
from resource_pack_management import install_resource_pack_from_file, manage_world_resource_packs_json, ResourcePackError


logger = get_logger(__name__)

PYTHON_AMULET = "/app/importBuild/schem_to_mc_amulet/venv/bin/python"
PYTHON_STRUCTURA = "/app/importBuild/structura_env/venv/bin/python"
SPLIT_SCRIPT = "/app/importBuild/schem_to_mc_amulet/split_mcstructure.py"
CONVERT_SCRIPT = "/app/importBuild/schem_to_mc_amulet/convert2mc.py"
STRUCTURA_SCRIPT = "/app/importBuild/structura_env/structuraCli.py"
STRUCTURA_DIR = "/app/importBuild/structura_env"

SPLIT_THRESHOLD = 5000


async def _run_script(command: list[str], update: Update, context: ContextTypes.DEFAULT_TYPE, step_name: str, cwd: str | None = None) -> tuple[str, str, int] | None:
    """
    Helper to run a script as a subprocess and handle basic errors/logging.
    Returns (stdout, stderr, returncode) or None on major error.
    """
    try:
        logger.info(f"Running {step_name}: {' '.join(command)} in CWD: {cwd or os.getcwd()}")
        # Determine the appropriate reply target (message or callback query message)
        reply_target = update.message or (update.callback_query.message if update.callback_query else None)
        if reply_target:
            await reply_target.reply_text(f"⏳ Running {step_name}...")
        else:
            logger.warning(f"No reply target found for {step_name} status update.")

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd
        )
        stdout_bytes, stderr_bytes = await process.communicate()
        stdout = stdout_bytes.decode().strip()
        stderr = stderr_bytes.decode().strip()
        logger.info(f"{step_name} stdout: {stdout}")
        if stderr:
            logger.error(f"{step_name} stderr: {stderr}")

        if process.returncode != 0:
            if reply_target:
                await reply_target.reply_text(
                    f"❌ Error during {step_name} (Code {process.returncode}).\n"
                    f"Details:\n<pre>{html.escape(stderr)}</pre>",
                    parse_mode=ParseMode.HTML
                )
            return None
        return stdout, stderr, process.returncode
    except FileNotFoundError:
        logger.error(f"❌ FileNotFoundError for {step_name}: Command or script not found. Check paths: {command[0]}, {command[1]}")
        reply_target = update.message or (update.callback_query.message if update.callback_query else None)
        if reply_target:
            await reply_target.reply_text(f"❌ Error: Script for {step_name} not found. Please check bot configuration.")
        return None
    except Exception as e:
        logger.error(f"❌ Exception during {step_name}: {e}", exc_info=True)
        reply_target = update.message or (update.callback_query.message if update.callback_query else None)
        if reply_target:
            await reply_target.reply_text(f"❌ An unexpected error occurred during {step_name}: {html.escape(str(e))}")
        return None

def _parse_output_files_from_stdout(stdout: str, base_dir: str) -> list[str]:
    """
    Parses stdout for output file paths.
    Looks for lines like "Output file: /path/to/file" or "Created: /path/to/file"
    Also tries to find .mcstructure, .schematic, .mcpack files mentioned in stdout.
    Paths are made relative to base_dir if they are absolute and within it,
    or assumed to be relative to base_dir if not absolute.
    """
    found_files = []
    # Regex to find file paths, can be absolute or relative
    # It tries to capture common wordings like "Output file:", "Created:", etc.
    # and then the path itself.
    # It also captures paths ending with specific extensions directly.
    regex = re.compile(
        r"(?:Output file|Created|Output mcstructure|Output mcpack|Successfully converted to|Successfully created pack):\s*([/\w\s.-]+\.(?:mcstructure|schematic|mcpack))|"
        r"([/\w\s.-]+\.(?:mcstructure|schematic|mcpack))" # Direct path
    )
    for line in stdout.splitlines():
        match = regex.search(line)
        if match:
            # Match groups: first is path after a keyword, second is direct path
            path_str = match.group(1) or match.group(2)
            if path_str:
                path_str = path_str.strip()
                # Ensure the path is absolute or correctly relative to base_dir
                if os.path.isabs(path_str):
                    # If it's within base_dir, use it. Otherwise, it's unexpected.
                    if path_str.startswith(base_dir):
                        abs_path = path_str
                    else:
                        logger.warning(f"Absolute path {path_str} found in stdout is outside base_dir {base_dir}. Skipping.")
                        continue
                else:
                    # If relative, join with base_dir
                    abs_path = os.path.join(base_dir, path_str)

                if os.path.exists(abs_path):
                    if abs_path not in found_files:
                        found_files.append(abs_path)
                else:
                    logger.warning(f"File path '{abs_path}' (from stdout line '{line}') does not exist. Skipping.")
    logger.info(f"Parsed output files from stdout: {found_files}")
    return found_files


async def process_structure_file_wizard(downloaded_file_path: str, original_filename: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes a structure file through splitting, conversion to mcstructure, and conversion to mcpack."""
    await update.message.reply_text(f"🧙‍♂️ Starting automatic wizard for {original_filename}...")

    processing_dir = tempfile.mkdtemp(prefix="tgbot_structure_wizard_")
    logger.info(f"Wizard processing in temp directory: {processing_dir}")

    try:
        current_input_filename = original_filename
        current_input_file = os.path.join(processing_dir, current_input_filename)
        shutil.copy(downloaded_file_path, current_input_file)

        # If the file is .schem, rename it to .schematic for compatibility with scripts
        if current_input_filename.lower().endswith(".schem"):
            new_filename = Path(current_input_filename).with_suffix(".schematic").name
            new_input_file_path = os.path.join(processing_dir, new_filename)
            os.rename(current_input_file, new_input_file_path)
            logger.info(f"Renamed .schem file {current_input_filename} to {new_filename} for processing.")
            current_input_file = new_input_file_path
            current_input_filename = new_filename
            await update.message.reply_text(f"ℹ️ Rinomino il file in `{new_filename}` per compatibilità.", parse_mode=ParseMode.MARKDOWN)

        # Store original file info for later use
        context.user_data["wizard_original_file"] = current_input_file
        context.user_data["wizard_processing_dir"] = processing_dir


        # --- Step 1: Splitting ---
        await update.message.reply_text("✂️ Attempting to split the structure...")
        split_command = [
            PYTHON_AMULET, SPLIT_SCRIPT,
            current_input_file,
            "--threshold", str(SPLIT_THRESHOLD)
        ]
        split_result = await _run_script(split_command, update, context, "splitting", cwd=processing_dir)
        if not split_result:
            return

        split_stdout, _, _ = split_result
        split_output_files = _parse_output_files_from_stdout(split_stdout, processing_dir)

        if not split_output_files:
            logger.info("No output files parsed from split stdout, listing directory for schematics/mcstructures.")
            all_files_in_processing_dir = [os.path.join(processing_dir, f) for f in os.listdir(processing_dir)]
            potential_split_files = [
                f for f in all_files_in_processing_dir
                if f.lower().endswith((".schematic", ".mcstructure")) and os.path.isfile(f)
            ]
            if len(potential_split_files) == 1 and Path(potential_split_files[0]).name == Path(current_input_file).name:
                split_output_files = [potential_split_files[0]]
                logger.info(f"Split step resulted in one file (likely original or modified): {split_output_files}")
            elif not potential_split_files:
                logger.error("Split step: No structure files found in processing dir after split attempt and stdout parsing failed.")
                await update.message.reply_text("❌ Split step failed to produce output files.")
                return
            else:
                part_files = [f for f in potential_split_files if "_part" in Path(f).name]
                if part_files:
                    split_output_files = part_files
                else:
                    split_output_files = potential_split_files
                logger.info(f"Split step directory listing found: {split_output_files}")

        if not split_output_files:
            await update.message.reply_text("❌ No output files found after split attempt. Using original file.")
            split_output_files = [current_input_file]

        # Check if files were actually split (more than 1 file or different from original)
        was_split = len(split_output_files) > 1 or (
            len(split_output_files) == 1 and 
            Path(split_output_files[0]).name != Path(current_input_file).name
        )

        if was_split:
            # Show the split files to the user and ask what to do
            files_list = "\n".join([f"• {Path(f).name}" for f in split_output_files])
            await update.message.reply_text(
                f"✅ File diviso con successo in {len(split_output_files)} parti:\n\n{files_list}\n\n"
                "Cosa vuoi fare?"
            )

            # Store the split files info for later use
            context.user_data["wizard_split_files"] = split_output_files

            # Create buttons for user choice
            buttons = [
                [InlineKeyboardButton("📥 Scarica i file divisi", callback_data="wizard_action:download_split")],
                [InlineKeyboardButton("📦 Crea mcpack dalle parti divise", callback_data="wizard_action:create_mcpack_split")],
                [InlineKeyboardButton("📦 Crea mcpack dalla struttura originale", callback_data="wizard_action:create_mcpack_original")]
            ]
            reply_markup = InlineKeyboardMarkup(buttons)

            await update.message.reply_text(
                "Scegli un'opzione:",
                reply_markup=reply_markup
            )
            return # Wait for user choice

        else:
            # File was not split, proceed directly with conversion
            await update.message.reply_text("ℹ️ Il file non è stato diviso (dimensione sotto la soglia). Procedo con la conversione...")
            await continue_wizard_with_conversion(split_output_files, processing_dir, update, context)

    except Exception as e:
        logger.error(f"Unhandled error in structure wizard: {e}", exc_info=True)
        await update.message.reply_text(f"🆘 An critical error occurred in the wizard: {html.escape(str(e))}")
        try:
            if 'processing_dir' in locals() and os.path.exists(processing_dir):
                shutil.rmtree(processing_dir)
                logger.info(f"Cleaned up temporary directory: {processing_dir}")
        except Exception as cleanup_e:
            logger.error(f"Error cleaning up temp directory {processing_dir} after error: {cleanup_e}", exc_info=True)


async def handle_wizard_create_mcpack_original(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle creating mcpack from original unsplit file."""
    original_file = context.user_data.pop("wizard_original_file", None)
    processing_dir = context.user_data.pop("wizard_processing_dir", None)
    
    # Clean up split files data since we're not using them
    context.user_data.pop("wizard_split_files", None)

    if not original_file or not processing_dir or not os.path.exists(processing_dir):
        logger.error("Wizard create original mcpack: Missing original file or processing directory.")
        reply_target = update.message or (update.callback_query.message if update.callback_query else None)
        if reply_target:
            await reply_target.reply_text(
                "❌ Errore interno: file originale mancante o scaduto. Riprova caricando di nuovo il file."
            )
        return

    reply_target = update.message or (update.callback_query.message if update.callback_query else None)
    if reply_target:
        await reply_target.reply_text("📦 Procedo con la creazione dell'mcpack dalla struttura originale...")

    # Process only the original file
    await continue_wizard_with_conversion([original_file], processing_dir, update, context)


async def handle_wizard_create_mcpack_split(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle creating mcpack from split files."""
    split_files = context.user_data.pop("wizard_split_files", None)
    processing_dir = context.user_data.pop("wizard_processing_dir", None)
    
    # Clean up original file data since we're not using it
    context.user_data.pop("wizard_original_file", None)

    if not split_files or not processing_dir or not os.path.exists(processing_dir):
        logger.error("Wizard create split mcpack: Missing split files or processing directory.")
        reply_target = update.message or (update.callback_query.message if update.callback_query else None)
        if reply_target:
            await reply_target.reply_text(
                "❌ Errore interno: file divisi mancanti o scaduti. Riprova caricando di nuovo il file."
            )
        return

    reply_target = update.message or (update.callback_query.message if update.callback_query else None)
    if reply_target:
        await reply_target.reply_text(f"📦 Procedo con la creazione di {len(split_files)} mcpack dalle parti divise...")

    # Process the split files
    await continue_wizard_with_conversion(split_files, processing_dir, update, context)


async def continue_wizard_with_conversion(split_output_files: list[str], processing_dir: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Continue the wizard with conversion to mcstructure and then mcpack creation."""
    try:
        # --- Step 2: Conversion to .mcstructure (if needed) ---
        reply_target = update.message or (update.callback_query.message if update.callback_query else None)
        if reply_target:
            await reply_target.reply_text("🔄 Converting files to .mcstructure format (if necessary)...")

        mcstructure_files = []
        for file_to_convert_path in split_output_files:
            if file_to_convert_path.lower().endswith(".mcstructure"):
                mcstructure_files.append(file_to_convert_path)
                logger.info(f"File {file_to_convert_path} is already .mcstructure.")
                if reply_target:
                    await reply_target.reply_text(f"ℹ️ {Path(file_to_convert_path).name} is already .mcstructure.")
            elif file_to_convert_path.lower().endswith(".schematic"):
                convert_command = [PYTHON_AMULET, CONVERT_SCRIPT, file_to_convert_path]
                convert_result = await _run_script(convert_command, update, context, f"converting {Path(file_to_convert_path).name}", cwd=processing_dir)
                if not convert_result:
                    continue

                convert_stdout, _, _ = convert_result
                converted_paths = _parse_output_files_from_stdout(convert_stdout, processing_dir)

                if converted_paths:
                    mcstructure_files.extend(p for p in converted_paths if p.lower().endswith(".mcstructure"))
                else:
                    assumed_mcstructure_path = Path(file_to_convert_path).with_suffix(".mcstructure")
                    if assumed_mcstructure_path.exists():
                        mcstructure_files.append(str(assumed_mcstructure_path))
                        logger.info(f"Assumed converted file: {assumed_mcstructure_path}")
                    else:
                        if reply_target:
                            await reply_target.reply_text(f"❌ Failed to find/determine .mcstructure output for {Path(file_to_convert_path).name}.")
                        logger.error(f"Could not determine output for {file_to_convert_path} from convert2mc.py stdout: {convert_stdout}")
            else:
                logger.warning(f"Skipping unknown file type from split: {file_to_convert_path}")

        if not mcstructure_files:
            if reply_target:
                await reply_target.reply_text("❌ No .mcstructure files to process after conversion step.")
            try:
                shutil.rmtree(processing_dir)
                logger.info(f"Cleaned up temporary directory: {processing_dir}")
            except Exception as e:
                logger.error(f"Error cleaning up temp directory {processing_dir}: {e}", exc_info=True)
            return

        # --- Step 3: Ask for Opacity ---
        if reply_target:
            await reply_target.reply_text("🎨 Quale opacità desideri per il resource pack?")

        context.user_data["awaiting_structura_opacity"] = True
        context.user_data["structura_mcstructure_files"] = mcstructure_files
        context.user_data["structura_processing_dir"] = processing_dir

        buttons = [
            [InlineKeyboardButton("30%", callback_data="structura_opacity:30")],
            [InlineKeyboardButton("50%", callback_data="structura_opacity:50")],
            [InlineKeyboardButton("80%", callback_data="structura_opacity:80")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        if reply_target:
            await reply_target.reply_text(
                "Scegli un'opacità predefinita o invia un numero tra 1 e 100:",
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"Unhandled error in continue_wizard_with_conversion: {e}", exc_info=True)
        reply_target = update.message or (update.callback_query.message if update.callback_query else None)
        if reply_target:
            await reply_target.reply_text(f"🆘 An critical error occurred in the wizard: {html.escape(str(e))}")
        try:
            if os.path.exists(processing_dir):
                shutil.rmtree(processing_dir)
                logger.info(f"Cleaned up temporary directory: {processing_dir}")
        except Exception as cleanup_e:
            logger.error(f"Error cleaning up temp directory {processing_dir} after error: {cleanup_e}", exc_info=True)


async def handle_wizard_download_split_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle downloading split files and cleanup."""
    split_files = context.user_data.pop("wizard_split_files", None)
    processing_dir = context.user_data.pop("wizard_processing_dir", None)
    
    # Clean up original file data since we're downloading splits
    context.user_data.pop("wizard_original_file", None)

    if not split_files or not processing_dir or not os.path.exists(processing_dir):
        logger.error("Wizard download: Missing files or processing directory.")
        reply_target = update.message or (update.callback_query.message if update.callback_query else None)
        if reply_target:
            await reply_target.reply_text(
                "❌ Errore interno: dati per il download mancanti o scaduti. Riprova caricando di nuovo il file."
            )
        return

    reply_target = update.message or (update.callback_query.message if update.callback_query else None)
    
    try:
        if reply_target:
            await reply_target.reply_text(f"📥 Invio {len(split_files)} file(i) divisi...")

        for file_path in split_files:
            try:
                with open(file_path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=f,
                        filename=Path(file_path).name
                    )
                logger.info(f"Sent split file {file_path} to user.")
            except Exception as e:
                logger.error(f"Error sending split file {file_path}: {e}", exc_info=True)
                if reply_target:
                    await reply_target.reply_text(f"⚠️ Could not send file {Path(file_path).name}: {html.escape(str(e))}")

        if reply_target:
            await reply_target.reply_text("✅ Tutti i file divisi sono stati inviati!")

    except Exception as e:
        logger.error(f"Unhandled error in handle_wizard_download_split_files: {e}", exc_info=True)
        if reply_target:
            await reply_target.reply_text(f"🆘 An error occurred while sending files: {html.escape(str(e))}")
    finally:
        # Cleanup
        try:
            if os.path.exists(processing_dir):
                shutil.rmtree(processing_dir)
                logger.info(f"Cleaned up temporary directory: {processing_dir}")
        except Exception as e:
            logger.error(f"Error cleaning up temp directory {processing_dir}: {e}", exc_info=True)


async def handle_structura_opacity_input(update: Update, context: ContextTypes.DEFAULT_TYPE, opacity_value: int):
    """Handles the opacity input for Structura and proceeds with mcpack creation."""
    mcstructure_files = context.user_data.pop("structura_mcstructure_files", None)
    processing_dir = context.user_data.pop("structura_processing_dir", None)
    context.user_data.pop("awaiting_structura_opacity", None)

    if not mcstructure_files or not processing_dir or not os.path.exists(processing_dir):
        logger.error("Structura opacity handler: Missing files or processing directory.")
        reply_target = update.message or (update.callback_query.message if update.callback_query else None)
        if reply_target:
            await reply_target.reply_text(
                "❌ Errore interno: dati per la creazione del pacchetto mancanti o scaduti. Riprova caricando di nuovo il file."
            )
        # Attempt cleanup if processing_dir exists but data was missing
        if processing_dir and os.path.exists(processing_dir):
            try:
                shutil.rmtree(processing_dir)
                logger.info(f"Cleaned up temporary directory: {processing_dir}")
            except Exception as cleanup_e:
                logger.error(f"Error cleaning up temp directory {processing_dir} after data error: {cleanup_e}", exc_info=True)
        return

    reply_target = update.message or (update.callback_query.message if update.callback_query else None)
    
    # Messaggio più specifico in base al numero di file
    if len(mcstructure_files) == 1:
        if reply_target:
            await reply_target.reply_text(f"📦 Creazione mcpack con opacità {opacity_value}%...")
    else:
        if reply_target:
            await reply_target.reply_text(f"📦 Creazione di {len(mcstructure_files)} mcpack (uno per ogni parte) con opacità {opacity_value}%...")
    
    if not reply_target:
        logger.warning("No reply target found for structura opacity input status update.")


    final_mcpack_files = []
    try:
        for i, mcstructure_file_path in enumerate(mcstructure_files):
            pack_name_base = Path(mcstructure_file_path).stem
            pack_name = re.sub(r'\W+', '_', pack_name_base)
            if not pack_name:
                pack_name = f"structure_pack_{i+1}"

            structura_command = [
                PYTHON_STRUCTURA, STRUCTURA_SCRIPT,
                pack_name,
                "--structures", mcstructure_file_path,
                "--opacity", str(opacity_value)
            ]
            structura_result = await _run_script(
                structura_command,
                update,
                context,
                f"creating .mcpack for {Path(mcstructure_file_path).name}",
                cwd=STRUCTURA_DIR
            )
            if not structura_result:
                continue

            structura_stdout, _, _ = structura_result
            created_mcpacks = _parse_output_files_from_stdout(structura_stdout, STRUCTURA_DIR)

            if created_mcpacks:
                final_mcpack_files.extend(p for p in created_mcpacks if p.lower().endswith(".mcpack"))
            else:
                assumed_mcpack_path1 = Path(STRUCTURA_DIR) / f"{pack_name}.mcpack"
                assumed_mcpack_path2 = Path(STRUCTURA_DIR) / "packs" / f"{pack_name}.mcpack"

                if assumed_mcpack_path2.exists():
                    final_mcpack_files.append(str(assumed_mcpack_path2))
                    logger.info(f"Assumed .mcpack output (in packs/): {assumed_mcpack_path2}")
                elif assumed_mcpack_path1.exists():
                    final_mcpack_files.append(str(assumed_mcpack_path1))
                    logger.info(f"Assumed .mcpack output: {assumed_mcpack_path1}")
                else:
                    reply_target = update.message or (update.callback_query.message if update.callback_query else None)
                    if reply_target:
                        await reply_target.reply_text(f"❌ Failed to find .mcpack output for {Path(mcstructure_file_path).name}.")
                    logger.error(f"Could not determine .mcpack output for {mcstructure_file_path} from structuraCli.py stdout: {structura_stdout}")


        # --- Send files ---
        if final_mcpack_files:
            reply_target = update.message or (update.callback_query.message if update.callback_query else None)
            if reply_target:
                await reply_target.reply_text(f"✅ Wizard finished! Sending {len(final_mcpack_files)} .mcpack file(s)...")
            for mcpack_path in final_mcpack_files:
                try:
                    with open(mcpack_path, "rb") as f:
                        await context.bot.send_document(
                            chat_id=(update.effective_chat.id),
                            document=f,
                            filename=Path(mcpack_path).name
                        )
                    logger.info(f"Sent {mcpack_path} to user.")
                except Exception as e:
                    logger.error(f"Error sending file {mcpack_path}: {e}", exc_info=True)
                    reply_target = update.message or (update.callback_query.message if update.callback_query else None)
                    if reply_target:
                        await reply_target.reply_text(f"⚠️ Could not send file {Path(mcpack_path).name}: {html.escape(str(e))}")
        else:
            reply_target = update.message or (update.callback_query.message if update.callback_query else None)
            if reply_target:
                await reply_target.reply_text("❌ Wizard completed, but no .mcpack files were generated.")

    except Exception as e:
        logger.error(f"Unhandled error in structura opacity handler: {e}", exc_info=True)
        reply_target = update.message or (update.callback_query.message if update.callback_query else None)
        if reply_target:
            await reply_target.reply_text(f"🆘 An critical error occurred: {html.escape(str(e))}")
    finally:
        # --- Cleanup ---
        try:
            if os.path.exists(processing_dir):
                shutil.rmtree(processing_dir)
                logger.info(f"Cleaned up temporary directory: {processing_dir}")
        except Exception as e:
            logger.error(f"Error cleaning up temp directory {processing_dir}: {e}", exc_info=True)



async def handle_armor_stand_save(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """
    Gestisce il salvataggio della posizione dell'armor stand rilevato
    """
    uid = update.effective_user.id
    
    if text.lower() == "no":
        context.user_data.pop("detected_armor_stand", None)
        context.user_data.pop("awaiting_armor_stand_save", None)
        await update.message.reply_text("❌ Salvataggio posizione annullato.")
        return
    
    armor_stand_data = context.user_data.pop("detected_armor_stand", None)
    context.user_data.pop("awaiting_armor_stand_save", None)
    
    if not armor_stand_data:
        await update.message.reply_text("❌ Dati armor stand non trovati. Riprova il rilevamento.")
        return
    
    location_name = f"{text}_armor_stand"
    coords = armor_stand_data["armor_stand_coords"]
    
    save_location(uid, location_name, coords)
    await update.message.reply_text(
        f"✅ Posizione armor stand salvata come '{location_name}'!\n"
        f"📍 Coordinate: X={coords['x']:.1f}, Y={coords['y']:.1f}, Z={coords['z']:.1f}\n"
        f"🧭 Orientamento: {armor_stand_data['direction']}"
    )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if not is_user_authenticated(uid):
        await update.message.reply_text("Devi prima effettuare il /login.")
        return

    # Handle Structura opacity input
    if context.user_data.get("awaiting_structura_opacity"):
        try:
            opacity_value = int(text)
            if 1 <= opacity_value <= 100:
                await handle_structura_opacity_input(update, context, opacity_value)
            else:
                await update.message.reply_text("Valore di opacità non valido. Inserisci un numero tra 1 e 100.")
        except ValueError:
            await update.message.reply_text("Input non valido. Inserisci un numero tra 1 e 100 per l'opacità.")
        return # Consume the message if we were awaiting opacity

    # --- Integration for handle_armor_stand_save ---
    if context.user_data.get("awaiting_armor_stand_save"):
        # The 'text' here will be the user's response (e.g., "no" or the desired name)
        await handle_armor_stand_save(update, context, text)
        return # Consume the message
    # --- End of integration ---
# SOSTITUISCI la sezione di gestione username in handle_text_message con questa:

    # Gestione inserimento username Minecraft
    if context.user_data.get("awaiting_mc_username"):
        if not text:
            await update.message.reply_text("Nome utente Minecraft non valido. Riprova.")
            return
        set_minecraft_username(uid, text)
        context.user_data.pop("awaiting_mc_username")
        await update.message.reply_text(f"Username Minecraft '{text}' salvato.")

        next_action_data = context.user_data.pop("next_action_data", None)
        if next_action_data:
            action_type = next_action_data.get("type")
            original_update_obj = next_action_data.get("update") # Renamed to avoid clash
            original_context_args = next_action_data.get("args", []) # Store original args if any

            if original_update_obj is None: # Should not happen if logic is correct
                logger.error("next_action_data missing original_update_obj")
                await update.message.reply_text("Errore interno, azione successiva non chiara.")
                return

            # Reconstruct the context for the original command if necessary
            # This part is tricky and depends on what 'original_update_obj' and 'context' are needed for.
            # For simplicity, we assume the current 'update' and 'context' are sufficient
            # or the specific handlers know how to use 'original_update_obj'.

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
                # Importa la funzione necessaria
                from command_handlers import paste_hologram_command
                await paste_hologram_command(original_update_obj, context)
            elif action_type == "handle_document_wizard":
                logger.warning("Re-triggering wizard after username prompt - this path needs careful review.")
                # Potentially re-call handle_document_message if the file data was stored
                # For now, this 'pass' means the user might need to re-upload.
                # To properly resume, you'd need to store the downloaded file path or file_id
                # and then re-trigger process_structure_file_wizard.
                # Example:
                # stored_file_info = context.user_data.pop("pending_document_wizard", None)
                # if stored_file_info:
                #     await process_structure_file_wizard(
                #         stored_file_info["path"],
                #         stored_file_info["filename"],
                #         original_update_obj, # or the current update if appropriate
                #         context
                #     )
                # else:
                # await update.message.reply_text("File info not found to resume wizard. Please upload again.")
                pass
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
        return
    minecraft_username = get_minecraft_username(uid)
    # No direct 'else' needed here, other handlers will check minecraft_username if they need it.

    # Gestione modifica username
    if context.user_data.get("awaiting_username_edit"):
        if not text:
            await update.message.reply_text("Nome utente non valido. Riprova.")
            return
        users_data[uid]["minecraft_username"] = text
        from user_management import save_users # Ensure this import is available or move save_users
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
        if not minecraft_username: # Checked after pop, as it's crucial for the command
            await update.message.reply_text("Username Minecraft non impostato. Non posso salvare la posizione.")
            # Consider re-prompting for username or guiding the user
            return
        
        # Ensure minecraft_username is available for the command
        if not minecraft_username:
            await update.message.reply_text("Username Minecraft non impostato. Usa /edituser o imposta il tuo username.")
            # Potentially re-prompt for username here too if saveloc is critical path
            # context.user_data["awaiting_mc_username"] = True
            # context.user_data["next_action_data"] = {"type": "saveloc_retry", "location_name": location_name, "update": update} # Custom state
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
        return

    # Gestione salvataggio posizione armor stand
    if context.user_data.get("awaiting_armor_stand_save"):
        await handle_armor_stand_save(update, context, text)
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
                ) for i in matches[:20] # Show max 20 items
            ]
            # Ensure keyboard is a list of lists for rows
            keyboard = [[button] for button in buttons] # One button per row
            # Or for multiple buttons per row:
            # keyboard = [buttons[j:j+1] for j in range(len(buttons))] # This seems to be the original intention for 1 per row
            # For 2 per row:
            # keyboard = [buttons[j:j+2] for j in range(0, len(buttons), 2)]

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
                context.user_data.pop("awaiting_item_quantity", None) # Clear state
                return
            
            if not minecraft_username: # Crucial check
                await update.message.reply_text("Username Minecraft non impostato. Non posso eseguire /give.")
                # Potentially re-prompt for username here
                # context.user_data["awaiting_mc_username"] = True
                # context.user_data["next_action_data"] = {
                #     "type": "give_retry", # Custom state to retry give
                #     "item_id": item_id,
                #     "quantity_text": text, # Store the quantity text to re-parse
                #     "update": update
                # }
                # Don't clear awaiting_item_quantity and selected_item_for_give if you want to retry
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
        except subprocess.CalledProcessError as e:
            await update.message.reply_text(f"Errore dal server Minecraft: {e.stderr or e.output or e}")
        except Exception as e:
            logger.error(
                f"Errore imprevisto in handle_message (give quantity): {e}", exc_info=True)
            await update.message.reply_text(f"Errore imprevisto: {e}")
        finally:
            # Clear state only on success or unrecoverable error, not on simple invalid input for quantity
            if "quantity" in locals() or isinstance(e, (asyncio.TimeoutError, subprocess.CalledProcessError, Exception)):
                 context.user_data.pop("selected_item_for_give", None)
                 context.user_data.pop("awaiting_item_quantity", None)
        return

    # Gestione nuova posizione resource pack
    if context.user_data.get("awaiting_rp_new_position"):
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
            # Don't clear state, let user retry
        else:
            try:
                x, y, z = map(float, parts)
                if not minecraft_username: # Crucial check
                    await update.message.reply_text("Username Minecraft non impostato. Non posso eseguire /tp.")
                    # Potentially re-prompt for username
                    # context.user_data["awaiting_mc_username"] = True
                    # context.user_data["next_action_data"] = {
                    # "type": "tp_coords_retry", # Custom state
                    # "coords_text": text, # Store coords to re-parse
                    # "update": update
                    # }
                    # Don't clear awaiting_tp_coords_input if you want to retry
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
                    f"Errore imprevisto in handle_message (tp coords): {e}", exc_info=True)
                await update.message.reply_text(f"Errore imprevisto: {e}")
                context.user_data.pop("awaiting_tp_coords_input", None) # Clear on this error
        return


    if not text.startswith('/'): # Default for non-command text if no state is active
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
            logger.warning(
                "Inline query: lista ITEMS vuota o non disponibile.")
        else:
            matches = [
                i for i in all_items
                if query in i["id"].lower() or query in i["name"].lower()
            ]
            # Ensure minecraft_username is fetched for the template string
            # This is tricky for inline mode as user context isn't directly tied
            # For now, use a placeholder or instruct user to replace it.
            # A better approach would be a different command structure for inline results.
            mc_user_placeholder = "{MINECRAFT_USERNAME}" # Placeholder

            results = [
                InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    title=i["name"],
                    description=f'ID: {i["id"]}',
                    input_message_content=InputTextMessageContent(
                        # User will need to replace placeholder or bot needs to know username
                        f'/give {mc_user_placeholder} {i["id"]} 1'
                    )
                ) for i in matches[:20] # Show max 20 results
            ]
    await update.inline_query.answer(results, cache_time=10)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Answer callback query quickly

    uid = query.from_user.id
    data = query.data

    if not is_user_authenticated(uid):
        await query.edit_message_text("Errore: non sei autenticato. Usa /login.")
        return

    # Handle wizard actions first as they manage their own state/cleanup
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
            context.user_data["awaiting_username_edit"] = True
            await query.edit_message_text("Ok, inserisci il nuovo username Minecraft:")

        elif data == "delete_location":
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
        elif data == "cancel_delete_loc":
            await query.edit_message_text("Cancellazione posizione annullata.")
            # Potentially show main menu or previous state. For now, just confirm.
            # from command_handlers import show_main_menu_buttons # Example
            # await show_main_menu_buttons(update, context, query.message)


        elif data.startswith("delete_loc:"):
            name_to_delete = data.split(":", 1)[1]
            if delete_location(uid, name_to_delete):
                await query.edit_message_text(f"Posizione «{name_to_delete}» cancellata 🔥")
            else:
                await query.edit_message_text(f"Posizione «{name_to_delete}» non trovata.")

        elif data == "menu_give": # Requires CONTAINER for eventual 'give' command
            if not CONTAINER:
                 await query.edit_message_text("Errore: CONTAINER non configurato per il comando give.")
                 return
            context.user_data["awaiting_give_prefix"] = True
            await query.edit_message_text(
                "Ok, inviami il nome (o parte del nome/ID) dell'oggetto che vuoi dare:"
            )

        elif data.startswith("give_item_select:"): # Requires CONTAINER
            if not CONTAINER:
                 await query.edit_message_text("Errore: CONTAINER non configurato per il comando give.")
                 return
            item_id = data.split(":", 1)[1]
            context.user_data["selected_item_for_give"] = item_id
            context.user_data["awaiting_item_quantity"] = True
            await query.edit_message_text(f"Item selezionato: {item_id}.\nInserisci la quantità desiderata:")

        elif data == "menu_tp": # Requires CONTAINER for get_online_players and eventual 'tp'
            # Minecraft username check is already done above if required by logic
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


        elif data.startswith("tp_saved:"): # Requires CONTAINER
            if not CONTAINER:
                 await query.edit_message_text("Errore: CONTAINER non configurato per il comando teleport.")
                 return
            location_name = data.split(":", 1)[1]
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

        elif data == "tp_coords_input": # Leads to action requiring CONTAINER
            if not CONTAINER:
                 await query.edit_message_text("Errore: CONTAINER non configurato per il comando teleport.")
                 return
            context.user_data["awaiting_tp_coords_input"] = True
            await query.edit_message_text("Inserisci le coordinate nel formato: `x y z` (es. `100 64 -200`)", parse_mode=ParseMode.MARKDOWN)

        elif data.startswith("tp_player:"): # Requires CONTAINER
            if not CONTAINER:
                 await query.edit_message_text("Errore: CONTAINER non configurato per il comando teleport.")
                 return
            target_player = data.split(":", 1)[1]
            cmd_text = f"tp {minecraft_username} {target_player}"
            docker_cmd_args = ["docker", "exec",
                                CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await query.edit_message_text(f"Teleport verso {target_player} eseguito!")

        elif data == "menu_weather": # Requires CONTAINER
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

        elif data.startswith("weather_set:"): # Requires CONTAINER
            if not CONTAINER:
                await query.edit_message_text("Errore: CONTAINER non configurato per il comando weather.")
                return
            weather_condition = data.split(":", 1)[1]
            cmd_text = f"weather {weather_condition}"
            docker_cmd_args = ["docker", "exec",
                                CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await query.edit_message_text(f"Meteo impostato su: {weather_condition.capitalize()}")

        elif data.startswith("download_backup_file:"): # Does not require CONTAINER
            backup_filename_from_callback = data.split(":", 1)[1]
            backups_dir = get_backups_storage_path() # This function should handle if path is not configured
            if not backups_dir:
                await query.edit_message_text("Errore: Percorso dei backup non configurato nel bot.")
                return

            backup_file_path = os.path.join(
                backups_dir, backup_filename_from_callback)
            logger.info(
                f"Tentativo di scaricare il file di backup da: {backup_file_path} (richiesto da callback: {data})")

            if os.path.exists(backup_file_path) and os.path.isfile(backup_file_path): # also check if it's a file
                try:
                    original_message_text = query.message.text
                    original_reply_markup = query.message.reply_markup # Save for potential restore
                    await query.edit_message_text(f"{original_message_text}\n\n⏳ Preparazione invio di '{html.escape(backup_filename_from_callback)}'...", reply_markup=None) # Remove buttons during processing

                    with open(backup_file_path, "rb") as backup_file:
                        await context.bot.send_document(
                            chat_id=query.message.chat_id,
                            document=backup_file,
                            filename=os.path.basename(backup_file_path),
                            caption=f"Backup del mondo: {os.path.basename(backup_file_path)}"
                        )
                    # Optionally, restore the original message text and buttons or send a new confirmation.
                    # For simplicity, just send a new message:
                    await query.message.reply_text(f"✅ File '{html.escape(backup_filename_from_callback)}' inviato!")
                    # If you want to edit the "Preparazione invio" message:
                    # await query.edit_message_text(f"✅ File '{html.escape(backup_filename_from_callback)}' inviato!", reply_markup=original_reply_markup)

                except Exception as e:
                    logger.error(
                        f"Errore inviando il file di backup '{backup_file_path}': {e}", exc_info=True)
                    # Try to restore original message and buttons if sending failed
                    await query.edit_message_text(original_message_text, reply_markup=original_reply_markup)
                    await query.message.reply_text(f"⚠️ Impossibile inviare il file di backup '{html.escape(backup_filename_from_callback)}': {html.escape(str(e))}")
            else:
                logger.warning(
                    f"File di backup non trovato o non è un file: {backup_file_path}")
                await query.edit_message_text(f"⚠️ File di backup non trovato: <code>{html.escape(backup_filename_from_callback)}</code>. Potrebbe essere stato spostato o cancellato.", parse_mode=ParseMode.HTML)

        elif data.startswith("rp_manage:"): # Does not directly require CONTAINER, but leads to actions that might
            pack_uuid = data.split(":", 1)[1]
            try:
                from resource_pack_management import get_world_active_packs_with_details
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
                    "↕️ Sposta", callback_data=f"rp_action:move:{pack_uuid}")], # Corrected typo from ) to }
                [InlineKeyboardButton(
                    "↩️ Annulla", callback_data="rp_action:cancel_manage")]
            ]
            reply_markup = InlineKeyboardMarkup(buttons)
            await query.edit_message_text(
                f"Gestisci resource pack: <b>{html.escape(pack_name)}</b> (<code>{pack_uuid[:8]}...</code>)",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )

        elif data.startswith("rp_action:delete:"):
            pack_uuid_to_delete = data.split(":", 2)[2] # rp_action:delete:UUID
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

        elif data.startswith("rp_action:move:"):
            pack_uuid_to_move = data.split(":", 2)[2] # rp_action:move:UUID
            context.user_data["awaiting_rp_new_position"] = pack_uuid_to_move
            await query.edit_message_text(
                "Inserisci la nuova posizione (numero) per questo resource pack nella lista attiva.\n"
                "La posizione 1 è la più bassa priorità (in fondo alla lista applicata), l'ultima è la più alta (in cima)."
            )

        elif data == "rp_action:cancel_manage" or data == "rp_action:cancel_edit":
            await query.edit_message_text("Gestione resource pack annullata.")
            # from command_handlers import resource_packs_command # Example to go back
            # await resource_packs_command(update, context) # This would re-trigger the list

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

    # NUOVO: Controllo per paste hologram
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

    # CONTINUA con la logica esistente per wizard e resource pack...
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

# Aggiungi queste funzioni alla FINE del file message_handlers.py

async def handle_hologram_structure_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, structure_file_path: str, original_filename: str):
    """
    Gestisce il caricamento del file struttura per paste hologram
    """
    uid = update.effective_user.id
    minecraft_username = get_minecraft_username(uid)
    
    # Salva il percorso del file per uso successivo
    context.user_data["hologram_structure_path"] = structure_file_path
    context.user_data["hologram_structure_name"] = original_filename
    
    await update.message.reply_text(
        f"📁 File '{original_filename}' ricevuto!\n"
        "🔍 Avvio rilevamento armor stand..."
    )
    
    # Avvia il rilevamento armor stand
    await detect_armor_stand_for_hologram_improved(update, context, minecraft_username)



# Versione migliorata del rilevamento armor stand
# Sostituisci la funzione detect_armor_stand_for_hologram esistente

async def detect_armor_stand_for_hologram_improved(update: Update, context: ContextTypes.DEFAULT_TYPE, minecraft_username: str):
    """
    Versione migliorata del rilevamento armor stand per paste hologram
    - Usa intervalli di rotazione più precisi
    - Implementa doppia verifica
    - Calcola la distanza per validare il risultato
    """
    
    # Orientamenti con intervalli più precisi e meno sovrapposizione
    orientations = {
        "Nord": {
            "ry_ranges": [(-22.5, 22.5), (337.5, 360)],  # Gestisce il wrap-around
            "direction": "north", 
            "angle": 0,
            "expected_facing": "nord"
        },
        "Est": {
            "ry_ranges": [(22.5, 112.5)],
            "direction": "east", 
            "angle": 90,
            "expected_facing": "est"
        },
        "Sud": {
            "ry_ranges": [(112.5, 202.5)],
            "direction": "south", 
            "angle": 180,
            "expected_facing": "sud"
        },
        "Ovest": {
            "ry_ranges": [(202.5, 292.5)],
            "direction": "west", 
            "angle": 270,
            "expected_facing": "ovest"
        },
        "Nord-Ovest": {
            "ry_ranges": [(292.5, 337.5)],
            "direction": "west", 
            "angle": 315,
            "expected_facing": "nord-ovest"
        }
    }
    
    MAX_SEARCH_DISTANCE = 5  # Distanza massima di ricerca in blocchi
    found_armor_stands = []
    
    try:
        await update.message.reply_text("🔍 **Ricerca armor stand migliorata**\nRicerca in corso...")
        
        # Prima fase: Ricerca generale degli armor stand nelle vicinanze
        player_pos = await get_player_position(minecraft_username, update, context)
        if not player_pos:
            await update.message.reply_text("❌ Impossibile ottenere la posizione del giocatore.")
            cleanup_hologram_data(context)
            return
            
        await update.message.reply_text(f"📍 Posizione giocatore: X={player_pos['x']:.1f}, Y={player_pos['y']:.1f}, Z={player_pos['z']:.1f}")
        
        # Cerca armor stand in un'area specifica attorno al giocatore
        nearby_armor_stands = await find_nearby_armor_stands(
            player_pos, MAX_SEARCH_DISTANCE, minecraft_username, update, context
        )
        
        if not nearby_armor_stands:
            await update.message.reply_text("❌ Nessun armor stand trovato nel raggio di 5 blocchi.")
            cleanup_hologram_data(context)
            return
            
        await update.message.reply_text(f"🎯 Trovati {len(nearby_armor_stands)} armor stand nelle vicinanze!")
        
        # Seconda fase: Determina orientamento per ogni armor stand trovato
        for i, armor_stand in enumerate(nearby_armor_stands):
            await update.message.reply_text(f"🧭 Analisi orientamento armor stand #{i+1}...")
            
            orientation_result = await determine_armor_stand_orientation(
                armor_stand, orientations, minecraft_username, update, context
            )
            
            if orientation_result:
                distance = calculate_distance_3d(player_pos, armor_stand)
                armor_stand.update({
                    'orientation': orientation_result,
                    'distance_from_player': distance
                })
                found_armor_stands.append(armor_stand)
        
        # Terza fase: Selezione del miglior armor stand
        if not found_armor_stands:
            await update.message.reply_text("❌ Nessun armor stand con orientamento valido trovato.")
            cleanup_hologram_data(context)
            return
            
        # Ordina per distanza (più vicino = migliore)
        found_armor_stands.sort(key=lambda x: x['distance_from_player'])
        best_armor_stand = found_armor_stands[0]
        
        # Mostra risultato
        orientation_info = best_armor_stand['orientation']
        await update.message.reply_text(
            f"✅ **Armor stand ottimale trovato!**\n"
            f"🧭 **Orientamento**: {orientation_info['direction'].capitalize()} ({orientation_info['angle']}°)\n"
            f"📍 **Posizione**: X={best_armor_stand['x']:.1f}, Y={best_armor_stand['y']:.1f}, Z={best_armor_stand['z']:.1f}\n"
            f"📏 **Distanza**: {best_armor_stand['distance_from_player']:.1f} blocchi\n"
            f"🎯 **Facing**: {orientation_info['expected_facing']}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Se ci sono più armor stand, mostra le opzioni
        if len(found_armor_stands) > 1:
            other_stands_info = []
            for i, stand in enumerate(found_armor_stands[1:4], 2):  # Mostra max 3 alternative
                ori = stand['orientation']
                other_stands_info.append(
                    f"{i}. Distanza: {stand['distance_from_player']:.1f}m, "
                    f"Facing: {ori['expected_facing']}"
                )
            
            if other_stands_info:
                await update.message.reply_text(
                    f"ℹ️ **Alternative trovate:**\n" + "\n".join(other_stands_info) +
                    "\n\n*Usando il più vicino per default*"
                )
        
        # Procedi con il paste usando il miglior armor stand
        await execute_hologram_paste(
            update, context,
            {
                'x': best_armor_stand['x'],
                'y': best_armor_stand['y'], 
                'z': best_armor_stand['z']
            },
            best_armor_stand['orientation']['direction'],
            minecraft_username
        )
        
    except Exception as e:
        logger.error(f"🔍❌ Errore durante rilevamento armor stand migliorato: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore durante il rilevamento: {html.escape(str(e))}")
        cleanup_hologram_data(context)


async def get_player_position(minecraft_username: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Ottiene la posizione precisa del giocatore"""
    try:
        # Pulisci i log
        await run_docker_command(["docker", "logs", "--tail", "1", CONTAINER], read_output=True, timeout=2)
        
        # Comando per ottenere posizione esatta
        pos_cmd = f"execute as {minecraft_username} at @s run tp @s ~ ~ ~0.001"
        await run_docker_command(["docker", "exec", CONTAINER, "send-command", pos_cmd], read_output=False)
        await asyncio.sleep(1.5)
        
        # Leggi i log
        log_output = await run_docker_command(["docker", "logs", "--tail", "10", CONTAINER], read_output=True, timeout=5)
        
        # Pattern più robusto per il teleport
        teleport_pattern = rf"Teleported {re.escape(minecraft_username)} to ([0-9\.\-]+),?\s*([0-9\.\-]+),?\s*([0-9\.\-]+)"
        matches = re.findall(teleport_pattern, log_output)
        
        if matches:
            x_str, y_str, z_str = matches[-1]
            return {
                "x": float(x_str),
                "y": float(y_str), 
                "z": float(z_str)
            }
        
        return None
        
    except Exception as e:
        logger.error(f"Errore ottenimento posizione giocatore: {e}")
        return None


async def find_nearby_armor_stands(player_pos: dict, max_distance: int, minecraft_username: str, 
                                 update: Update, context: ContextTypes.DEFAULT_TYPE) -> list:
    """
    Trova tutti gli armor stand nelle vicinanze del giocatore
    """
    found_stands = []
    
    try:
        # Griglia di ricerca attorno al giocatore
        search_offsets = [
            (0, 0, 0),     # Posizione giocatore
            (1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1),  # Cardinali
            (1, 0, 1), (-1, 0, 1), (1, 0, -1), (-1, 0, -1), # Diagonali
            (2, 0, 0), (-2, 0, 0), (0, 0, 2), (0, 0, -2),   # Più lontani
            (0, 1, 0), (0, -1, 0),  # Sopra/sotto
        ]
        
        for dx, dy, dz in search_offsets:
            search_x = player_pos['x'] + dx
            search_y = player_pos['y'] + dy
            search_z = player_pos['z'] + dz
            
            # Comando per testare se c'è un armor stand in questa posizione
            test_cmd = f"execute positioned {search_x} {search_y} {search_z} if entity @e[type=armor_stand,dx=0,dy=0,dz=0] run say ARMOR_STAND_FOUND_{search_x}_{search_y}_{search_z}"
            
            # Pulisci log prima del test
            await run_docker_command(["docker", "logs", "--tail", "1", CONTAINER], read_output=True, timeout=1)
            
            await run_docker_command(["docker", "exec", CONTAINER, "send-command", test_cmd], read_output=False)
            await asyncio.sleep(0.8)
            
            # Controlla i log per il messaggio di conferma
            log_output = await run_docker_command(["docker", "logs", "--tail", "5", CONTAINER], read_output=True, timeout=3)
            
            if f"ARMOR_STAND_FOUND_{search_x}_{search_y}_{search_z}" in log_output:
                distance = calculate_distance_3d(player_pos, {"x": search_x, "y": search_y, "z": search_z})
                if distance <= max_distance:
                    found_stands.append({
                        "x": search_x,
                        "y": search_y,
                        "z": search_z
                    })
                    logger.info(f"Armor stand trovato a: {search_x}, {search_y}, {search_z} (distanza: {distance:.1f})")
        
        return found_stands
        
    except Exception as e:
        logger.error(f"Errore ricerca armor stand: {e}")
        return []


async def determine_armor_stand_orientation(armor_stand: dict, orientations: dict, minecraft_username: str,
                                          update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
    """
    Determina l'orientamento preciso di un armor stand
    """
    try:
        for orientation_name, config in orientations.items():
            for ry_range in config['ry_ranges']:
                ry_min, ry_max = ry_range
                
                # Comando più preciso per testare orientamento
                test_cmd = (
                    f"execute positioned {armor_stand['x']} {armor_stand['y']} {armor_stand['z']} "
                    f"if entity @e[type=armor_stand,dx=0,dy=0,dz=0,rym={ry_min},ry={ry_max}] "
                    f"run say ORIENTATION_FOUND_{orientation_name}_{armor_stand['x']}_{armor_stand['y']}_{armor_stand['z']}"
                )
                
                # Pulisci log
                await run_docker_command(["docker", "logs", "--tail", "1", CONTAINER], read_output=True, timeout=1)
                
                await run_docker_command(["docker", "exec", CONTAINER, "send-command", test_cmd], read_output=False)
                await asyncio.sleep(0.8)
                
                # Controlla log
                log_output = await run_docker_command(["docker", "logs", "--tail", "5", CONTAINER], read_output=True, timeout=3)
                
                expected_message = f"ORIENTATION_FOUND_{orientation_name}_{armor_stand['x']}_{armor_stand['y']}_{armor_stand['z']}"
                if expected_message in log_output:
                    return config
        
        return None
        
    except Exception as e:
        logger.error(f"Errore determinazione orientamento: {e}")
        return None


def calculate_distance_3d(pos1: dict, pos2: dict) -> float:
    """Calcola la distanza 3D tra due posizioni"""
    dx = pos1['x'] - pos2['x']
    dy = pos1['y'] - pos2['y'] 
    dz = pos1['z'] - pos2['z']
    return (dx*dx + dy*dy + dz*dz) ** 0.5


def calculate_armor_stand_position_improved(player_coords: dict, armor_stand_coords: dict) -> dict:
    """
    Versione migliorata che usa le coordinate precise dell'armor stand
    invece di calcolarle dall'offset del teleport
    """
    # Ritorna direttamente le coordinate dell'armor stand trovato
    return {
        "x": armor_stand_coords["x"],
        "y": armor_stand_coords["y"], 
        "z": armor_stand_coords["z"]
    }


async def execute_hologram_paste(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                               armor_stand_coords: dict, orientation: str, minecraft_username: str):
    """
    Esegue il processo completo di paste hologram
    """
    structure_path = context.user_data.get("hologram_structure_path")
    structure_name = context.user_data.get("hologram_structure_name")
    
    if not structure_path or not os.path.exists(structure_path):
        await update.message.reply_text("❌ File struttura non trovato.")
        cleanup_hologram_data(context)
        return
    
    try:
        # Step 1: Conferma e preparazione
        coords_str = f"{armor_stand_coords['x']:.1f},{armor_stand_coords['y']:.1f},{armor_stand_coords['z']:.1f}"
        
        await update.message.reply_text(
            f"🏗️ **Preparazione Paste Hologram**\n"
            f"📁 Struttura: {structure_name}\n"
            f"📍 Coordinate: {coords_str}\n"
            f"🧭 Orientamento: {orientation.capitalize()}\n\n"
            f"⚠️ **ATTENZIONE**: Il server verrà arrestato per il backup e l'operazione!"
        )
        
        # Step 2: Backup del mondo
        await update.message.reply_text("💾 Creazione backup del mondo...")
        backup_success = await create_world_backup_for_paste(update, context)
        if not backup_success:
            await update.message.reply_text("❌ Backup fallito. Operazione annullata.")
            cleanup_hologram_data(context)
            return
        
        # Step 3: Arresta il server
        await update.message.reply_text("🛑 Arresto server per incollare struttura...")
        # Importa le funzioni necessarie da command_handlers
        from command_handlers import stop_server_command, start_server_command
        
        stopped = await stop_server_command(update, context, quiet=True)
        if not stopped:
            await update.message.reply_text("❌ Impossibile arrestare il server. Operazione annullata.")
            cleanup_hologram_data(context)
            return
        
        await update.message.reply_text("⏳ Attesa rilascio file...")
        await asyncio.sleep(5)
        
        # Step 4: Esegui lo script paste
        await update.message.reply_text("🏗️ Incollaggio struttura in corso...")
        paste_success = await execute_paste_structure_script(
            structure_path, coords_str, orientation, update, context
        )
        
        if paste_success:
            await update.message.reply_text("✅ Struttura incollata con successo!")
        else:
            await update.message.reply_text("⚠️ Incollaggio completato con avvisi (controlla i log).")
        
        # Step 5: Riavvia il server
        await update.message.reply_text("🚀 Riavvio server...")
        await start_server_command(update, context, quiet=True)
        await update.message.reply_text("✅ **Paste Hologram completato!**")
        
    except Exception as e:
        logger.error(f"🏗️❌ Errore durante paste hologram: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore durante l'operazione: {html.escape(str(e))}")
        
        # Riavvia il server in caso di errore
        try:
            from command_handlers import start_server_command
            await update.message.reply_text("🚀 Tentativo riavvio server di sicurezza...")
            await start_server_command(update, context, quiet=True)
        except Exception as restart_error:
            logger.error(f"Errore riavvio server di sicurezza: {restart_error}")
    
    finally:
        cleanup_hologram_data(context)


async def create_world_backup_for_paste(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Crea un backup del mondo specificatamente per paste hologram
    """
    try:
        world_dir_path = get_world_directory_path(WORLD_NAME)
        backups_storage = get_backups_storage_path()
        
        if not world_dir_path or not os.path.exists(world_dir_path):
            logger.error(f"Directory mondo '{WORLD_NAME}' non trovata per backup hologram.")
            return False
        
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_world_name = "".join(c if c.isalnum() else "_" for c in WORLD_NAME)
        archive_name_base = os.path.join(backups_storage, f"{safe_world_name}_hologram_backup_{timestamp}")
        
        await asyncio.to_thread(
            shutil.make_archive,
            base_name=archive_name_base,
            format='zip',
            root_dir=os.path.dirname(world_dir_path),
            base_dir=os.path.basename(world_dir_path)
        )
        
        final_archive_name = f"{archive_name_base}.zip"
        await update.message.reply_text(
            f"💾 Backup creato: {os.path.basename(final_archive_name)}"
        )
        return True
        
    except Exception as e:
        logger.error(f"💾❌ Errore backup hologram: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore backup: {html.escape(str(e))}")
        return False


async def execute_paste_structure_script(structure_path: str, coords_str: str, 
                                       orientation: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Esegue lo script pasteStructure.py
    """
    try:
        world_dir_path = get_world_directory_path(WORLD_NAME)
        if not world_dir_path:
            await update.message.reply_text("❌ Percorso mondo non trovato.")
            return False
        
        # Prepara comando per lo script
        script_path = "/app/importBuild/schem_to_mc_amulet/pasteStructure.py"  
        python_executable = "/app/importBuild/schem_to_mc_amulet/venv/bin/python"  
        
        command = [
            python_executable, script_path,
            world_dir_path,
            structure_path, 
            coords_str,
            "--orient", orientation,
            "--dimension", "overworld",
            "--mode", "origin",  # Usa origine della struttura
            "--verbose"
        ]
        
        logger.info(f"Esecuzione paste script: {' '.join(command)}")
        
        # Esegui lo script
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout_bytes, stderr_bytes = await process.communicate()
        stdout = stdout_bytes.decode().strip()
        stderr = stderr_bytes.decode().strip()
        
        # Log output per debugging
        if stdout:
            logger.info(f"Paste script stdout: {stdout}")
        if stderr:
            logger.warning(f"Paste script stderr: {stderr}")
        
        # Invia parte dell'output all'utente
        if stdout:
            # Prendi solo le ultime righe più importanti
            lines = stdout.split('\n')
            important_lines = [line for line in lines[-10:] if '✅' in line or '❌' in line or 'RIEPILOGO' in line]
            if important_lines:
                output_text = '\n'.join(important_lines)
                await update.message.reply_text(f"📋 Output script:\n<pre>{html.escape(output_text)}</pre>", parse_mode=ParseMode.HTML)
        
        success = process.returncode == 0
        if not success and stderr:
            await update.message.reply_text(f"⚠️ Script warnings:\n<pre>{html.escape(stderr[:500])}</pre>", parse_mode=ParseMode.HTML)
        
        return success
        
    except Exception as e:
        logger.error(f"🏗️❌ Errore esecuzione paste script: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore script: {html.escape(str(e))}")
        return False


def cleanup_hologram_data(context: ContextTypes.DEFAULT_TYPE):
    """
    Pulisce i dati temporanei del paste hologram
    """
    keys_to_remove = [
        "awaiting_hologram_structure",
        "hologram_structure_path", 
        "hologram_structure_name"
    ]
    
    for key in keys_to_remove:
        context.user_data.pop(key, None)
