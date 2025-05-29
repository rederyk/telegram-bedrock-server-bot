import asyncio
import subprocess
import uuid
import re
import os
import html
import tempfile
import shutil
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import CONTAINER, get_logger, WORLD_NAME # Assicurati che WORLD_NAME sia definito
from user_management import get_minecraft_username
from docker_utils import run_docker_command
# from world_management import get_backups_storage_path, get_world_directory_path # Non usate direttamente qui

logger = get_logger(__name__)

# Definizione delle altre funzioni come paste_hologram_command_entry, handle_hologram_structure_upload, ecc.
# ... (codice esistente omesso per brevità, assumendo che sia presente)


async def paste_hologram_command_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Entry point for the paste hologram command.
    Starts by detecting an armor stand, then asks for the structure file if found.
    """
    uid = update.effective_user.id
    minecraft_username = get_minecraft_username(uid)
    if not minecraft_username:
        await update.message.reply_text("⚠️ Nome utente Minecraft non trovato. Per favore, impostalo prima con /setuser.")
        return

    # Start the armor stand detection
    await detect_armor_stand_v3(update, context, minecraft_username)


async def handle_hologram_structure_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, structure_file_path: str, original_filename: str):
    """
    Gestisce il caricamento del file struttura per paste hologram, DOPO che un armor stand è stato trovato.
    """
    uid = update.effective_user.id
    minecraft_username = get_minecraft_username(uid) # Anche se non usato direttamente qui, è buona prassi averlo se necessario

    context.user_data["hologram_structure_path"] = structure_file_path
    context.user_data["hologram_structure_name"] = original_filename

    armor_stand_coords = context.user_data.get("hologram_as_coords")
    orientation = context.user_data.get("hologram_as_orientation")

    if not armor_stand_coords or not orientation:
        logger.error("Armor stand details not found in context during structure upload for hologram.")
        await update.message.reply_text(
            "❌ Errore: Dettagli dell'armor stand non trovati. Riprova il comando /pastehologram."
        )
        cleanup_hologram_data(context)
        return

    await update.message.reply_text(
        f"📁 File '{original_filename}' ricevuto!"
    )

    await execute_hologram_paste(update, context, armor_stand_coords, orientation, get_minecraft_username(uid))


async def detect_armor_stand_v3(update: Update, context: ContextTypes.DEFAULT_TYPE, minecraft_username: str):
    """
    Rileva un armor stand di fronte al giocatore e ne determina l'orientamento cardinale ESATTO.
    Utilizza il teletrasporto del giocatore come segnale di conferma per test positivi,
    e controlla i log per "Execute subcommand if entity test failed" per test negativi.
    """
    await update.message.reply_text("🔍 Cerco armor stand di fronte a te e ne determino l'orientamento esatto...")

    # Definizioni degli orientamenti cardinali ESATTI con selettori Bedrock Edition
    # Usa rym=X,ry=X per testare orientamenti specifici (non range)
    orientation_checks = [
        {"name": "sud", "selector": "rym=0,ry=0", "angle": "0°"},        # Sud esatto (0°)
        {"name": "ovest", "selector": "rym=90,ry=90", "angle": "90°"},   # Ovest esatto (90°)
        {"name": "nord", "selector": "rym=180,ry=180", "angle": "180°"}, # Nord esatto (180°)
        {"name": "est", "selector": "rym=270,ry=270", "angle": "270°"},  # Est esatto (270°)
    ]

    detected_orientation_name = None
    armor_stand_coords = None

    for orientation_data in orientation_checks:
        current_orientation_selector = orientation_data["selector"]
        temp_orientation_name = orientation_data["name"]
        angle_display = orientation_data["angle"]

        # Comando per testare l'esistenza dell'armor stand con l'orientamento ESATTO
        test_cmd = (
            f"execute at {minecraft_username} positioned ^ ^ ^1 "
            f"if entity @e[type=armor_stand,dx=0,dy=0,dz=0,{current_orientation_selector}] "
            f"run tp {minecraft_username} ~ ~ ~"
        )

        logger.info(f"Testing orientation {temp_orientation_name} ({angle_display}) with command: {test_cmd}")

        # Pulisci i log recenti per evitare false positività
        await run_docker_command(["docker", "logs", "--tail", "3", CONTAINER], read_output=True, timeout=3)
        
        # Esegui il comando di test
        await run_docker_command(["docker", "exec", CONTAINER, "send-command", test_cmd], read_output=False)
        await asyncio.sleep(2)  # Attendi che il comando venga eseguito e loggato

        # Leggi i log per verificare il risultato del test
        log_output = await run_docker_command(["docker", "logs", "--tail", "15", CONTAINER], read_output=True, timeout=5)

        # Controlla prima se il test è fallito (negativo)
        if "Execute subcommand if entity test failed" in log_output:
            logger.debug(f"Test NEGATIVO per orientamento {temp_orientation_name} ({angle_display}) - Armor stand NON trovato con questo orientamento")
            continue  # Passa al prossimo orientamento

        # Controlla se il test è positivo (teletrasporto del player)
        elif f"Teleported {minecraft_username} to" in log_output or f"Teleported entity {minecraft_username}" in log_output:
            logger.info(f"Test POSITIVO per orientamento {temp_orientation_name} ({angle_display}) - Player teleport signal received")
            
            # Armor stand con l'orientamento ESATTO trovato! Ora otteniamo le sue coordinate precise.
            # Teletrasportiamo l'ARMOR STAND trovato su se stesso per loggare le sue coordinate.
            get_as_coords_cmd = (
                f"execute at {minecraft_username} positioned ^ ^ ^1 "
                f"run tp @e[type=armor_stand,dx=0,dy=0,dz=0,{current_orientation_selector},c=1] ~ ~ ~"
            )

            # Pulisci nuovamente i log prima di ottenere le coordinate dell'AS
            await run_docker_command(["docker", "logs", "--tail", "3", CONTAINER], read_output=True, timeout=3)
            await run_docker_command(["docker", "exec", CONTAINER, "send-command", get_as_coords_cmd], read_output=False)
            await asyncio.sleep(2)  # Attendi il teletrasporto dell'armor stand

            as_log_output = await run_docker_command(["docker", "logs", "--tail", "15", CONTAINER], read_output=True, timeout=5)
            
            # Estrai le coordinate dell'armor stand dal log
            coord_match = re.search(r"Teleported .*? to ([0-9\.\-]+)[,\s]+([0-9\.\-]+)[,\s]+([0-9\.\-]+)", as_log_output)

            if coord_match:
                x_str, y_str, z_str = coord_match.groups()
                armor_stand_coords = {"x": float(x_str), "y": float(y_str), "z": float(z_str)}
                detected_orientation_name = temp_orientation_name
                
                logger.info(f"✅ Armor stand trovato alle coordinate {armor_stand_coords} con orientamento ESATTO {detected_orientation_name} ({angle_display})")
                break  # Esci dal loop, abbiamo trovato l'armor stand e le sue info
            else:
                logger.warning(
                    f"Test positivo per orientamento {temp_orientation_name} ({angle_display}) "
                    f"ma impossibile ottenere le coordinate. Log AS: '{as_log_output[:200]}...'"
                )
                # Continua a ciclare, potrebbe essere un errore temporaneo
        else:
            logger.warning(f"Risultato AMBIGUO per orientamento {temp_orientation_name} ({angle_display}) - né test failed né teleport trovati nei log")
            logger.debug(f"Log output per debug: {log_output[:300]}")

    if armor_stand_coords and detected_orientation_name:
        context.user_data["hologram_as_coords"] = armor_stand_coords
        context.user_data["hologram_as_orientation"] = detected_orientation_name  
        context.user_data["awaiting_hologram_structure"] = True

        await update.message.reply_text(
            f"✅ **Armor Stand Rilevato con Successo!**\n"
            f"📍 Coordinate: {armor_stand_coords['x']:.1f}, {armor_stand_coords['y']:.1f}, {armor_stand_coords['z']:.1f}\n"
            f"🧭 Orientamento Rilevato: {detected_orientation_name.capitalize()} ({orientation_checks[[o['name'] for o in orientation_checks].index(detected_orientation_name)]['angle']})\n\n"
            "⬆️ Ora carica il file `.mcstructure` per l'ologramma."
        )
        return True
    else:
        await update.message.reply_text(
            "❌ **Nessun Armor Stand Trovato**\n"
            "Non è stato rilevato alcun armor stand con orientamento cardinale esatto "
            "(Sud 0°, Ovest 90°, Nord 180°, Est 270°) nel blocco di fronte a te.\n\n"
            "🔧 **Suggerimenti:**\n"
            "• Assicurati che l'armor stand sia piazzato esattamente nel blocco davanti a te\n"
            "• Verifica che l'armor stand sia orientato verso una direzione cardinale esatta\n"
            "• Prova a riorientare l'armor stand e riprova il comando"
        )
        cleanup_hologram_data(context)  # Pulisci i dati parziali se presenti
        return False


async def get_player_coords(minecraft_username: str):
    """Ottiene coordinate del player (questa funzione rimane utile per altri scopi, ma non è usata direttamente per le coordinate dell'AS nel nuovo flusso)"""
    try:
        cmd = f"tp {minecraft_username} ~ ~ ~"
        
        # Pulisci log prima del comando per evitare di leggere un vecchio output di teletrasporto
        await run_docker_command(["docker", "logs", "--tail", "1", CONTAINER], read_output=True, timeout=2)
        await run_docker_command(["docker", "exec", CONTAINER, "send-command", cmd], read_output=False)
        await asyncio.sleep(1.5) # Dai tempo al comando di essere processato e loggato
        
        log_output = await run_docker_command(["docker", "logs", "--tail", "10", CONTAINER], read_output=True, timeout=5)
        
        match = re.search(r"Teleported.*?to ([0-9\.\-]+)[,\s]+([0-9\.\-]+)[,\s]+([0-9\.\-]+)", log_output)
        if match:
            x, y, z = match.groups()
            return {"x": float(x), "y": float(y), "z": float(z)}
        
        logger.warning(f"Could not parse coordinates for {minecraft_username} from log: {log_output}")
        return None
        
    except Exception as e:
        logger.error(f"Errore durante l'ottenimento delle coordinate del player {minecraft_username}: {e}")
        return None




def cleanup_hologram_data(context: ContextTypes.DEFAULT_TYPE):
    """
    Pulisce i dati temporanei del paste hologram dalla user_data.
    """
    keys_to_remove = [
        "awaiting_hologram_structure",
        "hologram_structure_path",
        "hologram_structure_name",
        "hologram_as_coords",
        "hologram_as_orientation"
    ]
    for key in keys_to_remove:
        if key in context.user_data:
            del context.user_data[key]
    logger.debug("Hologram temporary data cleaned up.")

# ... (Il resto del codice come execute_hologram_paste, create_world_backup_for_paste, ecc. rimane invariato)
# Assicurati che queste funzioni siano definite nel tuo file.
# Per esempio, execute_hologram_paste:
async def execute_hologram_paste(update: Update, context: ContextTypes.DEFAULT_TYPE,
                               armor_stand_coords: dict, orientation: str, minecraft_username: str):
    # Implementazione di execute_hologram_paste come fornita...
    # (omessa qui per brevità, ma deve essere presente nel tuo script completo)
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
            f"📍 Coordinate Armor Stand: {coords_str}\n"
            f"🧭 Orientamento Struttura: {orientation.capitalize()}\n\n"
            f"⚠️ **ATTENZIONE**: Il server potrebbe essere arrestato per il backup e l'operazione!"
        )
        
        # Aggiungi un prompt di conferma esplicito prima di procedere con operazioni distruttive
        keyboard = [
            [InlineKeyboardButton("✅ Conferma e Procedi", callback_data="hologram_confirm_paste")],
            [InlineKeyboardButton("❌ Annulla", callback_data="hologram_cancel_paste")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Sei sicuro di voler procedere? Il mondo verrà backuppato e il server riavviato.",
            reply_markup=reply_markup
        )
        # Lo stato successivo sarà gestito da un callback_query_handler per 'hologram_confirm_paste'
        # o 'hologram_cancel_paste'. Qui memorizziamo temporaneamente i dati necessari.
        context.user_data['pending_hologram_action'] = {
            'armor_stand_coords': armor_stand_coords,
            'orientation': orientation,
            'minecraft_username': minecraft_username,
            'structure_path': structure_path, # Già in user_data
            'structure_name': structure_name  # Già in user_data
        }

    except Exception as e:
        logger.error(f"🏗️❌ Errore durante la preparazione di paste hologram: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore durante la preparazione dell'operazione: {html.escape(str(e))}")
        cleanup_hologram_data(context)



async def create_world_backup_for_paste(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # Implementazione di create_world_backup_for_paste...
    # (omessa qui per brevità, ma deve essere presente nel tuo script completo)
    # Assicurati che usi get_world_directory_path e get_backups_storage_path
    from world_management import get_world_directory_path, get_backups_storage_path 
    from datetime import datetime

    try:
        world_dir_path_obj = get_world_directory_path(WORLD_NAME) # Assume che WORLD_NAME sia globale o da config
        if not world_dir_path_obj or not os.path.exists(world_dir_path_obj):
            logger.error(f"Directory del mondo '{WORLD_NAME}' non trovata per il backup dell'ologramma.")
            # Se update è da un CallbackQuery, usa update.effective_message
            await update.effective_message.reply_text(f"❌ Directory del mondo '{WORLD_NAME}' non trovata.")
            return False
        
        world_dir_path = str(world_dir_path_obj) # shutil.make_archive preferisce stringhe

        backups_storage_obj = get_backups_storage_path()
        if not os.path.exists(backups_storage_obj):
            os.makedirs(backups_storage_obj) # Crea la directory di backup se non esiste
        
        backups_storage = str(backups_storage_obj)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_world_name = "".join(c if c.isalnum() else "_" for c in WORLD_NAME)
        archive_name_base = os.path.join(backups_storage, f"{safe_world_name}_hologram_paste_backup_{timestamp}")

        # Esegui shutil.make_archive in un thread separato per non bloccare asyncio
        await asyncio.to_thread(
            shutil.make_archive,
            base_name=archive_name_base,
            format='zip', # o 'gztar'
            root_dir=os.path.dirname(world_dir_path),
            base_dir=os.path.basename(world_dir_path)
        )

        final_archive_name = f"{archive_name_base}.zip" # o '.tar.gz' se usi gztar
        # Se update è da un CallbackQuery, usa update.effective_message
        await update.effective_message.reply_text(
            f"✅ Backup del mondo creato con successo: {os.path.basename(final_archive_name)}"
        )
        logger.info(f"Backup per hologram paste creato: {final_archive_name}")
        return True

    except Exception as e:
        logger.error(f"💾❌ Errore durante la creazione del backup per hologram paste: {e}", exc_info=True)
        # Se update è da un CallbackQuery, usa update.effective_message
        await update.effective_message.reply_text(f"❌ Errore durante la creazione del backup: {html.escape(str(e))}")
        return False

async def execute_paste_structure_script(structure_path: str, coords_str: str,
                                       orientation: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    from world_management import get_world_directory_path
    try:
        world_dir_path_obj = get_world_directory_path(WORLD_NAME) 
        if not world_dir_path_obj or not os.path.exists(world_dir_path_obj):
            logger.error(f"Directory del mondo '{WORLD_NAME}' non trovata per l'operazione paste.")
            await update.effective_message.reply_text(f"❌ Directory del mondo '{WORLD_NAME}' non trovata.")
            return False
        world_dir_path = str(world_dir_path_obj)

        script_path = "/app/importBuild/schem_to_mc_amulet/pasteStructure.py" 
        python_executable = "/app/importBuild/schem_to_mc_amulet/venv/bin/python"

        command = [
            python_executable, script_path,
            world_dir_path,
            structure_path, 
            coords_str,     
            "--orient", orientation.lower(), 
            "--dimension", "overworld", 
            "--mode", "origin", 
            "--verbose" 
        ]

        logger.info(f"Esecuzione dello script pasteStructure: {' '.join(command)}")

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout_bytes, stderr_bytes = await process.communicate()
        
        stdout = stdout_bytes.decode('utf-8', errors='replace').strip()
        stderr = stderr_bytes.decode('utf-8', errors='replace').strip()

        if stdout:
            logger.info(f"Output stdout dello script pasteStructure:\n{stdout}")
        if stderr:
            logger.warning(f"Output stderr dello script pasteStructure:\n{stderr}")

        output_summary = "Risultato dello script di incollaggio:\n"
        if stdout:
            summary_lines = stdout.split('\n')
            important_output_lines = [line for line in summary_lines if 'RIEPILOGO' in line or '✅' in line or '❌' in line or 'completat' in line.lower()]
            if not important_output_lines: 
                important_output_lines = summary_lines[-10:]
            
            # FIX: Pre-calculate the string with the newline character
            joined_important_output = '\n'.join(important_output_lines)
            escaped_important_output = html.escape(joined_important_output)
            output_summary += f"Console Output (ultime righe):\n<pre>{escaped_important_output}</pre>\n"
        
        if stderr:
            output_summary += f"Errori/Avvisi:\n<pre>{html.escape(stderr[:1000])}</pre>"

        if not stdout and not stderr:
            output_summary += "Lo script non ha prodotto output."
            
        await update.effective_message.reply_text(output_summary, parse_mode=ParseMode.HTML)

        if process.returncode != 0:
            logger.error(f"Lo script pasteStructure è terminato con codice d'errore {process.returncode}.")
            return False 
        
        return True

    except FileNotFoundError:
        logger.error(f"Errore: L'eseguibile Python '{python_executable}' o lo script '{script_path}' non sono stati trovati.")
        await update.effective_message.reply_text(f"❌ Errore critico: File necessari per l'incollaggio non trovati sul server.")
        return False
    except Exception as e:
        logger.error(f"🏗️❌ Errore durante l'esecuzione dello script pasteStructure: {e}", exc_info=True)
        await update.effective_message.reply_text(f"❌ Errore durante l'esecuzione dello script di incollaggio: {html.escape(str(e))}")
        return False