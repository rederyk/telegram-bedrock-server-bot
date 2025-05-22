# minecraft_telegram_bot/resource_pack_management.py
import os
import json
import zipfile
import requests
import shutil
import uuid # Per generare nomi di file univoci se necessario
from typing import Tuple, Optional, List, Dict, Any

from config import get_logger, WORLD_NAME # Assumendo che WORLD_NAME sia necessario qui o passato esplicitamente
from world_management import get_resource_packs_main_folder_path, get_world_specific_resource_packs_json_path

logger = get_logger(__name__)

class ResourcePackError(Exception):
    """Eccezione personalizzata per le operazioni sui resource pack."""
    pass


def _is_valid_url(url: str) -> bool:
    """Validazione URL di base."""
    return url.startswith('http://') or url.startswith('https://')

def _extract_manifest_details(pack_zip_path: str) -> Tuple[Optional[str], Optional[List[int]], Optional[str]]:
    """
    Estrae UUID, versione e nome da manifest.json all'interno di un file zip.
    Restituisce (uuid, version_array, name)
    """
    try:
        with zipfile.ZipFile(pack_zip_path, 'r') as zf:
            if 'manifest.json' not in zf.namelist():
                logger.error(f"manifest.json non trovato in {pack_zip_path}")
                raise ResourcePackError(f"Manifest.json non trovato in {os.path.basename(pack_zip_path)}.")
            
            with zf.open('manifest.json') as manifest_file:
                manifest_data = json.load(manifest_file)
            
            header = manifest_data.get('header', {})
            pack_uuid = header.get('uuid')
            version = header.get('version') # Dovrebbe essere un array es. [1, 0, 0]
            name = header.get('name')

            if not pack_uuid or not isinstance(pack_uuid, str):
                raise ResourcePackError("UUID del pacchetto mancante o non valido nel manifest.")
            if not version or not isinstance(version, list) or not all(isinstance(v, int) for v in version):
                raise ResourcePackError("Versione del pacchetto mancante o non valida nel manifest.")
            
            # Il nome può essere una stringa 'pack.name' o mancare, specialmente in vecchi pacchetti
            if not name or not isinstance(name, str): 
                # Prova a ottenere il nome dai moduli se non è nell'header (comune per alcuni pacchetti)
                modules = manifest_data.get('modules', [])
                if modules and isinstance(modules, list) and len(modules) > 0 and 'description' in modules[0]:
                     # Spesso la descrizione del primo modulo è usata come nome/identificatore
                     name = modules[0].get('description', 'Nome Sconosciuto dal Modulo')
                else:
                    name = "Nome Pacchetto Sconosciuto" # Fallback se nessun nome trovato

            logger.info(f"Estratto dal manifest di {os.path.basename(pack_zip_path)}: UUID={pack_uuid}, Version={version}, Name={name}")
            return str(pack_uuid), list(version), str(name)

    except zipfile.BadZipFile:
        logger.error(f"File zip corrotto o non valido: {pack_zip_path}")
        raise ResourcePackError(f"File {os.path.basename(pack_zip_path)} corrotto o non è un file zip valido.")
    except json.JSONDecodeError:
        logger.error(f"Errore di decodifica JSON in manifest.json da {pack_zip_path}")
        raise ResourcePackError(f"Errore nel leggere il manifest.json del pacchetto {os.path.basename(pack_zip_path)}.")
    except KeyError as e:
        logger.error(f"Chiave mancante nel manifest.json da {pack_zip_path}: {e}")
        raise ResourcePackError(f"Struttura manifest.json non valida in {os.path.basename(pack_zip_path)} (manca: {e}).")


async def download_resource_pack_from_url(url: str, temp_dir: str) -> str:
    """
    Scarica un resource pack da un URL in una directory temporanea.
    Restituisce il percorso al file scaricato.
    """
    if not _is_valid_url(url):
        raise ResourcePackError("URL fornito non valido.")

    try:
        # Esegui la richiesta in un thread separato per non bloccare l'event loop di asyncio
        response = await asyncio.to_thread(requests.get, url, stream=True, timeout=30)
        response.raise_for_status()

        content_disposition = response.headers.get('content-disposition')
        filename = None
        if content_disposition:
            parts = content_disposition.split('filename=')
            if len(parts) > 1:
                filename = parts[1].strip('" ')
        
        if not filename:
            filename = url.split('/')[-1]
            if not filename or '?' in filename: 
                 filename = "downloaded_pack_" + str(uuid.uuid4())[:8]

        if not any(filename.lower().endswith(ext) for ext in ['.zip', '.mcpack']):
            filename += ".zip"
            
        temp_file_path = os.path.join(temp_dir, filename)

        with open(temp_file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        logger.info(f"File scaricato da {url} a {temp_file_path}")
        return temp_file_path
    except requests.exceptions.RequestException as e:
        logger.error(f"Errore durante il download da {url}: {e}")
        raise ResourcePackError(f"Errore di download: {e}")
    except Exception as e: # Cattura altre eccezioni impreviste
        logger.error(f"Errore imprevisto durante il download da {url}: {e}", exc_info=True)
        raise ResourcePackError(f"Errore imprevisto durante il download: {e}")


def install_resource_pack_from_file(
    source_file_path: str, 
    original_filename: str
) -> Tuple[str, str, List[int], str]:
    """
    Elabora un file resource pack (percorso locale), rinomina se .mcpack,
    lo sposta nella cartella resource_packs ed estrae i dettagli del manifest.

    Restituisce: (final_pack_path, pack_uuid, pack_version, pack_name)
    """
    resource_packs_folder = get_resource_packs_main_folder_path()
    if not resource_packs_folder:
        raise ResourcePackError("Impossibile determinare la cartella dei resource pack.")
    if not os.path.exists(resource_packs_folder):
        try:
            os.makedirs(resource_packs_folder)
            logger.info(f"Cartella resource_packs creata in {resource_packs_folder}")
        except OSError as e:
            raise ResourcePackError(f"Impossibile creare la cartella dei resource pack {resource_packs_folder}: {e}")


    base, ext = os.path.splitext(original_filename)
    if ext.lower() == '.mcpack':
        target_filename = base + ".zip"
    elif ext.lower() == '.zip':
        target_filename = original_filename
    else:
        raise ResourcePackError(f"Formato file non supportato: {original_filename}. Deve essere .zip o .mcpack.")
    
    destination_path = os.path.join(resource_packs_folder, target_filename)
    
    # Gestisci la sovrascrittura se il file esiste già
    if os.path.exists(destination_path):
        logger.warning(f"Il file '{target_filename}' esiste già in {resource_packs_folder}. Sarà sovrascritto.")
        try:
            os.remove(destination_path)
        except OSError as e:
            raise ResourcePackError(f"Impossibile sovrascrivere il file esistente '{target_filename}': {e}")

    try:
        shutil.move(source_file_path, destination_path)
        logger.info(f"File '{original_filename}' spostato in '{destination_path}'.")

        pack_uuid, pack_version, pack_name = _extract_manifest_details(destination_path)
        if not pack_uuid or not pack_version: # pack_name può essere un fallback
             raise ResourcePackError("Impossibile estrarre i dettagli del manifest dal pacchetto installato.")
        
        return destination_path, pack_uuid, pack_version, pack_name

    except FileNotFoundError:
        logger.error(f"File sorgente non trovato: {source_file_path}")
        raise ResourcePackError("File sorgente del pacchetto non trovato.")
    except Exception as e:
        logger.error(f"Errore durante l'installazione del pacchetto '{original_filename}': {e}", exc_info=True)
        if os.path.exists(destination_path) and source_file_path != destination_path:
            pass # Non rimuovere automaticamente, potrebbe essere un file legittimo
        raise ResourcePackError(f"Errore installazione pacchetto: {e}")


def manage_world_resource_packs_json(
    world_name_target: str, 
    pack_uuid_to_add: Optional[str] = None,
    pack_version_to_add: Optional[List[int]] = None,
    pack_uuid_to_remove: Optional[str] = None,
    add_to_top: bool = False # False significa aggiungi alla fine (priorità più alta)
) -> List[Dict[str, Any]]:
    """
    Legge, modifica e scrive world_resource_packs.json.
    Aggiunge o rimuove un pacchetto. Se si aggiunge, pack_uuid_to_add e pack_version_to_add sono richiesti.
    Se si rimuove, pack_uuid_to_remove è richiesto.
    Restituisce la lista aggiornata dei pacchetti attivi.
    """
    if not world_name_target:
        raise ResourcePackError("Nome del mondo non specificato per la gestione dei resource pack.")

    json_path = get_world_specific_resource_packs_json_path(world_name_target)
    if not json_path:
        raise ResourcePackError(f"Impossibile trovare il file world_resource_packs.json per il mondo '{world_name_target}'.")

    active_packs: List[Dict[str, Any]] = []
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f: # Specifica encoding
                active_packs = json.load(f)
            if not isinstance(active_packs, list):
                logger.warning(f"{json_path} non contiene una lista JSON valida. Sarà sovrascritto.")
                active_packs = []
        except json.JSONDecodeError:
            logger.warning(f"Errore di decodifica JSON in {json_path}. Il file sarà sovrascritto se si apportano modifiche.")
            active_packs = []
        except Exception as e: # Cattura altre eccezioni di I/O
            logger.error(f"Errore durante la lettura di {json_path}: {e}", exc_info=True)
            raise ResourcePackError(f"Errore durante la lettura di world_resource_packs.json: {e}")

    else:
        logger.info(f"{json_path} non trovato. Sarà creato se si aggiunge un pacchetto.")
        active_packs = []
    
    modified = False

    if pack_uuid_to_remove:
        original_len = len(active_packs)
        active_packs = [p for p in active_packs if p.get('pack_id') != pack_uuid_to_remove]
        if len(active_packs) < original_len:
            logger.info(f"Pacchetto {pack_uuid_to_remove} rimosso da world_resource_packs.json per '{world_name_target}'.")
            modified = True

    if pack_uuid_to_add and pack_version_to_add:
        existing_pack_index = -1
        for i, pack_data in enumerate(active_packs):
            if pack_data.get('pack_id') == pack_uuid_to_add:
                existing_pack_index = i
                break
        
        new_pack_entry = {"pack_id": pack_uuid_to_add, "version": pack_version_to_add}

        if existing_pack_index != -1:
            if active_packs[existing_pack_index].get('version') == pack_version_to_add:
                logger.info(f"Pacchetto {pack_uuid_to_add} versione {pack_version_to_add} già attivo in '{world_name_target}'. Nessuna modifica.")
            else:
                logger.info(f"Pacchetto {pack_uuid_to_add} trovato con versione diversa. Aggiornamento versione a {pack_version_to_add} in '{world_name_target}'.")
                active_packs[existing_pack_index]['version'] = pack_version_to_add
                modified = True
        else:
            if add_to_top: 
                active_packs.insert(0, new_pack_entry)
            else: 
                active_packs.append(new_pack_entry)
            logger.info(f"Pacchetto {pack_uuid_to_add} versione {pack_version_to_add} aggiunto a world_resource_packs.json per '{world_name_target}'.")
            modified = True

    if modified:
        try:
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            with open(json_path, 'w', encoding='utf-8') as f: # Specifica encoding
                json.dump(active_packs, f, indent=2) 
            logger.info(f"world_resource_packs.json per '{world_name_target}' aggiornato con successo.")
        except IOError as e:
            logger.error(f"Errore di I/O durante la scrittura di {json_path}: {e}")
            raise ResourcePackError(f"Impossibile scrivere su world_resource_packs.json: {e}")
        except Exception as e: # Cattura altre eccezioni
            logger.error(f"Errore imprevisto durante la scrittura di {json_path}: {e}", exc_info=True)
            raise ResourcePackError(f"Errore imprevisto durante l'aggiornamento di world_resource_packs.json: {e}")
            
    return active_packs


def get_active_resource_packs(world_name_target: str) -> List[Dict[str, Any]]:
    """Legge e restituisce la lista dei resource pack attivi per il mondo."""
    json_path = get_world_specific_resource_packs_json_path(world_name_target)
    if not json_path or not os.path.exists(json_path):
        return []
    try:
        with open(json_path, 'r', encoding='utf-8') as f: # Specifica encoding
            packs = json.load(f)
        return packs if isinstance(packs, list) else []
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Errore leggendo {json_path}: {e}")
        return []
    except Exception as e: # Cattura altre eccezioni
        logger.error(f"Errore imprevisto leggendo {json_path}: {e}", exc_info=True)
        return []

# Funzioni aggiuntive che potrebbero essere utili (da implementare se necessario):
# def list_available_resource_packs() -> List[Dict[str, Any]]:
#     """Scansiona la cartella resource_packs e restituisce una lista di tutti i pacchetti disponibili."""
#     pass

# def get_resource_pack_details(pack_uuid: str) -> Optional[Dict[str, Any]]:
#     """Ottiene i dettagli di un resource pack specifico dal suo UUID."""
#     pass
