import sys
import os

from loguru import logger

from omnimcp.config import config

log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
# Define file path using a format string recognized by loguru's sink
log_file_path = os.path.join(log_dir, "run_{time:YYYY-MM-DD_HH-mm-ss}.log")

logger.remove()  # Remove default handler to configure levels precisely
# Log INFO and above to stderr
logger.add(sys.stderr, level=config.LOG_LEVEL.upper() if config.LOG_LEVEL else "INFO")
# Log DEBUG and above to a rotating file
logger.add(
    log_file_path, rotation="50 MB", level="DEBUG", encoding="utf8", enqueue=True
)  # enqueue for async safety

logger.info("Logger configured.")
# You might want to set LOG_LEVEL=DEBUG in your .env file now
