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

from config import CONTAINER, get_logger, WORLD_NAME
from user_management import get_minecraft_username
from docker_utils import run_docker_command
from world_management import get_backups_storage_path, get_world_directory_path
# Assuming these command handlers will be imported or called from here
# from command_handlers import stop_server_command, start_server_command

logger = get_logger(__name__)


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

    # Assuming save_location is in user_management or a shared utility
    from user_management import save_location
    save_location(uid, location_name, coords)
    await update.message.reply_text(
        f"✅ Posizione armor stand salvata come '{location_name}'!\n"
        f"📍 Coordinate: X={coords['x']:.1f}, Y={coords['y']:.1f}, Z={coords['z']:.1f}\n"
        f"🧭 Orientamento: {armor_stand_data['direction']}"
    )


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
