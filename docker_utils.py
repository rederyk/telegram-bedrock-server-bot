# minecraft_telegram_bot/docker_utils.py
import asyncio
import subprocess
import re
from config import CONTAINER, get_logger

logger = get_logger(__name__)

async def run_docker_command(command_args: list, read_output: bool = False, timeout: int = 15):
    if not CONTAINER and "exec" in command_args:
        logger.error("🐳❌ CONTAINER non impostato per Docker exec.")
        raise ValueError("CONTAINER non configurato per l'esecuzione del comando Docker.")

    try:
        logger.debug(f"🐳 Eseguo Docker: {' '.join(command_args)}")
        process = await asyncio.create_subprocess_exec(
            *command_args,
            stdout=asyncio.subprocess.PIPE if read_output else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

        decoded_stderr = stderr.decode().strip() if stderr else ""
        if decoded_stderr:
            # Non registrare stderr come warning se è solo "Container ... is not running"
            # o messaggi informativi da `send-command list` che a volte finiscono in stderr
            if "is not running" not in decoded_stderr.lower() and \
               not ("list" in command_args and "players online" in decoded_stderr.lower()):
                logger.info(f"🐳 Stderr Docker '{' '.join(command_args)}': {decoded_stderr}")


        if process.returncode != 0:
            # Non trattare come errore se `send-command list` non trova giocatori
            # o se il container non è in esecuzione e stiamo provando a fermarlo/riavviarlo
            if not (("send-command" in command_args and "list" in command_args) or \
                    (("stop" in command_args or "restart" in command_args) and "is not running" in decoded_stderr.lower())):
                logger.warning(
                    f"🐳⚠️ Comando Docker '{' '.join(command_args)}' -> {process.returncode}. Stderr: {decoded_stderr}"
                )
                raise subprocess.CalledProcessError(
                    process.returncode, command_args,
                    output=stdout.decode().strip() if stdout and read_output else None,
                    stderr=decoded_stderr
                )
            else: # Logga come info se è un caso "normale" di non-errore
                 logger.info(f"🐳 Comando Docker '{' '.join(command_args)}' -> {process.returncode} (gestito). Stderr: {decoded_stderr}")


        if read_output:
            return stdout.decode().strip() if stdout else ""
        return process.returncode
    except asyncio.TimeoutError:
        logger.error(f"🐳⏳ Timeout Docker: {' '.join(command_args)}")
        raise
    except subprocess.CalledProcessError: # Rilanciata se non gestita sopra
        raise
    except Exception as e:
        logger.error(f"🐳🆘 Errore Docker imprevisto {' '.join(command_args)}: {e}", exc_info=True)
        raise

async def get_online_players_from_server() -> list:
    if not CONTAINER:
        logger.error("🐳❌ CONTAINER non impostato per lista giocatori.")
        return []
    try:
        list_command_args = ["docker", "exec", CONTAINER, "send-command", "list"]
        logger.info(f"🐳👤 Aggiorno lista giocatori: {' '.join(list_command_args)}")
        try:
            await run_docker_command(list_command_args, read_output=False, timeout=5)
        except subprocess.CalledProcessError as e:
            # Questo è comune se il server è avviato ma nessun player è loggato, o se il comando 'list'
            # su Bedrock non produce output se nessuno è online, ma scrive su stderr.
            # Consideriamo il messaggio "No players online" o "Nessun giocatore connesso" come non-errore.
            if "no players online" not in (e.stderr or "").lower() and \
               "nessun giocatore connesso" not in (e.stderr or "").lower():
                logger.warning(
                    f"🐳⚠️ Comando '{' '.join(list_command_args)}' errore {e.returncode}, leggo log. Stderr: {e.stderr}"
                )
            else:
                 logger.info(f"🐳ℹ️ Comando list giocatori: {e.stderr}") # Nessun giocatore o messaggio informativo
        except asyncio.TimeoutError:
            logger.error(
                f"🐳⏳ Timeout '{' '.join(list_command_args)}'. Lista giocatori non aggiornata."
            )
            return []
        except Exception as e: # Altre eccezioni da run_docker_command
            logger.error(
                f"🐳🆘 Errore '{' '.join(list_command_args)}': {e}. Tento lettura log."
            )

        await asyncio.sleep(1.0)

        logs_command_args = ["docker", "logs", "--tail", "100", CONTAINER]
        logger.info(f"🐳📄 Leggo log: {' '.join(logs_command_args)}")
        output = await run_docker_command(logs_command_args, read_output=True, timeout=5)

        if not output:
            logger.warning("🐳❓ Nessun output log dopo comando list.")
            return []

        lines = output.splitlines()
        player_list = []

        for i in reversed(range(len(lines))):
            current_line_raw = lines[i]
            current_line_content = current_line_raw
            match = re.search(r"\]: (.*)|\] (.*)|คอนโซล: (.*)", current_line_content)
            if match:
                current_line_content = next(g for g in match.groups() if g is not None)

            current_line_lower = current_line_content.lower()

            if ("players online:" in current_line_lower and "there are" in current_line_lower) or \
               ("players online:" in current_line_lower):
                if ":" in current_line_content:
                    potential_players_str = current_line_content.split(":", 1)[1].strip()
                    if potential_players_str:
                        if "max players online" not in current_line_lower:
                            player_list = [
                                p.strip() for p in potential_players_str.split(',')
                                if p.strip() and "no players online" not in p.lower() and "nessun giocatore connesso" not in p.lower()
                            ]
                            if player_list:
                                logger.info(f"👤✅ Giocatori online (stessa riga): {player_list}")
                                return player_list

                if i + 1 < len(lines):
                    next_line_raw = lines[i+1]
                    next_line_content = next_line_raw
                    match_next = re.search(r"\]: (.*)|\] (.*)|คอนโซล: (.*)", next_line_content)
                    if match_next:
                        next_line_content = next(g for g in match_next.groups() if g is not None)
                    next_line_content_stripped = next_line_content.strip()
                    if next_line_content_stripped and \
                       not next_line_content_stripped.startswith("[") and \
                       " INFO" not in next_line_raw and \
                       " WARN" not in next_line_raw and \
                       " ERROR" not in next_line_raw and \
                       "คอนโซล:" not in next_line_raw:
                        if "no players online" not in next_line_content_stripped.lower() and \
                           "nessun giocatore connesso" not in next_line_content_stripped.lower():
                            player_list = [p.strip() for p in next_line_content_stripped.split(',') if p.strip()]
                            if player_list:
                                logger.info(f"👤✅ Giocatori online (riga succ.): {player_list}")
                                return player_list

                logger.info("👤ℹ️ 'players online:' trovato, ma nessun giocatore elencato.")
                return []

        logger.info("👤❓ Pattern 'players online:' non trovato nei log recenti.")
        return []
    except asyncio.TimeoutError:
        logger.error("🐳⏳ Timeout lettura log per giocatori online.")
    except subprocess.CalledProcessError as e:
        logger.error(f"🐳❌ Errore Docker lettura log giocatori: {e.cmd} - {e.stderr or e.output or e}")
    except ValueError as e: # CONTAINER non configurato
        logger.error(f"⚙️❌ Errore config get_online_players: {e}")
    except Exception as e:
        logger.error(f"🆘 Errore generico giocatori online: {e}", exc_info=True)
    return []