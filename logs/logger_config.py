
import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Cria pasta de logs, se não existir
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Nome do arquivo de log (exemplo: logs/automacao_2025-10-15.log)
LOG_FILE = os.path.join(LOG_DIR, f"automacao_{datetime.now():%Y-%m-%d}.log")

# Formato padrão dos logs
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Cria o logger principal
logger = logging.getLogger("automacao_repasse")
logger.setLevel(logging.INFO)

# Evita duplicação de handlers em importações múltiplas
if not logger.handlers:
    # Handler para o terminal
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Handler para arquivo com rotação
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5_000_000,  # 5 MB
        backupCount=5,       # mantém até 5 arquivos antigos
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)

    # Formatação dos logs
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    # Adiciona os handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    # Mensagem inicial (quando o logger é criado)
    logger.info("=" * 80)
    logger.info("🚀 Iniciando sessão de logs da automação de repasse")
    logger.info("=" * 80)
