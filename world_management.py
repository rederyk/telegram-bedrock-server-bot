# minecraft_telegram_bot/world_management.py
import os
import io
import sys
import tempfile # Per creare file temporanei in modo sicuro
import nbtlib
import shutil # Importato per shutil.make_archive, anche se non usato direttamente qui, ma utile per la logica di backup
from datetime import datetime # Importato per timestamp, utile per i nomi dei backup

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
    MalformedFileError = Exception
    NBTError = Exception

from nbtlib.tag import Byte

BEDROCK_DATA_PATH = "/bedrockData"

def get_world_level_dat_path(world_name: str) -> str | None:
    if not world_name:
        logger.error("Nome del mondo non fornito per trovare level.dat.")
        return None
    
    potential_path_worlds_subdir = os.path.join(BEDROCK_DATA_PATH, "worlds", world_name, "level.dat")
    if os.path.exists(potential_path_worlds_subdir):
        logger.info(f"Trovato level.dat in: {potential_path_worlds_subdir}")
        return potential_path_worlds_subdir

    potential_path_direct_subdir = os.path.join(BEDROCK_DATA_PATH, world_name, "level.dat")
    if os.path.exists(potential_path_direct_subdir):
        logger.info(f"Trovato level.dat in: {potential_path_direct_subdir}")
        return potential_path_direct_subdir

    logger.warning(f"level.dat non trovato per il mondo '{world_name}'. Percorsi controllati: "
                   f"'{potential_path_worlds_subdir}' e '{potential_path_direct_subdir}'. ")
    return None

# <<< INIZIO NUOVE FUNZIONI >>>
def get_world_directory_path(world_name: str) -> str | None:
    """
    Restituisce il percorso assoluto della directory del mondo specificato,
    basandosi sulla posizione del file level.dat.
    """
    level_dat_path = get_world_level_dat_path(world_name)
    if level_dat_path and os.path.exists(level_dat_path):
        # La directory del mondo è la directory genitore di level.dat
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
    path = os.path.join(BEDROCK_DATA_PATH, BACKUPS_DIR_NAME)
    try:
        os.makedirs(path, exist_ok=True) # Crea la directory se non esiste
        logger.info(f"Directory di backup assicurata/creata in: {path}")
    except OSError as e:
        logger.error(f"Errore creando la directory di backup {path}: {e}")
        # Potrebbe essere utile sollevare un'eccezione qui se la directory è cruciale
        # e la sua creazione fallisce per motivi diversi da "already exists".
    return path
# <<< FINE NUOVE FUNZIONI >>>

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
        with open(level_dat_path, "rb") as f:
            original_header = f.read(8) # Leggi l'header originale di 8 byte
            if len(original_header) < 8:
                logger.error(f"File level.dat ({level_dat_path}) troppo corto o corrotto (header mancante).")
                return False, "level.dat troppo corto o corrotto (header mancante)."
            
            nbt_file = nbtlib.File.parse(f, byteorder='little')
            logger.info(f"File NBT parsato con successo. Tipo dell'oggetto nbt_file: {type(nbt_file)}")

        tag_to_find_pascal_case = "HasBeenLoadedInCreative"
        tag_to_find_camel_case = "hasBeenLoadedInCreative"
        tag_found_name = None

        if tag_to_find_camel_case in nbt_file:
            tag_found_name = tag_to_find_camel_case
        elif tag_to_find_pascal_case in nbt_file:
            tag_found_name = tag_to_find_pascal_case
        
        if tag_found_name:
            logger.info(f"Trovato tag NBT '{tag_found_name}' in {level_dat_path}.")
            current_value = nbt_file[tag_found_name]
            
            if isinstance(current_value, Byte) and current_value == 0:
                logger.info(f"Il tag '{tag_found_name}' è già impostato a 0.")
                return True, f"Il tag '{tag_found_name}' è già impostato a 0 (False)."
            
            nbt_file[tag_found_name] = Byte(0)
            logger.info(f"Impostato il tag '{tag_found_name}' a 0 per il mondo '{world_name}'.")
        else:
            logger.warning(f"Tag '{tag_to_find_camel_case}' o '{tag_to_find_pascal_case}' non trovato in {level_dat_path}.")
            logger.info("--- DIAGNOSTICA: Tag NBT di primo livello disponibili nel file level.dat ---")
            if hasattr(nbt_file, 'keys') and callable(nbt_file.keys):
                available_keys = list(nbt_file.keys())
                if not available_keys:
                    logger.info("(Nessun tag di primo livello trovato o nbt_file non è un Compound con chiavi)")
                for key in available_keys:
                    logger.info(f"- Nome Tag: '{key}', Tipo: {type(nbt_file[key])}")
            else:
                logger.info("(L'oggetto nbt_file non ha il metodo 'keys', potrebbe non essere un Compound tag come radice o essere strutturato diversamente)")
            logger.info("--- FINE DIAGNOSTICA ---")
            return False, (f"Tag '{tag_to_find_camel_case}' (o simile) non trovato in level.dat. "
                           "Nessuna modifica apportata. Controlla i log del bot per i tag disponibili.")
        
        temp_file_handle, temp_file_path = tempfile.mkstemp(suffix=".dat", prefix="nbt_temp_")
        os.close(temp_file_handle)

        try:
            logger.info(f"Salvataggio NBT modificato su file temporaneo: {temp_file_path} con byteorder='little'")
            nbt_file.save(temp_file_path, byteorder='little')

            with open(temp_file_path, "rb") as tmp_f:
                modified_nbt_data_bytes = tmp_f.read()
            logger.info(f"Dati NBT letti da file temporaneo. Lunghezza: {len(modified_nbt_data_bytes)} bytes.")

        except Exception as e_save_temp:
            logger.error(f"Errore durante il salvataggio su file temporaneo ({temp_file_path}) o lettura: {type(e_save_temp).__name__} - {e_save_temp}", exc_info=True)
            return False, f"Errore durante il salvataggio NBT intermedio: {e_save_temp}"
        finally:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                    logger.info(f"File temporaneo {temp_file_path} rimosso.")
                except OSError as e_remove:
                    logger.error(f"Impossibile rimuovere il file temporaneo {temp_file_path}: {e_remove}")
        
        with open(level_dat_path, "wb") as f_final:
            f_final.write(original_header)
            f_final.write(modified_nbt_data_bytes)

        logger.info(f"Modifiche scritte con successo su {level_dat_path} utilizzando il metodo del file temporaneo.")
        return True, f"Reset del tag '{tag_found_name}' a 0 eseguito con successo per il mondo '{world_name}'."

    except (MalformedFileError, NBTError) as e:
        logger.error(f"Errore NBT ({type(e).__name__}) per {level_dat_path}: {e}", exc_info=True)
        return False, f"Errore NBT durante l'elaborazione di level.dat: {e}"
    except Exception as e:
        logger.error(f"Errore imprevisto ({type(e).__name__}) durante il reset del flag creativo per {world_name}: {e}", exc_info=True)
        return False, f"Si è verificato un errore imprevisto: {e}"