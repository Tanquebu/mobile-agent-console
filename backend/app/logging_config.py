"""Configurazione del logging applicativo per l'esecuzione reale.

Isolata dal resto perché sia testabile senza avviare un vero processo
uvicorn: il test di regressione invoca la stessa funzione usata in
produzione e verifica lo stato *effettivo* del logger (livello, handler),
invece di un `caplog.at_level(...)` che forzerebbe artificialmente il
livello per la durata del test mascherando l'assenza di configurazione
reale (bug osservato in TEST-BH-03/IMP-BH-03-R1: `uvicorn.run(...)` senza
`log_config` configura solo i logger `uvicorn.*`, mai il logger applicativo
`mobile_agent_console` usato in `app/main.py`, che restava a `WARNING`
senza alcun handler e scartava ogni `logger.info(...)` in modo silenzioso).
"""

from __future__ import annotations

import copy
import logging.config
from typing import Any

from uvicorn.config import LOGGING_CONFIG as _UVICORN_LOGGING_CONFIG

# Nome usato da tutti i logger applicativi del pacchetto (main.py,
# services/push_service.py, ...). Un'unica voce qui basta a coprirli tutti.
APP_LOGGER_NAME = "mobile_agent_console"


def build_log_config() -> dict[str, Any]:
    """Config di logging da passare a `uvicorn.run(log_config=...)`.

    Parte da una copia della configurazione di default di uvicorn (stessi
    formatter/handler per i suoi logger, `disable_existing_loggers: False`)
    e aggiunge il logger applicativo a livello INFO riusando l'handler
    `default` già definito da uvicorn (uno `StreamHandler` su stderr):
    nessun handler nuovo, nessuna chiave `root`, quindi nessuna modifica al
    root logger o ai logger di librerie terze (`urllib3`, `asyncio`, ...),
    che restano al loro livello di default.
    """
    config = copy.deepcopy(_UVICORN_LOGGING_CONFIG)
    config["loggers"][APP_LOGGER_NAME] = {
        "handlers": ["default"],
        "level": "INFO",
        "propagate": False,
    }
    return config


def configure_logging() -> dict[str, Any]:
    """Applica `build_log_config()` con `logging.config.dictConfig`.

    Quando `uvicorn.run(log_config=cfg)` riceve un dict, internamente
    chiama esattamente `logging.config.dictConfig(cfg)` (vedi
    `uvicorn.config.Config.configure_logging`), quindi invocare questa
    funzione direttamente in un test riproduce fedelmente l'inizializzazione
    di produzione senza dover aprire un vero socket uvicorn.
    """
    config = build_log_config()
    logging.config.dictConfig(config)
    return config
