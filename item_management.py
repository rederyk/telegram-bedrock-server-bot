# minecraft_telegram_bot/item_management.py
import os
import json
import requests # Mantenuto sincrono per semplicità in questo modulo isolato
from config import ITEMS_FILE, get_logger

logger = get_logger(__name__)

def fetch_items_from_source():
    """Scarica gli item dalla fonte online."""
    try:
        logger.info("Tentativo di scaricare la lista item da GrahamEdgecombe...")
        r = requests.get("http://minecraft-ids.grahamedgecombe.com/items.json", timeout=10)
        r.raise_for_status()
        items_data = []
        for item in r.json():
            if isinstance(item, dict) and "text_type" in item and "name" in item:
                items_data.append({
                    "id": f"minecraft:{item['text_type']}",
                    "name": item["name"]
                })
        with open(ITEMS_FILE, "w") as f:
            json.dump(items_data, f, indent=2)
        logger.info(f"Scaricati e salvati {len(items_data)} item.")
        return items_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Errore HTTP scaricamento item list: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"Errore JSON decodificando item list: {e}")
    except Exception as e:
        logger.error(f"Errore generico scaricamento item list: {e}")
    return []

def load_items_from_file():
    """Carica gli item dal file locale, se esiste."""
    if os.path.exists(ITEMS_FILE):
        try:
            with open(ITEMS_FILE) as f:
                items = json.load(f)
                logger.info(f"Caricati {len(items)} item da {ITEMS_FILE}.")
                return items
        except Exception as e:
            logger.error(f"Errore caricamento {ITEMS_FILE}: {e}")
    return None

# Variabile globale per gli items, caricata all'avvio del modulo
ITEMS = load_items_from_file()
if ITEMS is None: # Se il file non esiste o è corrotto, tenta di scaricarli
    logger.info(f"{ITEMS_FILE} non trovato o illeggibile, tento lo scaricamento...")
    ITEMS = fetch_items_from_source()
    if not ITEMS: # Se anche lo scaricamento fallisce
        logger.warning("Impossibile caricare o scaricare la lista degli item. Alcune funzionalità potrebbero essere limitate.")
        ITEMS = [] # Inizializza a lista vuota per evitare errori


def get_items():
    """Restituisce la lista degli item attualmente caricata."""
    return ITEMS

def refresh_items():
    """Forza l'aggiornamento della lista degli item dalla fonte."""
    global ITEMS
    new_items = fetch_items_from_source()
    if new_items: # Aggiorna solo se lo scaricamento ha avuto successo
        ITEMS = new_items
    return ITEMS