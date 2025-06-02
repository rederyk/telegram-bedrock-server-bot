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
from world_management import get_world_directory_path # Import aggiunto
from armor_stand_handlers import get_armor_stand_data_from_script # Importa la nuova funzione
# from world_management import get_backups_storage_path # Non usate direttamente qui
from server_handlers import stop_server_command, start_server_command # Import server control functions

logger = get_logger(__name__)

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2."""
    # Chars to escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
    # Note: \ must be escaped first.
    escape_chars = r'([_*\[\]()~`>#\+\-=|{}\.!\\])'
    return re.sub(escape_chars, r'\\\1', text)

# Definizione delle altre funzioni come paste_hologram_command_entry, handle_hologram_structure_upload, ecc.
# ... (codice esistente omesso per brevità, assumendo che sia presente)


async def paste_hologram_command_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Entry point for the paste hologram command.
    Starts by detecting an armor stand, then asks for the structure file if found.
    """
    cleanup_hologram_data(context)
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
    Rileva armor stand nel chunk del giocatore usando search_armorstand.py,
    filtra per un singolo armor stand con orientamento cardinale esatto (Nord, Sud, Est, Ovest),
    e ne salva coordinate e orientamento (la direzione in cui guarda l'AS).
    """
    await update.message.reply_text("🔍 Cerco armor stand con orientamento cardinale nel tuo chunk...")

    # Step 1: Ottenere coordinate del giocatore
    logger.info(f"🔍 Iniziando rilevamento armor stand per utente: {minecraft_username}")
    
    player_coords_dict = await get_player_coords(minecraft_username)
    if not player_coords_dict:
        logger.error(f"❌ Impossibile ottenere coordinate per {minecraft_username}")
        await update.message.reply_text("❌ Impossibile ottenere le coordinate del giocatore. Riprova.")
        cleanup_hologram_data(context)
        return False

    # FIX: Formato coordinate per lo script - deve essere senza decimali come nel test manuale
    player_coords_str = f"{int(player_coords_dict['x'])},{int(player_coords_dict['y'])},{int(player_coords_dict['z'])}"
    logger.info(f"📍 Coordinate giocatore originali: {player_coords_dict['x']:.2f},{player_coords_dict['y']:.2f},{player_coords_dict['z']:.2f}")
    logger.info(f"📍 Coordinate inviate allo script: {player_coords_str}")
    
    await update.message.reply_text(f"⏳ Esecuzione analisi del chunk in corso (può richiedere qualche secondo)...")

    # Step 2: Eseguire lo script di ricerca armor stand con logging dettagliato
    logger.info(f"🔧 Chiamando get_armor_stand_data_from_script con WORLD_NAME='{WORLD_NAME}' e coords='{player_coords_str}'")
    
    try:
        all_found_stands_data = await get_armor_stand_data_from_script(WORLD_NAME, player_coords_str)
        
        # Log dettagliato del risultato
        if all_found_stands_data is None:
            logger.error("❌ get_armor_stand_data_from_script ha restituito None - errore critico nello script")
            await update.message.reply_text(
                "❌ **Errore Critico Script**\n"
                "Lo script di ricerca armor stand ha riscontrato un errore grave.\n\n"
                "🔧 **Dettagli Tecnici:**\n"
                "• get_armor_stand_data_from_script ha restituito None\n"
                "• Controlla i log del server per errori Python/script\n"
                "• Verifica che lo script search_armorstand.py sia presente e funzionante"
            )
            cleanup_hologram_data(context)
            return False
            
        elif isinstance(all_found_stands_data, list) and len(all_found_stands_data) == 0:
            logger.warning("📋 Script eseguito ma lista vuota - possibile problema nel parsing dei risultati")
            
            # TEMPORARY DEBUG: Proviamo ad eseguire lo script direttamente per vedere l'output raw
            logger.info("🔧 DEBUG: Eseguendo script direttamente per debug...")
            try:
                from world_management import get_world_directory_path
                world_dir_path_obj = get_world_directory_path(WORLD_NAME)
                world_dir_path = str(world_dir_path_obj)
                
                script_path = "/app/importBuild/schem_to_mc_amulet/search_armorstand.py"
                python_executable = "/app/importBuild/schem_to_mc_amulet/venv/bin/python"
                
                debug_command = [python_executable, script_path, world_dir_path, player_coords_str]
                logger.info(f"🔧 DEBUG command: {' '.join(debug_command)}")
                
                process = await asyncio.create_subprocess_exec(
                    *debug_command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd="/app/importBuild/schem_to_mc_amulet"
                )
                
                stdout_bytes, stderr_bytes = await process.communicate()
                stdout = stdout_bytes.decode('utf-8', errors='replace').strip()
                stderr = stderr_bytes.decode('utf-8', errors='replace').strip()
                
                logger.info(f"🔧 DEBUG Script stdout:\n{stdout}")
                if stderr:
                    logger.warning(f"🔧 DEBUG Script stderr:\n{stderr}")
                
                # Cerca nel output se c'è menzione di armor stand
                if "minecraft:armor_stand" in stdout:
                    logger.error("❌ SCRIPT TROVA ARMOR STAND MA get_armor_stand_data_from_script NON LO RESTITUISCE!")
                    await update.message.reply_text(
                        "❌ **Bug nel Parsing dei Dati**\n"
                        "Lo script trova l'armor stand ma la funzione di parsing non riesce a processare i dati.\n\n"
                        "🔧 **Armor Stand rilevato manualmente:**\n"
                        "• Controlla la funzione get_armor_stand_data_from_script\n"
                        "• Possibile problema nel parsing JSON o nel formato output"
                    )
                else:
                    await update.message.reply_text(
                        "❌ **Nessun Armor Stand nel Chunk**\n"
                        f"Lo script ha analizzato il chunk alle coordinate {player_coords_str} "
                        f"ma non ha trovato armor stand.\n\n"
                        "🔧 **Suggerimenti:**\n"
                        "• Assicurati di essere nello stesso chunk dell'armor stand\n"
                        "• L'armor stand deve essere visibile e non nascosto\n"
                        "• Prova a muoverti leggermente e riprova il comando"
                    )
                
            except Exception as debug_e:
                logger.error(f"💥 Errore durante debug diretto dello script: {debug_e}")
                await update.message.reply_text(
                    "❌ **Errore di Debug**\n"
                    "Non è possibile eseguire il debug diretto dello script.\n"
                    "Controlla i log per errori dettagliati."
                )
            
            cleanup_hologram_data(context)
            return False
            
        else:
            logger.info(f"📋 Script eseguito con successo. Trovati {len(all_found_stands_data)} elementi totali")
            # Log di tutti gli elementi trovati per debug
            for i, stand_data in enumerate(all_found_stands_data):
                logger.info(f"  [{i}] Elemento trovato: ID={stand_data.get('id', 'N/A')}, "
                           f"Position={stand_data.get('position', 'N/A')}, "
                           f"Direction={stand_data.get('direction', 'N/A')}, "
                           f"Yaw={stand_data.get('yaw', 'N/A')}")

    except Exception as e:
        logger.error(f"💥 Eccezione durante chiamata get_armor_stand_data_from_script: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ **Errore Durante Esecuzione Script**\n"
            f"Si è verificata un'eccezione durante l'esecuzione dello script di ricerca.\n\n"
            f"🔧 **Dettagli Errore:**\n"
            f"• Tipo: {type(e).__name__}\n"
            f"• Messaggio: {str(e)[:200]}...\n"
            f"• Controlla i log completi per stack trace"
        )
        cleanup_hologram_data(context)
        return False

    # Step 3: Filtrare armor stand con orientamento cardinale
    logger.info("🔍 Filtrando armor stand per orientamento cardinale...")
    
    cardinal_armor_stands = []
    cardinal_orientations_text = ["Nord", "Sud", "Est", "Ovest"]

    for i, stand_data in enumerate(all_found_stands_data):
        logger.debug(f"  Analizzando elemento [{i}]: {stand_data}")
        
        # Verifica che sia un armor stand
        if stand_data.get("id") != "minecraft:armor_stand":
            logger.debug(f"    Saltato - non è armor stand: ID={stand_data.get('id')}")
            continue
            
        # Verifica orientamento cardinale
        direction = stand_data.get("direction")
        if direction not in cardinal_orientations_text:
            logger.debug(f"    Saltato - orientamento non cardinale: {direction}")
            continue
            
        try:
            # La posizione è una lista [x, y, z], convertiamola nel formato dict atteso
            pos_list = stand_data["position"]
            coords_dict = {"x": float(pos_list[0]), "y": float(pos_list[1]), "z": float(pos_list[2])}
            
            cardinal_armor_stands.append({
                "coords": coords_dict,
                "orientation": stand_data["direction"], # Es: "Nord"
                "raw_yaw": float(stand_data.get("yaw", 0.0)) # Yaw fornito dallo script
            })
            logger.info(f"✅ Armor Stand Cardinale Valido: Coords={coords_dict}, Orient={direction}, Yaw={stand_data.get('yaw')}")
            
        except (KeyError, IndexError, ValueError) as e:
            logger.warning(f"⚠️ Errore nel processare armor stand [{i}]: {stand_data}. Errore: {e}")

    logger.info(f"📊 Risultato filtro: {len(cardinal_armor_stands)} armor stand cardinali trovati su {len(all_found_stands_data)} totali")

    # Step 4: Gestire risultati
    if len(cardinal_armor_stands) == 1:
        target_as = cardinal_armor_stands[0]
        as_coords = target_as["coords"]
        as_orientation = target_as["orientation"] # Es: "Nord"

        context.user_data["hologram_as_coords"] = as_coords
        context.user_data["hologram_as_orientation"] = as_orientation
        context.user_data["awaiting_hologram_structure"] = True

        orientation_angle_map = {"Sud": "0°", "Ovest": "90°", "Nord": "180°", "Est": "270°"}
        angle_display = orientation_angle_map.get(as_orientation, f"{target_as['raw_yaw']:.1f}°")

        logger.info(f"🎯 Armor Stand selezionato con successo: {as_coords} orientato verso {as_orientation}")
        
        await update.message.reply_text(
            f"✅ **Armor Stand Rilevato con Successo!**\n"
            f"📍 Coordinate: {as_coords['x']:.1f}, {as_coords['y']:.1f}, {as_coords['z']:.1f}\n"
            f"🧭 Orientamento (AS guarda verso): {as_orientation.capitalize()} ({angle_display})\n\n"
            "⬆️ Ora carica il file `.mcstructure` per l'ologramma."
        )
        return True
        
    elif len(cardinal_armor_stands) == 0:
        # Fornire informazioni dettagliate su cosa è stato trovato
        non_armor_stands = [item for item in all_found_stands_data if item.get("id") != "minecraft:armor_stand"]
        non_cardinal_armor_stands = [item for item in all_found_stands_data 
                                   if item.get("id") == "minecraft:armor_stand" 
                                   and item.get("direction") not in cardinal_orientations_text]
        
        details_msg = f"❌ **Nessun Armor Stand Cardinale Trovato**\n\n"
        details_msg += f"📊 **Analisi Dettagliata del Chunk:**\n"
        details_msg += f"• Elementi totali trovati: {len(all_found_stands_data)}\n"
        details_msg += f"• Non-armor-stand: {len(non_armor_stands)}\n"
        details_msg += f"• Armor stand non-cardinali: {len(non_cardinal_armor_stands)}\n\n"
        
        if non_cardinal_armor_stands:
            details_msg += f"🧭 **Armor Stand con orientamento non-cardinale:**\n"
            for item in non_cardinal_armor_stands[:3]:  # Mostra solo i primi 3
                pos = item.get("position", [0,0,0])
                details_msg += f"• Pos: {pos[0]:.1f},{pos[1]:.1f},{pos[2]:.1f} - Orient: {item.get('direction', 'N/A')}\n"
            
        details_msg += f"\n🔧 **Suggerimenti:**\n"
        details_msg += f"• L'armor stand deve essere orientato ESATTAMENTE verso N,S,E,O\n"
        details_msg += f"• Usa F3 in gioco per verificare l'orientamento preciso\n"
        details_msg += f"• Riposiziona l'armor stand se necessario"
        
        logger.info(f"Nessun AS cardinale. Non-AS: {len(non_armor_stands)}, AS non-cardinali: {len(non_cardinal_armor_stands)}")
        await update.message.reply_text(details_msg)
        cleanup_hologram_data(context)
        return False
        
    else: # > 1 found
        logger.warning(f"Troppi AS cardinali trovati ({len(cardinal_armor_stands)}): {cardinal_armor_stands}")
        
        details_msg = f"❌ **Trovati {len(cardinal_armor_stands)} Armor Stand Cardinali**\n\n"
        details_msg += f"📍 **Posizioni degli Armor Stand trovati:**\n"
        for i, as_data in enumerate(cardinal_armor_stands[:5]):  # Mostra max 5
            coords = as_data["coords"]
            orient = as_data["orientation"]
            details_msg += f"• AS #{i+1}: {coords['x']:.1f},{coords['y']:.1f},{coords['z']:.1f} - {orient}\n"
            
        details_msg += f"\n🔧 **Per procedere:**\n"
        details_msg += f"• Rimuovi gli armor stand in eccesso nel chunk\n"
        details_msg += f"• Mantieni solo quello che vuoi utilizzare\n"
        details_msg += f"• Riprova il comando"
        
        await update.message.reply_text(details_msg)
        cleanup_hologram_data(context)
        return False

    # Fallback - non dovrebbe mai arrivare qui
    logger.error("❌ Raggiunto fallback imprevisto in detect_armor_stand_v3")
    await update.message.reply_text("❌ Errore imprevisto durante la ricerca dell'armor stand.")
    cleanup_hologram_data(context)
    return False




async def get_player_coords(minecraft_username: str):
    """Ottiene coordinate del player (questa funzione rimane utile per altri scopi, ma non è usata direttamente per le coordinate dell'AS nel nuovo flusso)"""
    try:
        # Comando più robusto, simile a quello usato in saveloc
        cmd = f"execute as {minecraft_username} at @s run tp @s ~ ~ ~0.0001"
        
        # Non è strettamente necessario pulire i log se leggiamo abbastanza righe dopo,
        # ma lo manteniamo per coerenza se si decide di ridurre --tail in futuro.
        # Considera che run_docker_command per send-command non restituisce output diretto del gioco.
        await run_docker_command(["docker", "exec", CONTAINER, "send-command", cmd], read_output=False, timeout=10)
        await asyncio.sleep(1.0) # Allineato con saveloc
        
        # Leggi più righe di log per aumentare la probabilità di catturare il messaggio
        log_output = await run_docker_command(["docker", "logs", "--tail", "100", CONTAINER], read_output=True, timeout=5)
        
        matches = None
        # Pattern primario da saveloc
        pattern1 = rf"Teleported {re.escape(minecraft_username)} to ([0-9\.\-]+),\s*([0-9\.\-]+),\s*([0-9\.\-]+)"
        found_matches = re.findall(pattern1, log_output)
        
        if not found_matches:
            # Pattern di fallback da saveloc
            pattern2 = rf"Teleported {re.escape(minecraft_username)} to ([0-9\.\-]+), ([0-9\.\-]+), ([0-9\.\-]+)"
            found_matches = re.findall(pattern2, log_output)

        if found_matches:
            x_str, y_str, z_str = found_matches[-1] # Prendi l'ultimo match, come in saveloc
            logger.info(f"Coordinate trovate per {minecraft_username}: X={x_str}, Y={y_str}, Z={z_str}")
            return {"x": float(x_str), "y": float(y_str), "z": float(z_str)}
        
        logger.warning(f"Could not parse coordinates for {minecraft_username} from log ({len(log_output.splitlines())} lines checked). Log snippet: ...{log_output[-500:]}")
        return None
        
    except asyncio.TimeoutError as e:
        logger.error(f"Timeout durante l'ottenimento delle coordinate del player {minecraft_username}: {e}")
        return None
    except subprocess.CalledProcessError as e:
        logger.error(f"Errore subprocess durante l'ottenimento delle coordinate del player {minecraft_username}: {e.stderr or e.output or e}")
        return None
    except ValueError as e: # Per float() conversion
        logger.error(f"Errore di conversione valore per le coordinate del player {minecraft_username}: {e}. Log: {log_output}")
        return None
    except Exception as e:
        logger.error(f"Errore generico durante l'ottenimento delle coordinate del player {minecraft_username}: {e}", exc_info=True)
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
        "hologram_as_orientation",
        "pending_hologram_action", # Assicurati che anche questo venga pulito
        "paste_coords"
    ]
    for key in keys_to_remove:
        if key in context.user_data:
            del context.user_data[key]
    logger.info("Hologram temporary data cleaned up.")





async def handle_hologram_confirm_paste_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Gestisce la conferma dell'utente per incollare l'ologramma.
    Ferma il server, esegue il backup, incolla la struttura, riavvia il server.
    """
    query = update.callback_query
    await query.answer("✅ Conferma ricevuta. Inizio procedura...") # Risposta rapida al callback
    
    pending_action = context.user_data.get('pending_hologram_action')

    if not pending_action:
        logger.warning("hologram_confirm_paste callback ricevuto ma 'pending_hologram_action' non trovato in user_data.")
        await query.edit_message_text("❌ Errore: Azione di paste non trovata o scaduta. Riprova il comando /pastehologram.")
        cleanup_hologram_data(context) # Pulisce anche se non c'era pending_action, per sicurezza
        return

    # Estrai i dati necessari
    armor_stand_coords = pending_action['armor_stand_coords']
    orientation = pending_action['orientation']
    # minecraft_username = pending_action['minecraft_username'] # Non direttamente usato qui, ma disponibile
    structure_path = pending_action['structure_path']
    structure_name = pending_action['structure_name']
    chat_id = pending_action['chat_id'] # Utile per inviare messaggi di stato

    try:
        escaped_container_name = escape_markdown_v2(CONTAINER)
        escaped_structure_name_html = html.escape(structure_name) # For HTML context messages

        await context.bot.send_message(chat_id, f"🛠️ Avvio procedura di incollaggio per '{escaped_structure_name_html}'...")
        
        # --- STOP SERVER ---
        await context.bot.send_message(chat_id, f"🛑 Arresto del server `{escaped_container_name}` in corso\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
        server_stopped = await stop_server_command(update, context, quiet=True)
        if not server_stopped:
            logger.error(f"SERVER_STOP: Impossibile fermare il server {CONTAINER}.")
            await context.bot.send_message(chat_id, f"❌ Impossibile arrestare il server `{escaped_container_name}`\\. Operazione interrotta\\.", parse_mode=ParseMode.MARKDOWN_V2)
            # Non tentare di riavviare se non si è fermato, potrebbe essere già in uno stato problematico.
            cleanup_hologram_data(context)
            return
        logger.info(f"SERVER_STOP: Server {CONTAINER} fermato.")
        await context.bot.send_message(chat_id, f"✅ Server `{escaped_container_name}` arrestato\\.", parse_mode=ParseMode.MARKDOWN_V2)

        # --- CREATE BACKUP ---
        await context.bot.send_message(chat_id, "💾 Creazione backup del mondo in corso...")
        backup_successful = await create_world_backup_for_paste(update, context)
        if not backup_successful:
            await context.bot.send_message(chat_id, "❌ Backup fallito\\. Operazione interrotta\\.")
            # --- RESTART SERVER ---
            logger.info(f"SERVER_START: Tentativo di riavviare il server {CONTAINER} dopo backup fallito.")
            await context.bot.send_message(chat_id, f"🔄 Riavvio del server `{escaped_container_name}` in corso\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
            server_restarted = await start_server_command(update, context, quiet=True)
            if server_restarted:
                logger.info(f"SERVER_START: Server {CONTAINER} riavviato dopo backup fallito.")
                await context.bot.send_message(chat_id, f"✅ Server `{escaped_container_name}` riavviato\\.", parse_mode=ParseMode.MARKDOWN_V2)
            else:
                logger.error(f"SERVER_START: Impossibile riavviare il server {CONTAINER} dopo backup fallito.")
                await context.bot.send_message(chat_id, f"❌ Impossibile riavviare il server `{escaped_container_name}` dopo backup fallito\\.", parse_mode=ParseMode.MARKDOWN_V2)
            cleanup_hologram_data(context)
            return
        await context.bot.send_message(chat_id, "✅ Backup completato\\.")

        # --- PASTE STRUCTURE ---
        coords_str = f"{armor_stand_coords['x']},{armor_stand_coords['y']},{armor_stand_coords['z']}" # Lo script vuole senza spazi
        await context.bot.send_message(chat_id, f"🏗️ Incollaggio struttura '{escaped_structure_name_html}' in corso...")
        paste_successful = await execute_paste_structure_script(
            structure_path, coords_str, orientation, update, context
        )
        if not paste_successful:
            await context.bot.send_message(chat_id, "❌ Incollaggio struttura fallito\\.")
            # --- RESTART SERVER ---
            logger.info(f"SERVER_START: Tentativo di riavviare il server {CONTAINER} dopo paste fallito.")
            await context.bot.send_message(chat_id, f"🔄 Riavvio del server `{escaped_container_name}` in corso\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
            server_restarted_after_paste_fail = await start_server_command(update, context, quiet=True)
            if server_restarted_after_paste_fail:
                logger.info(f"SERVER_START: Server {CONTAINER} riavviato dopo paste fallito.")
                await context.bot.send_message(chat_id, f"✅ Server `{escaped_container_name}` riavviato\\.", parse_mode=ParseMode.MARKDOWN_V2)
            else:
                logger.error(f"SERVER_START: Impossibile riavviare il server {CONTAINER} dopo paste fallito.")
                await context.bot.send_message(chat_id, f"❌ Impossibile riavviare il server `{escaped_container_name}` dopo paste fallito\\.", parse_mode=ParseMode.MARKDOWN_V2)
            cleanup_hologram_data(context)
            return
        # Removed the success message here, it's now part of the initial confirmation.

        # --- RESTART SERVER ---
        logger.info(f"SERVER_START: Tentativo di riavviare il server {CONTAINER}.")
        await context.bot.send_message(chat_id, f"🔄 Riavvio del server `{escaped_container_name}` in corso\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
        final_server_restarted = await start_server_command(update, context, quiet=True)
        if final_server_restarted:
            logger.info(f"SERVER_START: Server {CONTAINER} riavviato.")
            await context.bot.send_message(chat_id, f"✅ Server `{escaped_container_name}` riavviato\\. Operazione completata\\!", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            logger.error(f"SERVER_START: Impossibile riavviare il server {CONTAINER} al termine dell'operazione.")
            await context.bot.send_message(chat_id, f"❌ Impossibile riavviare il server `{escaped_container_name}` al termine dell'operazione\\.", parse_mode=ParseMode.MARKDOWN_V2)


    except Exception as e:
        logger.error(f"Errore imprevisto in handle_hologram_confirm_paste_callback: {e}", exc_info=True)
        await context.bot.send_message(chat_id, f"❌ Errore critico durante l'operazione di paste: {html.escape(str(e))}")
        # Tentativo di riavviare il server anche in caso di errore imprevisto
        escaped_container_name_for_error = escape_markdown_v2(CONTAINER)
        logger.info(f"SERVER_START: Tentativo di riavviare il server {CONTAINER} dopo errore critico.")
        await context.bot.send_message(chat_id, f"🔄 Riavvio di emergenza del server `{escaped_container_name_for_error}`\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
        emergency_restart_success = await start_server_command(update, context, quiet=True)
        if emergency_restart_success:
            logger.info(f"SERVER_START: Server {CONTAINER} riavviato (emergenza).")
            await context.bot.send_message(chat_id, f"✅ Server `{escaped_container_name_for_error}` riavviato\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            logger.error(f"SERVER_START: Impossibile riavviare il server {CONTAINER} in emergenza.")
            await context.bot.send_message(chat_id, f"❌ Impossibile riavviare il server `{escaped_container_name_for_error}` in emergenza\\.", parse_mode=ParseMode.MARKDOWN_V2)


    finally:
        cleanup_hologram_data(context)
        # Rimuovi il messaggio con i bottoni di conferma/annulla
        structure_name_for_final_msg = "l'operazione"
        if pending_action and 'structure_name' in pending_action:
             structure_name_for_final_msg = f"l'incollaggio di '{html.escape(pending_action['structure_name'])}'"
        try:
            await query.edit_message_text(f"Operazione di incollaggio per '{structure_name_for_final_msg}' terminata.")
        except Exception: # Potrebbe fallire se il messaggio è stato cancellato o è troppo vecchio
            pass


async def handle_hologram_cancel_paste_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Gestisce l'annullamento dell'utente per l'operazione di paste hologram.
    """
    query = update.callback_query
    await query.answer() # Risposta rapida al callback

    pending_action = context.user_data.get('pending_hologram_action')
    structure_name_display = "l'operazione"
    structure_name_display = "l'operazione" # Default
    if pending_action and 'structure_name' in pending_action:
        structure_name_display = f"l'incollaggio di '{html.escape(pending_action['structure_name'])}'"

    logger.info(f"Operazione di paste hologram annullata dall'utente {query.from_user.id}.")
    await query.edit_message_text(f"❌ Annullato {structure_name_display}.") # This message does not use MarkdownV2
    
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


async def execute_hologram_paste(update: Update, context: ContextTypes.DEFAULT_TYPE,
                               armor_stand_coords: dict, orientation: str, minecraft_username: str):
    """
    Prepara l'operazione di paste hologram mostrando un messaggio di conferma con bottoni.
    I dati necessari per l'operazione vengono salvati in context.user_data['pending_hologram_action'].
    L'effettiva esecuzione avviene tramite callback.
    """
    offset_false = False
    structure_path = context.user_data.get("hologram_structure_path")
    structure_name = context.user_data.get("hologram_structure_name")

    if not structure_path or not os.path.exists(structure_path):
        await update.message.reply_text("❌ File struttura non trovato o non più accessibile.")
        cleanup_hologram_data(context)
        return

    # Calculate paste position based on armor stand orientation
    from world_management import get_world_directory_path
    world_dir_path_obj = get_world_directory_path(WORLD_NAME)
    if not world_dir_path_obj or not os.path.exists(world_dir_path_obj):
        await update.message.reply_text(f"❌ Directory del mondo '{WORLD_NAME}' non trovata.")
        cleanup_hologram_data(context)
        return
    world_dir_path = str(world_dir_path_obj)

    # Get structure dimensions
    structure_info_script = "/app/importBuild/schem_to_mc_amulet/structureInfo.py"
    structure_info_exec = "/app/importBuild/schem_to_mc_amulet/venv/bin/python"

    process = await asyncio.create_subprocess_exec(
        structure_info_exec, structure_info_script, structure_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        logger.error(f"Failed to get structure dimensions: {stderr.decode()}")
        await update.message.reply_text("❌ Errore nel leggere le dimensioni della struttura.")
        cleanup_hologram_data(context)
        return False

    # Parse structure info output
    logger.info(f"Structure info raw output:\n{stdout.decode()}")
    
    size_match = re.search(r"Dimensione \(X, Y, Z\): (\d+), (\d+), (\d+)", stdout.decode())
    origin_match = re.search(r"Origine del Mondo \(X, Y, Z\): (-?\d+), (-?\d+), (-?\d+)", stdout.decode())
    
    if not size_match:
        logger.error("Could not parse structure dimensions")
        await update.effective_message.reply_text("❌ Impossibile determinare le dimensioni della struttura.")
        cleanup_hologram_data(context)
        return False

    size_x, size_y, size_z = map(int, size_match.groups())
    
    if origin_match:
        origin_x, origin_y, origin_z = map(int, origin_match.groups())
        logger.info(f"Structure dimensions: {size_x}x{size_y}x{size_z}")
        logger.info(f"Structure world origin: {origin_x}, {origin_y}, {origin_z}")
    else:
        logger.info(f"Structure dimensions: {size_x}x{size_y}x{size_z} (world origin not found)")

    # Calculate paste position based on armor stand orientation
    as_x = float(armor_stand_coords['x'])
    as_y = float(armor_stand_coords['y'])  
    as_z = float(armor_stand_coords['z'])
    
    paste_coords = ""  # Inizializza paste_coords a ""
    paste_x = as_x
    paste_y = as_y
    paste_z = as_z

    logger.info(f"Armor stand position: {as_x}, {as_y}, {as_z}")
    logger.info(f"Armor stand facing: {orientation}")
    logger.info(f"Structure dimensions: {size_x} x {size_y} x {size_z}")

    if offset_false:
        paste_x = as_x
        paste_y = as_y
        paste_z = as_z
        paste_coords = f"{int(paste_x)},{int(paste_y)},{int(paste_z)}"
    else:
        # Calcola il punto di incollaggio in base all'orientamento dell'armor stand
        # La struttura viene incollata nella direzione verso cui guarda l'AS, con un offset
        if orientation == "Nord":
            # AS guarda verso Nord, struttura va verso Nord
            paste_x = as_x + (size_x-1)  # Centra la struttura sull'asse X
            paste_y = as_y
            paste_z = as_z + (size_z-1) 
            logger.info(f"AS facing North: structure placed towards North")

        elif orientation == "Sud":
            # AS guarda verso Sud, struttura va verso Sud
            paste_x = as_x - (size_x-1) 
            paste_y = as_y
            paste_z = as_z - (size_z-1)  
            logger.info(f"AS facing South: structure placed towards South")

        elif orientation == "Est":
            # AS guarda verso Est, struttura va verso Est
            paste_x = as_x - (size_z-1)  
            paste_y = as_y
            paste_z = as_z + (size_x-1)
            logger.info(f"AS facing East: structure placed towards East")

        elif orientation == "Ovest":
            # AS guarda verso Ovest, struttura va verso Ovest
            paste_x = as_x + (size_z-1)  # Struttura inizia 1 blocco avanti rispetto all'AS (verso Ovest)
            paste_y = as_y
            paste_z = as_z - (size_x-1)
            logger.info(f"AS facing West: structure placed towards West")

        else:
            logger.error(f"Unknown armor stand orientation: {orientation}")
            await update.message.reply_text(f"❌ Orientamento armor stand sconosciuto: {orientation}")
            cleanup_hologram_data(context)
            return False

        # Converti a coordinate intere
        paste_x = int(paste_x)
        paste_y = int(paste_y)
        paste_z = int(paste_z)
        paste_coords = f"{paste_x},{paste_y},{paste_z}"

        logger.info(f"Calculated paste origin: {paste_coords}")
        logger.info(f"Structure will span from ({paste_x},{paste_y},{paste_z}) to ({paste_x + size_x - 1},{paste_y + size_y - 1},{paste_z + size_z - 1})")

        # Place a diamond block at the calculated paste origin for visual confirmation
        fill_command = f"fill {paste_x} {paste_y} {paste_z} {paste_x} {paste_y} {paste_z} minecraft:diamond_block"
        logger.info(f"Placing marker block at paste origin: {paste_coords} with command: {fill_command}")

        try:
            fill_process = await asyncio.create_subprocess_exec(
                "docker", "exec", CONTAINER, "send-command", fill_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            fill_stdout_bytes, fill_stderr_bytes = await fill_process.communicate()
            fill_stdout = fill_stdout_bytes.decode('utf-8', errors='replace').strip()
            fill_stderr = fill_stderr_bytes.decode('utf-8', errors='replace').strip()

            if fill_stdout:
                logger.info(f"Fill command stdout: {fill_stdout}")
            if fill_stderr:
                logger.warning(f"Fill command stderr: {fill_stderr}")

            if fill_process.returncode != 0:
                logger.error(f"Failed to place marker block at {paste_coords}. Command: {fill_command}. Return code: {fill_process.returncode}. Stderr: {fill_stderr}")
                await update.message.reply_text(
                    f"⚠️ Attenzione: Impossibile posizionare il blocco di conferma all'origine dell'incollaggio ({paste_coords}). "
                    f"Procedo con l'incollaggio della struttura, ma verifica la posizione manualmente."
                )
            else:
                logger.info(f"Marker block successfully placed at {paste_coords}")
        except Exception as fill_e:
            logger.error(f"Exception during marker block placement at {paste_coords}: {fill_e}", exc_info=True)
            await update.message.reply_text(
                f"⚠️ Attenzione: Eccezione durante il posizionamento del blocco di conferma all'origine dell'incollaggio ({paste_coords}). "
                f"Procedo con l'incollaggio della struttura, ma verifica la posizione manualmente."
            )

    try:
        # Prepare strings for MarkdownV2
        escaped_structure_name = escape_markdown_v2(structure_name)
        coords_str_raw = f"{armor_stand_coords['x']:.1f},{armor_stand_coords['y']:.1f},{armor_stand_coords['z']:.1f}"
        escaped_coords_str = escape_markdown_v2(coords_str_raw)
        escaped_orientation = escape_markdown_v2(orientation.capitalize())
        escaped_paste_coords = escape_markdown_v2(paste_coords)

        keyboard = [
            [InlineKeyboardButton("✅ Conferma Paste", callback_data="hologram_confirm_paste")],
            [InlineKeyboardButton("❌ Annulla Paste", callback_data="hologram_cancel_paste")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Salva i dati necessari prima di inviare il messaggio di conferma
        context.user_data['pending_hologram_action'] = {
            'armor_stand_coords': armor_stand_coords,
            'orientation': orientation,
            'minecraft_username': minecraft_username,
            'structure_path': structure_path,
            'structure_name': structure_name,
            'paste_coords': paste_coords,  # Aggiungi le coordinate calcolate
            'chat_id': update.effective_chat.id
        }
        logger.info(f"Pending hologram action set for user {update.effective_user.id} with structure {structure_name}")

        await update.message.reply_text(
            f"🏗️ **Conferma Incollaggio Ologramma**\n"
            f"📁 Struttura: `{escaped_structure_name}`\n"
            f"📍 AS Coords: `{escaped_coords_str}`\n"
            f"🧭 AS Orient\\.: `{escaped_orientation}`\n"
            f"📍 Origine Incollaggio: `{escaped_paste_coords}`\n"
            f"📏 Dimensioni: `{size_x}x{size_y}x{size_z}`\n\n"
            f"Sei sicuro di voler procedere?\n"
            f"⚠️ Il server verrà fermato, backuppato, la struttura incollata, e poi riavviato\\.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )

    except Exception as e:
        logger.error(f"🏗️❌ Errore durante la preparazione di paste hologram: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore durante la preparazione dell'operazione: {html.escape(str(e))}")
        cleanup_hologram_data(context)


async def execute_paste_structure_script(structure_path: str, coords_str: str,
                                       as_facing_orientation: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Esegue lo script di incollaggio usando le coordinate pre-calcolate.
    """
    # Recupera le coordinate pre-calcolate dall'azione pending
    pending_action = context.user_data.get('pending_hologram_action')
    if not pending_action or 'paste_coords' not in pending_action:
        logger.error("Coordinate di incollaggio pre-calcolate non trovate!")
        await update.effective_message.reply_text("❌ Errore: coordinate di incollaggio non trovate.")
        return False
    
    paste_coords = pending_action['paste_coords']
    logger.info(f"Using pre-calculated paste coordinates: {paste_coords}")

    # Mappa l'orientamento per lo script - ora stesso orientamento dell'AS
    orientation_map = {
        "Nord": "north",
        "Sud": "south", 
        "Est": "east",
        "Ovest": "west"
    }
    paste_script_orientation = orientation_map.get(as_facing_orientation)

    if not paste_script_orientation:
        logger.error(f"Orientamento AS non valido '{as_facing_orientation}' per calcolare orientamento paste.")
        await update.effective_message.reply_text(f"❌ Errore: Orientamento armor stand non valido ({as_facing_orientation}).")
        return False

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
            paste_coords,  # Usa le coordinate pre-calcolate
            "--orient", paste_script_orientation.lower(),
            "--dimension", "overworld", 
            "--mode", "origin",
            "--verbose"
        ]

        logger.info(f"Esecuzione dello script pasteStructure con coordinate pre-calcolate {paste_coords} (AS facing {as_facing_orientation}, pasting towards {paste_script_orientation}): {' '.join(command)}")

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
