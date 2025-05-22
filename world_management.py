# minecraft_telegram_bot/world_management.py
import os
import io
import sys
import tempfile # Per creare file temporanei in modo sicuro
import nbtlib
import shutil # Importato per shutil.make_archive, anche se non usato direttamente qui, ma utile per la logica di backup
from datetime import datetime # Importato per timestamp, utile per i nomi dei backup
import asyncio # Aggiunto per asyncio.to_thread se necessario per operazioni NBT lunghe

from config import get_logger, BACKUPS_DIR_NAME # Aggiunto BACKUPS_DIR_NAME
logger = get_logger(__name__)

try:
    from nbtlib.nbt import MalformedFileError, NBTError
    logger.info("Importate con successo MalformedFileError e NBTError da nbtlib.nbt.")
except ImportError:
    logger.warning(
        "ATTENZIONE: Impossibile importare MalformedFileError o NBTError da nbtlib.nbt. "
        "Questo è atteso con la versione di nbtlib (es. 2.0.4) che sembra essere installata. "
        "La gestione specifica degli errori NBT sarà compromessa; si utilizzerà 'Exception' come fallback generico."
    )
    MalformedFileError = Exception # type: ignore
    NBTError = Exception # type: ignore

from nbtlib.tag import Byte # type: ignore

BEDROCK_DATA_PATH = "/bedrockData" # Definito qui per coerenza, usato implicitamente sotto

def get_world_level_dat_path(world_name: str) -> str | None:
    if not world_name:
        logger.error("Nome del mondo non fornito per trovare level.dat.")
        return None
    
    # Percorso primario (usato da itzg/minecraft-bedrock-server quando si specifica LEVEL_NAME)
    # /data/worlds/MyWorldName/level.dat -> /bedrockData/worlds/MyWorldName/level.dat
    potential_path_worlds_subdir = os.path.join(BEDROCK_DATA_PATH, "worlds", world_name, "level.dat")
    if os.path.exists(potential_path_worlds_subdir):
        logger.info(f"Trovato level.dat in: {potential_path_worlds_subdir}")
        return potential_path_worlds_subdir

    # Percorso secondario (usato da itzg/minecraft-bedrock-server se non si specifica LEVEL_NAME, usa il nome della cartella)
    # /data/Bedrock level/level.dat -> /bedrockData/Bedrock level/level.dat
    potential_path_direct_subdir = os.path.join(BEDROCK_DATA_PATH, world_name, "level.dat")
    if os.path.exists(potential_path_direct_subdir):
        logger.info(f"Trovato level.dat in: {potential_path_direct_subdir}")
        return potential_path_direct_subdir
    
    # Fallback per strutture di cartelle personalizzate o vecchie
    # /data/MyWorldName/level.dat -> /bedrockData/MyWorldName/level.dat
    # Questo è simile al direct_subdir ma lo teniamo per chiarezza se la logica dovesse cambiare.
    # In realtà, con la configurazione attuale, questo è già coperto da potential_path_direct_subdir
    # se world_name è il nome della cartella del mondo direttamente sotto /bedrockData.

    logger.warning(f"level.dat non trovato per il mondo '{world_name}'. Percorsi controllati: "
                   f"'{potential_path_worlds_subdir}' e '{potential_path_direct_subdir}'. ")
    return None


def get_world_directory_path(world_name: str) -> str | None:
    """
    Restituisce il percorso assoluto della directory del mondo specificato,
    basandosi sulla posizione del file level.dat.
    """
    level_dat_path = get_world_level_dat_path(world_name)
    if level_dat_path and os.path.exists(level_dat_path):
        world_dir = os.path.dirname(level_dat_path)
        logger.info(f"Directory del mondo '{world_name}' trovata in: {world_dir}")
        return world_dir
    logger.warning(f"Impossibile determinare la directory del mondo per '{world_name}' da level.dat.")
    return None

def get_backups_storage_path() -> str:
    """
    Restituisce il percorso assoluto della directory di archiviazione dei backup
    e si assicura che esista.
    """
    # Assicurati che BEDROCK_DATA_PATH sia il prefisso corretto per i backup
    # Se i backup devono essere fuori da /bedrockData, modifica questo percorso.
    # Per ora, li mettiamo dentro /bedrockData/backups
    path = os.path.join(BEDROCK_DATA_PATH, BACKUPS_DIR_NAME)
    try:
        os.makedirs(path, exist_ok=True) 
        logger.info(f"Directory di backup assicurata/creata in: {path}")
    except OSError as e:
        logger.error(f"Errore creando la directory di backup {path}: {e}")
        # Considera di sollevare un'eccezione se la directory è cruciale
    return path

# <<< INIZIO NUOVE FUNZIONI PER RESOURCE PACKS >>>
def get_resource_packs_main_folder_path() -> str | None:
    """
    Restituisce il percorso assoluto della directory principale dei resource pack
    e si assicura che esista.
    Il server Bedrock di solito cerca i resource pack in una cartella 'resource_packs'
    allo stesso livello della cartella 'worlds' o del file 'server.properties'.
    Con il volume mapping di Docker, questo si traduce in /bedrockData/resource_packs
    """
    path = os.path.join(BEDROCK_DATA_PATH, "resource_packs") 
    try:
        # Non è necessario crearla qui se il server la gestisce, 
        # ma è utile per il bot sapere dove mettere i file.
        # La funzione di installazione la creerà se non esiste.
        # os.makedirs(path, exist_ok=True) 
        logger.info(f"Percorso designato per la cartella dei resource pack: {path}")
        return path
    except OSError as e: # In caso di problemi con makedirs se lo si abilita
        logger.error(f"Errore con la directory dei resource pack {path}: {e}")
        return None

def get_world_specific_resource_packs_json_path(world_name: str) -> str | None:
    """
    Restituisce il percorso assoluto del file world_resource_packs.json
    per il mondo specificato.
    """
    world_dir = get_world_directory_path(world_name)
    if world_dir:
        json_path = os.path.join(world_dir, "world_resource_packs.json")
        logger.info(f"Percorso per world_resource_packs.json per '{world_name}': {json_path}")
        return json_path
    logger.warning(f"Impossibile determinare la directory del mondo per '{world_name}' per trovare world_resource_packs.json.")
    return None
# <<< FINE NUOVE FUNZIONI PER RESOURCE PACKS >>>


async def reset_creative_flag(world_name: str) -> tuple[bool, str]:
    level_dat_path = get_world_level_dat_path(world_name)
    if not level_dat_path:
        return False, f"Impossibile localizzare level.dat per il mondo '{world_name}'. Controlla i log del bot."

    if not os.path.exists(level_dat_path):
        logger.error(f"File level.dat non trovato al percorso finale: {level_dat_path}")
        return False, f"File level.dat non trovato al percorso calcolato: {level_dat_path}"

    original_header = None
    modified_nbt_data_bytes = None

    try:
        # Operazioni su file NBT possono essere bloccanti, esegui in un thread separato
        def _process_nbt_file():
            nonlocal original_header, modified_nbt_data_bytes
            with open(level_dat_path, "rb") as f:
                original_header = f.read(8) 
                if len(original_header) < 8:
                    logger.error(f"File level.dat ({level_dat_path}) troppo corto o corrotto (header mancante).")
                    raise ValueError("level.dat troppo corto o corrotto (header mancante).")
                
                # nbtlib.File.parse potrebbe non resettare il cursore del file dopo la lettura dell'header
                # quindi passiamo un buffer di byte senza l'header, o un file aperto al punto giusto.
                # Per semplicità, riapriamo o usiamo un buffer.
                # Alternativa: f.seek(8) prima di parse, ma nbtlib potrebbe aspettarsi l'header.
                # La documentazione di nbtlib suggerisce che può gestire l'header.
                # Rileggiamo il file intero per nbtlib se necessario.
                f.seek(0) # Resetta il cursore per nbtlib per parsare l'intero file
                nbt_file = nbtlib.File.parse(f, byteorder='little') # type: ignore
                logger.info(f"File NBT parsato con successo. Tipo dell'oggetto nbt_file: {type(nbt_file)}")

            tag_to_find_pascal_case = "HasBeenLoadedInCreative"
            tag_to_find_camel_case = "hasBeenLoadedInCreative"
            tag_found_name = None

            if tag_to_find_camel_case in nbt_file: # type: ignore
                tag_found_name = tag_to_find_camel_case
            elif tag_to_find_pascal_case in nbt_file: # type: ignore
                tag_found_name = tag_to_find_pascal_case
            
            if tag_found_name:
                logger.info(f"Trovato tag NBT '{tag_found_name}' in {level_dat_path}.")
                current_value = nbt_file[tag_found_name] # type: ignore
                
                if isinstance(current_value, Byte) and current_value == 0:
                    logger.info(f"Il tag '{tag_found_name}' è già impostato a 0.")
                    return True, f"Il tag '{tag_found_name}' è già impostato a 0 (False)."
                
                nbt_file[tag_found_name] = Byte(0) # type: ignore
                logger.info(f"Impostato il tag '{tag_found_name}' a 0 per il mondo '{world_name}'.")
            else:
                logger.warning(f"Tag '{tag_to_find_camel_case}' o '{tag_to_find_pascal_case}' non trovato in {level_dat_path}.")
                # ... (logging diagnostico esistente)
                return False, (f"Tag '{tag_to_find_camel_case}' (o simile) non trovato in level.dat. "
                               "Nessuna modifica apportata.")
            
            # Salva NBT modificato in un buffer di byte
            # nbtlib.File.save() può scrivere su un file o un buffer.
            # Per ottenere i byte, scriviamo su un buffer in memoria.
            with io.BytesIO() as temp_buffer:
                nbt_file.save(temp_buffer, byteorder='little') # type: ignore
                # L'header NBT (8 byte) è scritto da nbtlib.File.save()
                # Dobbiamo rimuoverlo se vogliamo usare il nostro header originale.
                temp_buffer.seek(0)
                header_from_nbtlib = temp_buffer.read(8) # Leggi l'header scritto da nbtlib
                modified_nbt_data_bytes = temp_buffer.read() # Leggi il resto dei dati NBT
                logger.info(f"Dati NBT (senza header di nbtlib) pronti. Lunghezza: {len(modified_nbt_data_bytes)} bytes.")
                logger.info(f"Header originale letto: {original_header}, Header da nbtlib: {header_from_nbtlib}")

            return True, f"Reset del tag '{tag_found_name}' a 0 preparato per il mondo '{world_name}'."

        # Esegui la funzione sincrona in un thread separato
        success_processing, message_processing = await asyncio.to_thread(_process_nbt_file)

        if not success_processing:
            return False, message_processing
        
        if original_header is None or modified_nbt_data_bytes is None:
             logger.error("Header originale o dati NBT modificati non sono stati popolati correttamente.")
             return False, "Errore interno durante la preparazione dei dati NBT."

        # Scrivi il file level.dat modificato
        with open(level_dat_path, "wb") as f_final:
            f_final.write(original_header) # Scrivi l'header originale letto all'inizio
            f_final.write(modified_nbt_data_bytes) # Scrivi i dati NBT (senza l'header di nbtlib)

        logger.info(f"Modifiche scritte con successo su {level_dat_path}.")
        return True, message_processing # Usa il messaggio da _process_nbt_file se era già "già impostato a 0"

    except ValueError as ve: # Cattura il ValueError da _process_nbt_file
        logger.error(f"Errore di valore durante l'elaborazione di NBT per {world_name}: {ve}", exc_info=True)
        return False, str(ve)
    except (MalformedFileError, NBTError) as e:
        logger.error(f"Errore NBT ({type(e).__name__}) per {level_dat_path}: {e}", exc_info=True)
        return False, f"Errore NBT durante l'elaborazione di level.dat: {e}"
    except Exception as e:
        logger.error(f"Errore imprevisto ({type(e).__name__}) durante il reset del flag creativo per {world_name}: {e}", exc_info=True)
        return False, f"Si è verificato un errore imprevisto: {e}"
