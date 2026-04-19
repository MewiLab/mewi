import logging
import sys
from logging.handlers import RotatingFileHandler

from app.core.config import Settings

def setup_logging(settings: Settings) -> None:
    """
    Configure logging once at process startup (called from lifespan.py).

    Rules:
    - Console handler always on — Docker/cloud reads stdout
    - File handler only if log_file_path is set — disable in cloud by leaving it empty
    - force=True bulldozes any handlers uvicorn/third-parties set before us
    - Noisy libraries get their own level cap so they don't flood your logs
    """
    log_level = logging.DEBUG if settings.debug else getattr(logging, settings.log_level)
    log_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    handlers: list[logging.Handler] = []
    # will show log in terminal, even in docker, we can use docker logs <container_name>
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    handlers.append(console_handler)
    
    if settings.log_file_path:
        file_handler = RotatingFileHandler(
            filename=settings.log_file_path,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(log_format)
        handlers.append(file_handler)
    
    # If not use `force` our custom formatting will be ignored due to FSFS by uvicorn main:app
    logging.basicConfig(level=log_level, handlers=handlers, force=True)

    # Only log level >= warning requires to log down
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)