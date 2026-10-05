import logging
import sys
from logging.handlers import RotatingFileHandler

from app.core.config import Settings

def setup_logging(settings: Settings) -> None:
    """
    Configure logging once at process startup (called from lifespan.py).
    """
    log_level = logging.DEBUG if settings.debug else getattr(logging, settings.log_level)
    log_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    handlers: list[logging.Handler] = []
    
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
    
    logging.basicConfig(level=log_level, handlers=handlers, force=True)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

def shutdown_logging() -> None:
    logging.shutdown()