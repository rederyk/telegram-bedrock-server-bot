import asyncio
import subprocess
import re
import os
import html
import tempfile
import shutil
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import get_logger
# Assuming these utilities will still be needed or moved later
# from docker_utils import run_docker_command
# from resource_pack_management import install_resource_pack_from_file, manage_world_resource_packs_json, ResourcePackError

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
