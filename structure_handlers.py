# minecraft_telegram_bot/structure_handlers.py
import asyncio
import html
import os
import re
import subprocess

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import get_logger
from user_management import auth_required

logger = get_logger(__name__)

@auth_required
async def handle_split_mcstructure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Utilizzo: /split_structure <percorso_file> [--threshold N] [--axis x|y|z]")
        return

    input_path = context.args[0]
    threshold = None
    axis = None

    # Parse optional arguments
    i = 1
    while i < len(context.args):
        if context.args[i] == "--threshold" and i + 1 < len(context.args):
            try:
                threshold = int(context.args[i+1])
                i += 2
            except ValueError:
                await update.message.reply_text("Errore: --threshold richiede un numero intero.")
                return
        elif context.args[i] == "--axis" and i + 1 < len(context.args) and context.args[i+1] in ['x', 'y', 'z']:
            axis = context.args[i+1]
            i += 2
        else:
            await update.message.reply_text(f"Errore: Argomento non riconosciuto o incompleto: {context.args[i]}")
            return
    
    script_path = "/app/importBuild/schem_to_mc_amulet/split_mcstructure.py"
    python_executable = "/app/importBuild/schem_to_mc_amulet/venv/bin/python"

    command = [python_executable, script_path, input_path]
    if threshold is not None:
        command.extend(["--threshold", str(threshold)])
    if axis is not None:
        command.extend(["--axis", axis])

    await update.message.reply_text(f"⏳ Esecuzione split_mcstructure.py per {input_path}...")

    try:
        # Run the script as a subprocess
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            output_message = f"✅ split_mcstructure.py completato.\nOutput:\n<pre>{html.escape(stdout.decode())}</pre>"
            await update.message.reply_text(output_message, parse_mode=ParseMode.HTML)
        else:
            error_message = f"❌ Errore durante l'esecuzione di split_mcstructure.py (Codice {process.returncode}).\nErrore:\n<pre>{html.escape(stderr.decode())}</pre>"
            await update.message.reply_text(error_message, parse_mode=ParseMode.HTML)

    except FileNotFoundError:
        await update.message.reply_text(f"❌ Errore: Eseguibile Python o script non trovato. Verifica i percorsi.")
    except Exception as e:
        logger.error(f"❌ Errore esecuzione split_mcstructure.py: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore generico durante l'esecuzione: {html.escape(str(e))}")

@auth_required
async def handle_convert2mc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Utilizzo: /convert_structure <percorso_file> [--version X.Y.Z]")
        return

    input_path = context.args[0]
    version = None

    # Parse optional arguments
    i = 1
    while i < len(context.args):
        if context.args[i] == "--version" and i + 1 < len(context.args):
            version = context.args[i+1]
            i += 2
        else:
            await update.message.reply_text(f"Errore: Argomento non riconosciuto o incompleto: {context.args[i]}")
            return

    script_path = "/app/importBuild/schem_to_mc_amulet/convert2mc.py"
    python_executable = "/app/importBuild/schem_to_mc_amulet/venv/bin/python"

    command = [python_executable, script_path, input_path]
    if version is not None:
        command.extend(["--version", version])

    await update.message.reply_text(f"⏳ Esecuzione convert2mc.py per {input_path}...")

    try:
        # Run the script as a subprocess
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            output_message = f"✅ convert2mc.py completato.\nOutput:\n<pre>{html.escape(stdout.decode())}</pre>"
            await update.message.reply_text(output_message, parse_mode=ParseMode.HTML)
        else:
            error_message = f"❌ Errore durante l'esecuzione di convert2mc.py (Codice {process.returncode}).\nErrore:\n<pre>{html.escape(stderr.decode())}</pre>"
            await update.message.reply_text(error_message, parse_mode=ParseMode.HTML)

    except FileNotFoundError:
        await update.message.reply_text(f"❌ Errore: Eseguibile Python o script non trovato. Verifica i percorsi.")
    except Exception as e:
        logger.error(f"❌ Errore esecuzione convert2mc.py: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore generico durante l'esecuzione: {html.escape(str(e))}")

@auth_required
async def handle_structura_cli(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Utilizzo: /create_resourcepack <pack_name> --structures <file1.mcstructure> [<file2.mcstructure> ...] "
            "[--nametags <tag1> [<tag2> ...]] [--offsets <x,y,z> [<x,y,z> ...]] "
            "[--opacity N] [--icon <icon_path>] [--list] [--big_build] [--big_offset <x,y,z>]"
        )
        return

    pack_name = None
    structures = []
    nametags = None
    offsets = None
    opacity = None
    icon = None
    list_flag = False
    big_build = False
    big_offset = None

    # Parse arguments
    args = context.args
    i = 0
    while i < len(args):
        if i == 0 and pack_name is None:
            pack_name = args[i]
            i += 1
        elif args[i] == "--structures" and i + 1 < len(args):
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                structures.append(args[i])
                i += 1
        elif args[i] == "--nametags" and i + 1 < len(args):
            nametags = []
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                nametags.append(args[i])
                i += 1
        elif args[i] == "--offsets" and i + 1 < len(args):
            offsets = []
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                offsets.append(args[i])
                i += 1
        elif args[i] == "--opacity" and i + 1 < len(args):
            try:
                opacity = int(args[i+1])
                i += 2
            except ValueError:
                await update.message.reply_text("Errore: --opacity richiede un numero intero.")
                return
        elif args[i] == "--icon" and i + 1 < len(args):
            icon = args[i+1]
            i += 2
        elif args[i] == "--list":
            list_flag = True
            i += 1
        elif args[i] == "--big_build":
            big_build = True
            i += 1
        elif args[i] == "--big_offset" and i + 1 < len(args):
            big_offset = args[i+1]
            i += 2
        else:
            await update.message.reply_text(f"Errore: Argomento non riconosciuto o incompleto: {args[i]}")
            return

    if pack_name is None or not structures:
        await update.message.reply_text("Errore: Nome pacchetto e almeno un file struttura sono obbligatori.")
        return

    script_path = "/app/importBuild/structura_env/structuraCli.py"
    python_executable = "/app/importBuild/structura_env/venv/bin/python"

    command = [python_executable, script_path, pack_name, "--structures"] + structures

    if nametags is not None:
        command.extend(["--nametags"] + nametags)
    if offsets is not None:
        command.extend(["--offsets"] + offsets)
    if opacity is not None:
        command.extend(["--opacity", str(opacity)])
    if icon is not None:
        command.extend(["--icon", icon])
    if list_flag:
        command.append("--list")
    if big_build:
        command.append("--big_build")
    if big_offset is not None:
        command.extend(["--big_offset", big_offset])

    await update.message.reply_text(f"⏳ Esecuzione structuraCli.py per creare il pacchetto '{pack_name}'...")

    structura_script_dir = "/app/importBuild/structura_env/"
    try:
        # Run the script as a subprocess
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=structura_script_dir
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            output_message = f"✅ structuraCli.py completato.\nOutput:\n<pre>{html.escape(stdout.decode())}</pre>"
            await update.message.reply_text(output_message, parse_mode=ParseMode.HTML)
        else:
            error_message = f"❌ Errore durante l'esecuzione di structuraCli.py (Codice {process.returncode}).\nErrore:\n<pre>{html.escape(stderr.decode())}</pre>"
            await update.message.reply_text(error_message, parse_mode=ParseMode.HTML)

    except FileNotFoundError:
        await update.message.reply_text(f"❌ Errore: Eseguibile Python o script non trovato. Verifica i percorsi.")
    except Exception as e:
        logger.error(f"❌ Errore esecuzione structuraCli.py: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Errore generico durante l'esecuzione: {html.escape(str(e))}")
