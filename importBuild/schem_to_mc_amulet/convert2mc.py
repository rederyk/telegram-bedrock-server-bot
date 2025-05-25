#!/usr/bin/env python3
"""
Convert .schematic → .mcstructure (Bedrock) usando Amulet-Core.
Salva nella stessa cartella del file di input, mantenendo il nome base e cambiando estensione in .mcstructure.
Usa di default la versione Bedrock 1.21, con la possibilità di specificarne una diversa.
"""

import argparse
import sys
import os
import logging
from amulet import load_level
from amulet.level.formats.mcstructure import MCStructureFormatWrapper
from typing import Tuple

# Configurazione logging per output leggibile
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)

DEFAULT_VERSION = (1, 21)  # Default Bedrock version


def parse_version(version_str: str) -> Tuple[int, ...]:
    """
    Converte una stringa versione come '1.21' in una tupla (1, 21).
    """
    try:
        return tuple(int(p) for p in version_str.split("."))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Versione non valida: '{version_str}'. Usa il formato X.Y o X.Y.Z"
        )


def derive_output_path(input_path: str) -> str:
    """
    Restituisce il percorso .mcstructure nella stessa cartella dell'input.
    """
    base = os.path.splitext(os.path.basename(input_path))[0]
    dir_name = os.path.dirname(input_path) or "."
    return os.path.join(dir_name, f"{base}.mcstructure")


def convert(
    input_path: str,
    platform: str,
    version: Tuple[int, ...]
) -> str:
    """
    Esegue la conversione da .schematic a .mcstructure.
    """
    # Carica il livello
    logging.info(f"Caricamento schematic: {input_path}")
    level = load_level(input_path)
    dims = level.dimensions

    # Prepara output
    output_path = derive_output_path(input_path)
    logging.info(f"Output .mcstructure: {output_path}")

    # Crea e apre il wrapper .mcstructure
    mc = MCStructureFormatWrapper(output_path)
    logging.info(
        f"Creazione mcstructure (platform={platform}, version={'.'.join(map(str,version))})"
    )
    mc.create_and_open(
        platform=platform,
        version=version,
        bounds=level.bounds(dims[0]),
        overwrite=True
    )

    # Conta e trasferisce i chunk
    total_chunks = 0
    for dim in dims:
        coords = list(level.get_chunk_boxes(dim))
        num = len(coords)
        logging.info(f"Dimensione '{dim}': {num} chunk da convertire")
        for idx, (chunk, _box) in enumerate(coords, start=1):
            mc.commit_chunk(chunk, dimension=dim)
            logging.debug(f"Chunk {idx}/{num} di dimensione '{dim}' committato")
        total_chunks += num

    # Salva e chiude
    logging.info(f"Salvataggio e chiusura. Totale chunk: {total_chunks}")
    mc.save()
    mc.close()
    level.close()

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Converti .schematic → .mcstructure (Bedrock)"
    )
    parser.add_argument(
        "input", help="File .schematic di input"
    )
    parser.add_argument(
        "--platform", default="bedrock",
        help="Piattaforma Bedrock (default: bedrock)"
    )
    parser.add_argument(
        "--version", type=parse_version,
        default=DEFAULT_VERSION,
        help=(
            "Versione Bedrock (default: 1.21)."
            " Specificala come 'X.Y' o 'X.Y.Z'."
        )
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Mostra log di debug dettagliati"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        out = convert(args.input, args.platform, args.version)
        print(f"✅ Conversione completata: {out}")
    except Exception as e:
        logging.error(f"Errore durante la conversione: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
