#!/usr/bin/env python3

import argparse
import logging
import os
import math
import traceback

# Importazioni Amulet
try:
    import amulet
    from amulet.api.level import World
except ImportError as e:
    print(f"Errore: Amulet-Core non trovato: {e}")
    print("Installa con: pip install amulet-core amulet-nbt")
    exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

def parse_coordinates(coords_str):
    """Converte una stringa "x,y,z" in una tupla di float."""
    try:
        parts = coords_str.split(',')
        if len(parts) == 3:
            return float(parts[0]), float(parts[1]), float(parts[2])
        else:
            logger.error(f"Formato coordinate non valido: '{coords_str}'. Usare x,y,z.")
            return None
    except ValueError:
        logger.error(f"Coordinate non numeriche: '{coords_str}'.")
        return None

def get_chunk_coords(world_x, world_z):
    """Converte coordinate mondo in coordinate chunk."""
    chunk_x = int(math.floor(world_x / 16))
    chunk_z = int(math.floor(world_z / 16))
    return chunk_x, chunk_z

def get_py_repr(tag):
    """Helper to get a python representation from an NBT tag."""
    if hasattr(tag, 'py_list'):
        return tag.py_list
    elif hasattr(tag, 'py_dict'):
        return tag.py_dict
    elif hasattr(tag, 'py_str'):
        return tag.py_str
    elif hasattr(tag, 'py_int'):
        return tag.py_int
    elif hasattr(tag, 'py_float'):
        return tag.py_float
    elif hasattr(tag, 'value'):
        return tag.value
    return str(tag)

def extract_float_value(value):
    """Estrai valore float da vari tipi di tag NBT."""
    if hasattr(value, 'py_float'):
        return value.py_float
    elif hasattr(value, 'value'):
        return float(value.value)
    else:
        return float(value)

def yaw_to_direction(yaw_degrees):
    """Converte yaw in direzione cardinale."""
    # Normalizza yaw a range 0-360
    normalized_yaw = yaw_degrees % 360
    if normalized_yaw < 0:
        normalized_yaw += 360
    
    # Converti a direzioni cardinali (sistema coordinate Minecraft)
    if 337.5 <= normalized_yaw or normalized_yaw < 22.5:
        return "Sud", normalized_yaw
    elif 22.5 <= normalized_yaw < 67.5:
        return "Sud-Ovest", normalized_yaw
    elif 67.5 <= normalized_yaw < 112.5:
        return "Ovest", normalized_yaw
    elif 112.5 <= normalized_yaw < 157.5:
        return "Nord-Ovest", normalized_yaw
    elif 157.5 <= normalized_yaw < 202.5:
        return "Nord", normalized_yaw
    elif 202.5 <= normalized_yaw < 247.5:
        return "Nord-Est", normalized_yaw
    elif 247.5 <= normalized_yaw < 292.5:
        return "Est", normalized_yaw
    elif 292.5 <= normalized_yaw < 337.5:
        return "Sud-Est", normalized_yaw
    else:
        return f"Intermedio", normalized_yaw

def pitch_to_inclination(pitch_degrees):
    """Converte pitch in descrizione inclinazione."""
    if abs(pitch_degrees) < 5:
        return "dritta/orizzontale"
    elif pitch_degrees < -45:
        return "molto in alto"
    elif pitch_degrees < -15:
        return "in alto"
    elif pitch_degrees > 45:
        return "molto in basso"
    elif pitch_degrees > 15:
        return "in basso"
    else:
        return f"leggermente inclinata ({pitch_degrees:.1f}°)"

def analyze_rotation_detailed(nbt_compound, entity_id):
    """Analizza in dettaglio la rotazione di un'entità."""
    if not nbt_compound or 'Rotation' not in nbt_compound:
        logger.info("    ❌ Nessun dato di rotazione disponibile")
        return None, None
    
    rotation_tag = nbt_compound['Rotation']
    logger.info(f"    🔍 Tipo tag rotazione: {type(rotation_tag)}")
    
    # Estrai dati rotazione
    rotation_data = None
    if hasattr(rotation_tag, 'py_list'):
        rotation_data = rotation_tag.py_list
    elif hasattr(rotation_tag, 'value'):
        rotation_data = rotation_tag.value
    elif hasattr(rotation_tag, '__iter__'):
        rotation_data = list(rotation_tag)
    
    if not rotation_data or len(rotation_data) < 2:
        logger.warning(f"    ⚠️ Dati rotazione insufficienti: {rotation_data}")
        return None, None
    
    try:
        yaw_raw = rotation_data[0]
        pitch_raw = rotation_data[1]
        
        logger.info(f"    🎯 Valori grezzi: Yaw={yaw_raw} (tipo: {type(yaw_raw)}), Pitch={pitch_raw} (tipo: {type(pitch_raw)})")
        
        # Converti a float
        yaw = extract_float_value(yaw_raw)
        pitch = extract_float_value(pitch_raw)
        
        logger.info(f"    ✅ Rotazione estratta:")
        logger.info(f"      📐 Yaw (orizzontale): {yaw}°")
        logger.info(f"      📐 Pitch (verticale): {pitch}°")
        
        # Interpretazione dettagliata
        direction, normalized_yaw = yaw_to_direction(yaw)
        inclination = pitch_to_inclination(pitch)
        
        logger.info(f"    🧭 INTERPRETAZIONE:")
        logger.info(f"      🎯 Direzione: {direction} ({normalized_yaw:.1f}° normalizzato)")
        logger.info(f"      📏 Inclinazione: {inclination}")
        
        # Info specifica per armor stand
        if 'armor_stand' in str(entity_id).lower():
            logger.info(f"    🎭 INFO ARMOR STAND:")
            logger.info(f"      → L'armor stand guarda verso {direction}")
            logger.info(f"      → Testa/corpo orientati a {inclination}")
            
            # Suggerimenti per debugging
            if abs(yaw) > 180:
                logger.info(f"      💡 Nota: Yaw {yaw}° è equivalente a {yaw % 360}°")
        
        return yaw, pitch
        
    except Exception as e:
        logger.error(f"    ❌ Errore conversione rotazione: {e}")
        logger.error(f"    📋 Traceback: {traceback.format_exc()}")
        return None, None

def analyze_armor_stand_pose(nbt_compound):
    """Analizza la posa dell'armor stand."""
    if not nbt_compound:
        return
    
    logger.info(f"    🎭 ANALISI POSA ARMOR STAND:")
    
    # Posa generale
    if 'Pose' in nbt_compound:
        pose_tag = nbt_compound['Pose']
        pose_data = get_py_repr(pose_tag)
        logger.info(f"      🤸 Posa: {pose_data}")
    
    # Attributi specifici armor stand
    armor_stand_attrs = {
        'ShowArms': '🦾 Mostra braccia',
        'NoBasePlate': '🔲 Senza base',
        'NoGravity': '🪶 Senza gravità',
        'Silent': '🔇 Silenzioso',
        'Invulnerable': '🛡️ Invulnerabile',
        'PersistenceRequired': '📌 Persistenza richiesta',
        'CustomName': '🏷️ Nome personalizzato',
        'CustomNameVisible': '👁️ Nome visibile'
    }
    
    found_attrs = False
    for attr_key, description in armor_stand_attrs.items():
        if attr_key in nbt_compound:
            found_attrs = True
            attr_value = get_py_repr(nbt_compound[attr_key])
            logger.info(f"      {description}: {attr_value}")
    
    if not found_attrs:
        logger.info(f"      ℹ️ Nessun attributo speciale armor stand trovato")

def explore_chunk(world_path, coordinates_str):
    """Esplora TUTTO in un singolo chunk alle coordinate specificate."""
    coords = parse_coordinates(coordinates_str)
    if not coords:
        return
    
    x_coord, y_coord, z_coord = coords  
    chunk_x, chunk_z = get_chunk_coords(x_coord, z_coord)
    
    logger.info(f"=== ESPLORAZIONE CHUNK ===")
    logger.info(f"Coordinate mondo input: ({x_coord}, {y_coord}, {z_coord})")
    logger.info(f"Coordinate chunk: ({chunk_x}, {chunk_z})")
    logger.info("=" * 40)
    
    world_obj = None  
    try:
        world_obj = amulet.load_level(world_path)
        logger.info(f"Mondo caricato: {world_path}")
        logger.info(f"Tipo mondo: {type(world_obj.level_wrapper)}")
    except Exception as e:
        logger.error(f"Errore caricamento mondo: {e}")
        logger.error(traceback.format_exc())
        return
    
    try:
        logger.info(f"Dimensioni nel mondo: {world_obj.dimensions}")
        dimension = world_obj.dimensions[0] if world_obj.dimensions else None
        if not dimension:
            logger.error("Nessuna dimensione trovata!")
            return  
            
        logger.info(f"Usando dimensione: {dimension}")
        
        if not world_obj.has_chunk(chunk_x, chunk_z, dimension):
            logger.warning(f"Chunk ({chunk_x}, {chunk_z}) non esiste in dimensione {dimension}!")
            return  
        
        logger.info(f"✅ Chunk ({chunk_x}, {chunk_z}) esiste")
        chunk = world_obj.get_chunk(chunk_x, chunk_z, dimension)
        logger.info(f"✅ Chunk caricato: {type(chunk)}")
        
        logger.info("\n" + "=" * 50)
        logger.info("ANALISI CHUNK")
        logger.info("=" * 50)
        
        logger.info("\n🎯 RICERCA ENTITÀ:")
        entities_found = []
        
        # Cerca entità in vari attributi
        entity_sources = ['entities', '_native_entities', 'entity_data']
        for source_name in entity_sources:
            if hasattr(chunk, source_name):
                try:
                    source_entities = getattr(chunk, source_name)
                    if hasattr(source_entities, '__iter__') and not isinstance(source_entities, (str, dict, bytes)):
                        entity_list = list(source_entities)
                        if entity_list:
                            logger.info(f"  ✅ Trovate entità in chunk.{source_name} ({len(entity_list)} elementi)")
                            entities_found.extend(entity_list)
                            break
                except Exception as e:
                    logger.debug(f"  ⚠️ Errore accesso {source_name}: {e}")
        
        if not entities_found:
            logger.info("  ℹ️ Controllo attributi alternativi per entità...")
            for attr_name in dir(chunk):
                if 'entit' in attr_name.lower() and not attr_name.startswith('__'):
                    try:
                        potential_entities = getattr(chunk, attr_name)
                        if hasattr(potential_entities, '__iter__') and not isinstance(potential_entities, (str, dict, bytes)):
                            list_of_entities = list(potential_entities)  
                            if list_of_entities and hasattr(list_of_entities[0], 'nbt'):  
                                logger.info(f"  ✅ Trovate entità in chunk.{attr_name} ({len(list_of_entities)} elementi)")
                                entities_found.extend(list_of_entities)
                                break  
                    except Exception:
                        pass

        if entities_found:
            logger.info(f"\n🎉 ENTITÀ TROVATE: {len(entities_found)}")
            logger.info("=" * 30)
            
            for i, entity_obj in enumerate(entities_found):  
                logger.info(f"\n🔸 ENTITÀ #{i+1} (Tipo: {type(entity_obj)})")
                try:
                    # Informazioni base entità
                    entity_id_val = getattr(entity_obj, 'namespaced_name', 'N/A')
                    entity_pos_val = [
                        getattr(entity_obj, 'x', 'N/A'), 
                        getattr(entity_obj, 'y', 'N/A'), 
                        getattr(entity_obj, 'z', 'N/A')
                    ]

                    logger.info(f"  🆔 Identificatore: {entity_id_val}")
                    logger.info(f"  📍 Posizione: {entity_pos_val}")

                    # Analisi NBT
                    amulet_nbt_tag = getattr(entity_obj, 'nbt', None)
                    nbt_compound = {}

                    if amulet_nbt_tag:
                        try:
                            if hasattr(amulet_nbt_tag, 'compound'):
                                nbt_compound = amulet_nbt_tag.compound
                                logger.info(f"  ⚙️  NBT compound keys: {list(nbt_compound.keys()) if nbt_compound else 'Nessuno'}")
                            elif isinstance(amulet_nbt_tag, dict):  
                                nbt_compound = amulet_nbt_tag
                                logger.info(f"  ⚙️  NBT dict keys: {list(nbt_compound.keys()) if nbt_compound else 'Nessuno'}")
                            else:
                                logger.warning(f"  ⚠️ NBT tipo inaspettato: {type(amulet_nbt_tag)}")
                        except Exception as nbt_e:
                            logger.warning(f"  ⚠️ Errore accesso NBT: {nbt_e}")
                    else:
                        logger.warning("  ⚠️ Attributo 'nbt' non trovato")

                    # Analisi rotazione dettagliata
                    logger.info(f"  🧭 ANALISI ROTAZIONE:")
                    yaw, pitch = analyze_rotation_detailed(nbt_compound, entity_id_val)

                    # Analisi specifica per armor stand
                    if 'armor_stand' in str(entity_id_val).lower():
                        logger.info(f"  🎯 *** ARMOR STAND RILEVATO! ***")
                        
                        # Proprietà specifiche armor stand
                        logger.info(f"  🔧 PROPRIETÀ ARMOR STAND:")
                        
                        # Nome personalizzato
                        custom_name = ''
                        if 'CustomName' in nbt_compound:
                            custom_name_tag = nbt_compound['CustomName']
                            custom_name = get_py_repr(custom_name_tag)
                        logger.info(f"    🏷️ Nome: {custom_name if custom_name else '(Nessuno)'}")

                        # Invisibilità
                        invisible = False
                        if 'Invisible' in nbt_compound:
                            invisible_tag = nbt_compound['Invisible']
                            invisible = bool(get_py_repr(invisible_tag))
                        logger.info(f"    👻 Invisibile: {invisible}")

                        # Marker
                        marker = False
                        if 'Marker' in nbt_compound:
                            marker_tag = nbt_compound['Marker']
                            marker = bool(get_py_repr(marker_tag))
                        logger.info(f"    🔒 Marker: {marker}")

                        # Analisi posa dettagliata
                        analyze_armor_stand_pose(nbt_compound)

                    # Altri campi interessanti
                    logger.info("  🔍 Altri campi NBT interessanti:")
                    interesting_fields = [
                        'CustomName', 'CustomNameVisible', 'Invisible', 'Marker',  
                        'Pose', 'ArmorItems', 'HandItems', 'Health', 'Variant', 
                        'SkinID', 'Color', 'Strength', 'TargetID', 'OwnerNew', 'Saddled'
                    ]
                    
                    found_interesting = False
                    for field_key in interesting_fields:
                        if field_key in nbt_compound:
                            found_interesting = True
                            field_value = get_py_repr(nbt_compound[field_key])
                            logger.info(f"    🔧 {field_key}: {str(field_value)[:200]}")
                    
                    if not found_interesting:
                        logger.info("    ℹ️ Nessun campo predefinito interessante trovato")

                except Exception as e_detail:
                    logger.error(f"  ❌ Errore analisi entità #{i+1}: {e_detail}")
                    logger.error(f"  📋 Traceback: {traceback.format_exc()}")
        else:
            logger.info("\n❌ NESSUNA ENTITÀ TROVATA NEL CHUNK")
        
        # Informazioni sui blocchi
        logger.info(f"\n🧱 INFORMAZIONI BLOCCHI:")
        try:
            if hasattr(chunk, 'blocks'): 
                logger.info(f"  📊 Blocks: {type(chunk.blocks)}")
            
            if hasattr(chunk, 'block_entities'):
                be_list = []
                if hasattr(chunk.block_entities, '__iter__'):
                    be_list = list(chunk.block_entities)  
                logger.info(f"  📊 Block entities: {type(chunk.block_entities)} ({len(be_list)} elementi)")
                
                if be_list:
                    logger.info(f"  🔸 Prime {min(3, len(be_list))} block entities:")
                    for i, be in enumerate(be_list[:3]):
                        be_id = getattr(be, 'id', 'N/A')
                        be_pos = f"({getattr(be, 'x', '?')},{getattr(be, 'y', '?')},{getattr(be, 'z', '?')})"
                        logger.info(f"    {i+1}. ID: {be_id}, Pos: {be_pos}")
            
            if hasattr(chunk, 'biomes'): 
                logger.info(f"  📊 Biomes: {type(chunk.biomes)}")
            
            if hasattr(chunk, 'status'):
                status_val = getattr(chunk, 'status', 'N/A')
                logger.info(f"  📊 Status: {status_val}")
            
            if hasattr(chunk, 'changed'): 
                logger.info(f"  📊 Changed: {getattr(chunk, 'changed', 'N/A')}")

        except Exception as e:
            logger.error(f"  ❌ Errore analisi blocchi: {e}")
            logger.error(f"  📋 Traceback: {traceback.format_exc()}")
            
    except Exception as e:
        logger.error(f"Errore generale durante l'esplorazione del chunk: {e}")
        logger.error(f"Traceback completo: {traceback.format_exc()}")
    finally:
        if world_obj:  
            try:
                world_obj.close()
                logger.info("✅ Mondo chiuso correttamente")
            except Exception as e_close:
                logger.error(f"❌ Errore chiusura mondo: {e_close}")

def main():
    parser = argparse.ArgumentParser(
        description="Esplora TUTTO in un chunk Bedrock alle coordinate specificate con analisi rotazione migliorata"
    )
    parser.add_argument("world_path", help="Percorso cartella mondo Bedrock")
    parser.add_argument("coordinates", help="Coordinate 'x,y,z'")
    parser.add_argument("--verbose", "-v", action="store_true", help="Output più dettagliato (DEBUG)")
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("🐛 Logging verboso abilitato")
    
    if not os.path.isdir(args.world_path):
        logger.error(f"❌ Percorso mondo non valido: {args.world_path}")
        return

    explore_chunk(args.world_path, args.coordinates)

if __name__ == "__main__":
    main()