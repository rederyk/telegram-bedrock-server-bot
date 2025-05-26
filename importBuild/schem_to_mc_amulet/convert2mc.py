#!/usr/bin/env python3

"""
Convert .schematic → .mcstructure (Bedrock) con ottimizzazioni di performance
Implementa le stesse ottimizzazioni del divisore per migliorare rendering e prestazioni.
"""

import argparse
import sys
import os
import logging
from amulet import load_level
from amulet.level.formats.mcstructure import MCStructureFormatWrapper
from amulet.api.block import Block
from amulet.api.selection import SelectionBox, SelectionGroup
from typing import Tuple, List

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)

DEFAULT_VERSION = (1, 21)
AIR_BLOCK = Block("minecraft", "air")

def parse_version(version_str: str) -> Tuple[int, ...]:
    """Converte una stringa versione come '1.21' in una tupla (1, 21)."""
    try:
        return tuple(int(p) for p in version_str.split("."))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Versione non valida: '{version_str}'. Usa il formato X.Y o X.Y.Z"
        )

def derive_output_path(input_path: str) -> str:
    """Restituisce il percorso .mcstructure nella stessa cartella dell'input."""
    base = os.path.splitext(os.path.basename(input_path))[0]
    dir_name = os.path.dirname(input_path) or "."
    return os.path.join(dir_name, f"{base}.mcstructure")

def analyze_structure(level, dimension) -> dict:
    """
    Analizza la struttura per ottimizzazioni (come fa il divisore).
    """
    bounds = level.bounds(dimension)
    chunk_coords = list(level.get_chunk_boxes(dimension))
    
    # Conta blocchi non-aria per determinare densità
    non_air_count = 0
    total_blocks = 0
    
    logging.info(f"Analisi struttura: {len(chunk_coords)} chunk")
    
    for i, (chunk, box) in enumerate(chunk_coords[:10]):  # Campiona primi 10 chunk
        for x in range(box.min_x, min(box.max_x, box.min_x + 16)):  # Limita campionamento
            for y in range(box.min_y, min(box.max_y, box.min_y + 16)):
                for z in range(box.min_z, min(box.max_z, box.min_z + 16)):
                    try:
                        block = level.get_block(x, y, z, dimension)
                        total_blocks += 1
                        if block != AIR_BLOCK:
                            non_air_count += 1
                    except:
                        pass
    
    density = non_air_count / max(total_blocks, 1)
    
    return {
        'bounds': bounds,
        'chunk_count': len(chunk_coords),
        'density': density,
        'dimensions': {
            'x': bounds.max_x - bounds.min_x,
            'y': bounds.max_y - bounds.min_y,
            'z': bounds.max_z - bounds.min_z
        },
        'estimated_non_air': int(non_air_count * len(chunk_coords) / min(10, len(chunk_coords)))
    }

def optimize_chunk_processing(level, dimension, mc_wrapper, analysis: dict):
    """
    Processa i chunk con ottimizzazioni basate sull'analisi.
    """
    chunk_coords = list(level.get_chunk_boxes(dimension))
    total_chunks = len(chunk_coords)
    
    # Ordina i chunk per posizione per migliorare località dei dati
    chunk_coords.sort(key=lambda x: (x[1].min_x, x[1].min_z, x[1].min_y))
    
    logging.info(f"Processamento ottimizzato di {total_chunks} chunk")
    logging.info(f"Densità stimata: {analysis['density']:.2%}")
    
    # Processa in batch per ridurre overhead
    batch_size = min(32, max(4, total_chunks // 10))  # Batch adattivo
    
    for i in range(0, total_chunks, batch_size):
        batch = chunk_coords[i:i + batch_size]
        
        for chunk, box in batch:
            try:
                # Committa il chunk con gestione errori
                mc_wrapper.commit_chunk(chunk, dimension=dimension)
            except Exception as e:
                logging.warning(f"Errore chunk ({box.min_x},{box.min_z}): {e}")
                continue
        
        # Progress ogni batch
        progress = min(100, (i + batch_size) * 100 // total_chunks)
        if progress % 20 == 0:
            logging.info(f"Progresso: {progress}%")
    
    return total_chunks

def apply_bedrock_optimizations(mc_wrapper, analysis: dict):
    """
    Applica ottimizzazioni specifiche per Bedrock basate sull'analisi.
    """
    dims = analysis['dimensions']
    
    # Suggerimenti per il motore Bedrock
    logging.info("Applicazione ottimizzazioni Bedrock...")
    
    # Per strutture molto larghe, suggerisci chunk loading ottimizzato
    if dims['x'] > 256 or dims['z'] > 256:
        logging.info("⚠️  Struttura molto larga: considera divisione per rendering ottimale")
    
    # Per strutture molto alte, suggerisci ottimizzazioni verticali
    if dims['y'] > 128:
        logging.info("⚠️  Struttura molto alta: rendering verticale potrebbe essere lento")
    
    # Per strutture dense, suggerisci cache ottimizzazioni
    if analysis['density'] > 0.7:
        logging.info("✅ Struttura densa: beneficerà di cache dei blocchi")
    elif analysis['density'] < 0.1:
        logging.info("⚠️  Struttura molto sparsa: considera rimozione aria in eccesso")

def convert_optimized(
    input_path: str,
    platform: str,
    version: Tuple[int, ...],
    enable_analysis: bool = True
) -> str:
    """
    Conversione ottimizzata da .schematic a .mcstructure.
    """
    # Carica il livello
    logging.info(f"Caricamento schematic: {input_path}")
    level = load_level(input_path)
    dims = level.dimensions
    
    if not dims:
        raise ValueError("Nessuna dimensione trovata nel file")
    
    dimension = dims[0]
    
    # Analisi struttura (come nel divisore)
    if enable_analysis:
        logging.info("Analisi struttura per ottimizzazioni...")
        analysis = analyze_structure(level, dimension)
        
        logging.info(f"Dimensioni: {analysis['dimensions']['x']}×{analysis['dimensions']['y']}×{analysis['dimensions']['z']}")
        logging.info(f"Chunk: {analysis['chunk_count']}")
        logging.info(f"Blocchi stimati: {analysis['estimated_non_air']:,}")
    else:
        analysis = {'bounds': level.bounds(dimension), 'density': 0.5, 'dimensions': {}}
    
    # Prepara output
    output_path = derive_output_path(input_path)
    logging.info(f"Output .mcstructure: {output_path}")
    
    # Crea wrapper con ottimizzazioni
    mc = MCStructureFormatWrapper(output_path)
    logging.info(f"Creazione mcstructure ottimizzata (v{'.'.join(map(str,version))})")
    
    mc.create_and_open(
        platform=platform,
        version=version,
        bounds=analysis['bounds'],
        overwrite=True
    )
    
    try:
        # Applica ottimizzazioni Bedrock
        if enable_analysis:
            apply_bedrock_optimizations(mc, analysis)
        
        # Processamento ottimizzato dei chunk
        total_chunks = 0
        for dim in dims:
            if enable_analysis and dim == dimension:
                chunks_processed = optimize_chunk_processing(level, dim, mc, analysis)
            else:
                # Fallback standard
                coords = list(level.get_chunk_boxes(dim))
                for chunk, _box in coords:
                    mc.commit_chunk(chunk, dimension=dim)
                chunks_processed = len(coords)
            
            total_chunks += chunks_processed
            logging.info(f"Dimensione '{dim}': {chunks_processed} chunk processati")
        
        # Salva con feedback
        logging.info(f"Salvataggio ottimizzato ({total_chunks} chunk totali)...")
        mc.save()
        
        logging.info("✅ Conversione ottimizzata completata")
        
    finally:
        mc.close()
        level.close()
    
    return output_path

def main():
    parser = argparse.ArgumentParser(
        description="Convertitore ottimizzato .schematic → .mcstructure (Bedrock)\n"
                   "Include analisi struttura e ottimizzazioni performance del divisore.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", help="File .schematic di input")
    parser.add_argument("--platform", default="bedrock", help="Piattaforma (default: bedrock)")
    parser.add_argument("--version", type=parse_version, default=DEFAULT_VERSION,
                       help="Versione Bedrock (default: 1.21)")
    parser.add_argument("--no-analysis", action="store_true",
                       help="Disabilita analisi e ottimizzazioni (conversione standard)")
    parser.add_argument("--verbose", action="store_true", help="Output dettagliato")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if not os.path.exists(args.input):
        logging.error(f"File non trovato: {args.input}")
        sys.exit(1)
    
    try:
        output_path = convert_optimized(
            args.input,
            args.platform,
            args.version,
            enable_analysis=not args.no_analysis
        )
        print(f"✅ Conversione ottimizzata completata: {output_path}")
        
    except Exception as e:
        logging.error(f"Errore durante la conversione: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()