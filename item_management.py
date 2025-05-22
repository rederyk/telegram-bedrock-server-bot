# minecraft_telegram_bot/item_management.py
import os
import json
import requests
from config import ITEMS_FILE, get_logger

logger = get_logger(__name__)

def fetch_items_from_source():
    try:
        logger.info("🔗📦 Download lista item da GrahamEdgecombe...")
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
        logger.info(f"📦✅ Scaricati e salvati {len(items_data)} item.")
        return items_data
    except requests.exceptions.RequestException as e:
        logger.error(f"🔗❌ Errore HTTP download item: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"📄❌ Errore JSON decode item: {e}")
    except Exception as e:
        logger.error(f"🆘 Errore download item: {e}")
    return []

def load_items_from_file():
    if os.path.exists(ITEMS_FILE):
        try:
            with open(ITEMS_FILE) as f:
                items = json.load(f)
                logger.info(f"📦 Caricati {len(items)} item da {ITEMS_FILE}.")
                return items
        except Exception as e:
            logger.error(f"❌ Errore caricamento {ITEMS_FILE}: {e}")
    return None

ITEMS = load_items_from_file()
if ITEMS is None:
    logger.info(f"❓ {ITEMS_FILE} non trovato/illeggibile, tento download...")
    ITEMS = fetch_items_from_source()
    if not ITEMS:
        logger.warning("⚠️  Impossibile caricare/scaricare item. Funzionalità limitate.")
        ITEMS = []

def get_items():
    return ITEMS

def refresh_items():
    global ITEMS
    new_items = fetch_items_from_source()
    if new_items:
        ITEMS = new_items
    return ITEMS