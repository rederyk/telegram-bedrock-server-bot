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
from world_management import get_backups_storage_path
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
        current_input_file = os.path.join(processing_dir, original_filename)
        shutil.copy(downloaded_file_path, current_input_file)

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


        # --- Step 2: Conversion to .mcstructure (if needed) ---
        await update.message.reply_text("🔄 Converting files to .mcstructure format (if necessary)...")
        mcstructure_files = []
        for file_to_convert_path in split_output_files:
            if file_to_convert_path.lower().endswith(".mcstructure"):
                mcstructure_files.append(file_to_convert_path)
                logger.info(f"File {file_to_convert_path} is already .mcstructure.")
                await update.message.reply_text(f"ℹ️ {Path(file_to_convert_path).name} is already .mcstructure.")
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
                        await update.message.reply_text(f"❌ Failed to find/determine .mcstructure output for {Path(file_to_convert_path).name}.")
                        logger.error(f"Could not determine output for {file_to_convert_path} from convert2mc.py stdout: {convert_stdout}")
            else:
                logger.warning(f"Skipping unknown file type from split: {file_to_convert_path}")

        if not mcstructure_files:
            await update.message.reply_text("❌ No .mcstructure files to process after conversion step.")
            try:
                shutil.rmtree(processing_dir)
                logger.info(f"Cleaned up temporary directory: {processing_dir}")
            except Exception as e:
                logger.error(f"Error cleaning up temp directory {processing_dir}: {e}", exc_info=True)
            return

        # --- Step 3: Ask for Opacity ---
        await update.message.reply_text("🎨 Quale opacità desideri per il resource pack?")

        context.user_data["awaiting_structura_opacity"] = True
        context.user_data["structura_mcstructure_files"] = mcstructure_files
        context.user_data["structura_processing_dir"] = processing_dir

        buttons = [
            [InlineKeyboardButton("30%", callback_data="structura_opacity:30")],
            [InlineKeyboardButton("50%", callback_data="structura_opacity:50")],
            [InlineKeyboardButton("80%", callback_data="structura_opacity:80")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        await update.message.reply_text(
            "Scegli un'opacità predefinita o invia un numero tra 1 e 100:",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Unhandled error in structure wizard: {e}", exc_info=True)
        await update.message.reply_text(f"🆘 An critical error occurred in the wizard: {html.escape(str(e))}")
        try:
            if 'processing_dir' in locals() and os.path.exists(processing_dir):
                 shutil.rmtree(processing_dir)
                 logger.info(f"Cleaned up temporary directory: {processing_dir}")
        except Exception as cleanup_e:
            logger.error(f"Error cleaning up temp directory {processing_dir} after error: {cleanup_e}", exc_info=True)


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
    if reply_target:
        await reply_target.reply_text(f"📦 Creazione .mcpack con opacità {opacity_value}%...")
    else:
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
            original_update = next_action_data.get("update")
            original_context_args = next_action_data.get("args", []) # Store original args if any

            if original_update is None: # Should not happen if logic is correct
                logger.error("next_action_data missing original_update")
                await update.message.reply_text("Errore interno, azione successiva non chiara.")
                return

            if action_type == "menu":
                await menu_command(original_update, context)
            elif action_type == "give":
                await give_direct_command(original_update, context)
            elif action_type == "tp":
                await tp_direct_command(original_update, context)
            elif action_type == "weather":
                await weather_direct_command(original_update, context)
            elif action_type == "saveloc":
                await saveloc_command(original_update, context)
            elif action_type == "handle_document_wizard":
                logger.warning("Re-triggering wizard after username prompt - this path needs careful review.")
                pass
            else:
                await update.message.reply_text("Ora puoi usare i comandi che richiedono l'username (es. /menu).")
        else:
            await update.message.reply_text("Ora puoi usare i comandi che richiedono l'username (es. /menu).")
        return

    minecraft_username = get_minecraft_username(uid)
    if not minecraft_username and not context.user_data.get("awaiting_mc_username"):
        pass

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
        if not minecraft_username:
             await update.message.reply_text("Username Minecraft non impostato. Non posso salvare la posizione.")
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
            
            if not minecraft_username:
                await update.message.reply_text("Username Minecraft non impostato.")
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
        except asyncio.TimeoutError:
            await update.message.reply_text("Timeout eseguendo il comando give.")
        except subprocess.CalledProcessError as e:
            await update.message.reply_text(f"Errore dal server Minecraft: {e.stderr or e.output or e}")
        except Exception as e:
            logger.error(
                f"Errore imprevisto in handle_message (give quantity): {e}", exc_info=True)
            await update.message.reply_text(f"Errore imprevisto: {e}")
        finally:
            context.user_data.pop("selected_item_for_give", None)
            context.user_data.pop("awaiting_item_quantity", None)
        return

    # Gestione nuova posizione resource pack
    if context.user_data.get("awaiting_rp_new_position"):
        pack_uuid_to_move = context.user_data.pop(
            "awaiting_rp_new_position", None)
        if not pack_uuid_to_move:
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
            context.user_data["awaiting_rp_new_position"] = pack_uuid_to_move # Restore if input is invalid
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
        else:
            try:
                x, y, z = map(float, parts)
                if not minecraft_username:
                    await update.message.reply_text("Username Minecraft non impostato.")
                    return
                cmd_text = f"tp {minecraft_username} {x} {y} {z}"
                docker_cmd_args = ["docker", "exec",
                                   CONTAINER, "send-command", cmd_text]
                await run_docker_command(docker_cmd_args, read_output=False)
                await update.message.reply_text(f"Comando eseguito: /tp {minecraft_username} {x} {y} {z}")
            except ValueError as e:
                await update.message.reply_text(
                    "Le coordinate devono essere numeri validi (es. 100 64.5 -200). Riprova o /menu, /tp."
                )
            except asyncio.TimeoutError:
                await update.message.reply_text("Timeout eseguendo il comando teleport.")
            except subprocess.CalledProcessError as e:
                await update.message.reply_text(f"Errore dal server Minecraft: {e.stderr or e.output or e}")
            except Exception as e:
                logger.error(
                    f"Errore imprevisto in handle_message (tp coords): {e}", exc_info=True)
                await update.message.reply_text(f"Errore imprevisto: {e}")
            finally:
                context.user_data.pop("awaiting_tp_coords_input", None)
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

    # Centralized Minecraft username check for most actions
    # Actions that DON'T require username upfront:
    # - edit_username (it's for setting/changing it)
    # - download_backup_file (doesn't interact with MC server directly)
    # - rp_action:cancel_manage, rp_action:cancel_edit (simple cancellations)
    actions_not_requiring_mc_username = [
        "edit_username", "download_backup_file:",
        "rp_action:cancel_manage", "rp_action:cancel_edit"
    ]
    requires_mc_username = not any(data.startswith(prefix) or data == prefix for prefix in actions_not_requiring_mc_username)

    minecraft_username = get_minecraft_username(uid)
    if requires_mc_username and not minecraft_username:
        context.user_data["awaiting_mc_username"] = True
        # Store the callback data so we can resume after username input
        context.user_data["next_action_data"] = {"type": "callback", "data": data, "update": update} # Storing update might be too much
        await query.edit_message_text(
            "Il tuo username Minecraft non è impostato. Per favore, invialo in chat. "
            "L'azione verrà ripresa automaticamente."
        )
        return

    actions_requiring_container = [
        "give_item_select:", "tp_player:", "tp_coords_input", "weather_set:",
        "tp_saved:", "menu_give", "menu_tp", "menu_weather"
    ]
    is_action_requiring_container = any(data.startswith(
        action_prefix) for action_prefix in actions_requiring_container)

    if not CONTAINER and is_action_requiring_container:
        # Allow delete_location and edit_username even if CONTAINER is not set, as they are user data ops
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
            online_players = await get_online_players_from_server() # Requires CONTAINER
            buttons = []
            if online_players:
                buttons.extend([
                    InlineKeyboardButton(p, callback_data=f"tp_player:{p}")
                    for p in online_players
                ])
            buttons.append(InlineKeyboardButton(
                "📍 Inserisci coordinate", callback_data="tp_coords_input"))
            user_locs = get_locations(uid)
            for name_loc in user_locs: # Changed from 'name' to 'name_loc' to avoid conflict
                buttons.append(InlineKeyboardButton(
                    f"📌 {name_loc}", callback_data=f"tp_saved:{name_loc}"))

            if not buttons: # Should always have "Inserisci coordinate"
                 await query.edit_message_text(
                    "Nessun giocatore online e nessuna posizione salvata. "
                    "Puoi solo inserire le coordinate manualmente.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📍 Inserisci coordinate", callback_data="tp_coords_input")]])
                )
                 return

            keyboard_layout = [buttons[i:i+2]
                               for i in range(0, len(buttons), 2)]
            markup = InlineKeyboardMarkup(keyboard_layout)
            text_reply = "Scegli una destinazione:"
            if not online_players and CONTAINER: # Only mention if container is set but no players
                text_reply = "Nessun giocatore online.\nScegli tra posizioni salvate o coordinate:"
            elif not CONTAINER: # If container not set, can't get players
                 text_reply = ("Impossibile ottenere lista giocatori (CONTAINER non settato).\n"
                              "Scegli tra posizioni salvate o coordinate.")
            await query.edit_message_text(text_reply, reply_markup=markup)


        elif data.startswith("tp_saved:"):
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

        elif data == "tp_coords_input":
            context.user_data["awaiting_tp_coords_input"] = True
            await query.edit_message_text("Inserisci le coordinate nel formato: `x y z` (es. `100 64 -200`)")

        elif data.startswith("tp_player:"):
            target_player = data.split(":", 1)[1]
            cmd_text = f"tp {minecraft_username} {target_player}"
            docker_cmd_args = ["docker", "exec",
                               CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await query.edit_message_text(f"Teleport verso {target_player} eseguito!")

        elif data == "menu_weather":
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

        elif data.startswith("weather_set:"):
            weather_condition = data.split(":", 1)[1]
            cmd_text = f"weather {weather_condition}"
            docker_cmd_args = ["docker", "exec",
                               CONTAINER, "send-command", cmd_text]
            await run_docker_command(docker_cmd_args, read_output=False)
            await query.edit_message_text(f"Meteo impostato su: {weather_condition.capitalize()}")

        elif data.startswith("download_backup_file:"):
            backup_filename_from_callback = data.split(":", 1)[1]
            backups_dir = get_backups_storage_path()
            backup_file_path = os.path.join(
                backups_dir, backup_filename_from_callback)
            logger.info(
                f"Tentativo di scaricare il file di backup da: {backup_file_path} (richiesto da callback: {data})")

            if os.path.exists(backup_file_path):
                try:
                    original_message_text = query.message.text
                    await query.edit_message_text(f"{original_message_text}\n\n⏳ Preparazione invio di '{html.escape(backup_filename_from_callback)}'...")

                    with open(backup_file_path, "rb") as backup_file:
                        await context.bot.send_document(
                            chat_id=query.message.chat_id,
                            document=backup_file,
                            filename=os.path.basename(backup_file_path),
                            caption=f"Backup del mondo: {os.path.basename(backup_file_path)}"
                        )
                    await query.message.reply_text(f"✅ File '{html.escape(backup_filename_from_callback)}' inviato!")
                except Exception as e:
                    logger.error(
                        f"Errore inviando il file di backup '{backup_file_path}': {e}", exc_info=True)
                    # Try to restore original message if sending failed before it was modified too much
                    await query.edit_message_text(original_message_text) # Restore buttons
                    await query.message.reply_text(f"⚠️ Impossibile inviare il file di backup '{html.escape(backup_filename_from_callback)}': {e}")
            else:
                logger.warning(
                    f"File di backup non trovato per il download: {backup_file_path}")
                await query.edit_message_text(f"⚠️ File di backup non trovato: <code>{html.escape(backup_filename_from_callback)}</code>. Potrebbe essere stato spostato o cancellato.", parse_mode=ParseMode.HTML)

        elif data.startswith("rp_manage:"):
            pack_uuid = data.split(":", 1)[1]
            try:
                active_packs_details = await asyncio.to_thread(get_world_active_packs_with_details, WORLD_NAME)
                pack_details = next(
                    (p for p in active_packs_details if p['uuid'] == pack_uuid), None)
                pack_name = pack_details.get(
                    'name', 'Nome Sconosciuto') if pack_details else 'Nome Sconosciuto'
            except Exception:
                pack_name = 'Nome Sconosciuto'

            buttons = [
                [InlineKeyboardButton(
                    "🗑️ Elimina", callback_data=f"rp_action:delete:{pack_uuid}")],
                [InlineKeyboardButton(
                    "↕️ Sposta", callback_data=f"rp_action:move:{pack_uuid})")],
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
            pack_uuid_to_delete = data.split(":", 2)[2]
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
            pack_uuid_to_move = data.split(":", 2)[2]
            context.user_data["awaiting_rp_new_position"] = pack_uuid_to_move
            await query.edit_message_text(
                "Inserisci la nuova posizione (numero) per questo resource pack nella lista attiva.\n"
                "La posizione 1 è la più bassa priorità, l'ultima è la più alta."
            )

        elif data == "rp_action:cancel_manage" or data == "rp_action:cancel_edit": # Added cancel_edit
            await query.edit_message_text("Gestione resource pack annullata.")
            # Optionally, re-display the list of packs if coming from rp_manage
            # For simplicity, just confirm cancellation.

        elif data.startswith("structura_opacity:"):
            try:
                opacity_value = int(data.split(":", 1)[1])
                if 1 <= opacity_value <= 100:
                    await handle_structura_opacity_input(update, context, opacity_value)
                else:
                    await query.edit_message_text("Valore di opacità non valido. Scegli tra i bottoni o invia un numero tra 1 e 100.")
            except ValueError:
                 await query.edit_message_text("Valore di opacità non valido. Scegli tra i bottoni o invia un numero tra 1 e 100.")


        else:
            await query.edit_message_text("Azione non riconosciuta o scaduta.")

    except asyncio.TimeoutError:
        await query.edit_message_text("Timeout eseguendo l'azione richiesta. Riprova.")
    except subprocess.CalledProcessError as e:
        error_detail = e.stderr or e.output or str(e)
        await query.edit_message_text(f"Errore dal server Minecraft: {error_detail}. Riprova o contatta un admin.")
        logger.error(
            f"CalledProcessError in callback_query_handler for data '{data}': {e}", exc_info=True)
    except ValueError as e: # Catch general ValueErrors
        await query.edit_message_text(f"Errore nei dati forniti: {str(e)}")
    except Exception as e:
        logger.error(
            f"Errore imprevisto in callback_query_handler for data '{data}': {e}", exc_info=True)
        await query.edit_message_text("Si è verificato un errore imprevisto. Riprova più tardi.")


async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming document messages."""
    uid = update.effective_user.id
    if not update.message or not update.message.document:
        logger.warning("handle_document_message: No message or document found.")
        await update.message.reply_text("Nessun documento trovato nel messaggio.")
        return
        
    document = update.message.document
    original_filename = document.file_name

    if not is_user_authenticated(uid):
        await update.message.reply_text("Devi prima effettuare il /login.")
        return

    # Check for structure file wizard
    if original_filename and (original_filename.lower().endswith(".schematic") or original_filename.lower().endswith(".mcstructure")):
        minecraft_username = get_minecraft_username(uid)
        if not minecraft_username:
            context.user_data["awaiting_mc_username"] = True
            # Store necessary info to resume wizard after username input
            # This is complex because we need the file itself.
            # For now, let's just ask for username and user has to re-upload.
            # A better way would be to download the file, then ask for username if needed, then proceed.
            # Or, make the wizard itself handle the username prompt if it needs it for some step.
            # Given the wizard primarily calls external scripts, username might not be needed by the wizard directly.
            # Let's assume wizard can proceed without MC username for now, unless a script specifically needs it.
            # The scripts themselves don't seem to take username as an argument based on command_handlers.
            await update.message.reply_text(
                "Per alcune funzionalità avanzate, è utile avere il tuo username Minecraft. "
                "Puoi impostarlo con /edituser o il bot potrebbe richiederlo se necessario.\n"
                "Procedo con l'elaborazione del file..."
            )
            # Fall through to wizard, it will run.

        # Download the file to a temporary path first
        with tempfile.TemporaryDirectory(prefix="tgbot_download_") as temp_dir_for_download:
            downloaded_file_path = os.path.join(temp_dir_for_download, original_filename)
            try:
                new_file = await context.bot.get_file(document.file_id)
                await new_file.download_to_drive(custom_path=downloaded_file_path)
                logger.info(f"Document '{original_filename}' downloaded to temporary path: {downloaded_file_path} for wizard.")
                
                # Call the wizard function
                await process_structure_file_wizard(downloaded_file_path, original_filename, update, context)
            except Exception as e:
                logger.error(f"Error downloading file for wizard or during wizard prep: {e}", exc_info=True)
                await update.message.reply_text(f"❌ Error preparing file for processing: {html.escape(str(e))}")
        return # Wizard handled this document

    # Existing resource pack logic
    if not WORLD_NAME:
        await update.message.reply_text("Errore: WORLD_NAME non configurato. Impossibile aggiungere resource pack.")
        return

    if not (original_filename.lower().endswith(".zip") or original_filename.lower().endswith(".mcpack")):
        await update.message.reply_text(
            f"Formato file non supportato: {original_filename}. "
            "Invia un file .zip o .mcpack come resource pack, oppure .schematic/.mcstructure per il wizard."
        )
        return

    await update.message.reply_text(f"Ricevuto file '{original_filename}'. Tentativo di installazione come resource pack...")

    try:
        with tempfile.TemporaryDirectory(prefix="tgbot_rp_") as temp_dir:
            temp_file_path = os.path.join(temp_dir, original_filename)
            new_file = await context.bot.get_file(document.file_id)
            await new_file.download_to_drive(custom_path=temp_file_path)
            logger.info(
                f"Resource pack document downloaded to temporary path: {temp_file_path}")

            installed_pack_path, pack_uuid, pack_version, pack_name = install_resource_pack_from_file(
                temp_file_path, original_filename # WORLD_NAME is used internally by this func
            )
            logger.info(f"Resource pack installed: {pack_name} ({pack_uuid})")

            manage_world_resource_packs_json(
                WORLD_NAME,
                pack_uuid_to_add=pack_uuid,
                pack_version_to_add=pack_version,
                add_at_beginning=True # New packs get higher priority
            )
            logger.info(
                f"Resource pack {pack_name} ({pack_uuid}) activated for world {WORLD_NAME}.")

            await update.message.reply_text(
                f"✅ Resource pack '{pack_name}' installato e attivato per il mondo '{WORLD_NAME}'.\n"
                "ℹ️ Per applicare le modifiche, esegui il comando: /restartserver\n"
                "ℹ️ Per eliminare vecchie strutture che possono causare rallentamenti, esegui il comando: /editresourcepack"
            )
    except ResourcePackError as e:
        logger.error(
            f"Errore durante l'installazione/attivazione del resource pack: {e}")
        await update.message.reply_text(f"⚠️ Errore durante l'installazione del resource pack: {e}")
    except Exception as e:
        logger.error(
            f"Errore imprevisto in handle_document_message (resource pack): {e}", exc_info=True)
        await update.message.reply_text(f"❌ Si è verificato un errore imprevisto durante la gestione del documento: {e}")
