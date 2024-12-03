import logging
import colorlog
from pathlib import Path

class PredictionMarketFilter(logging.Filter):
    """Add prediction market context to log records."""
    def filter(self, record):
        # Ensure all records have certain attributes, even if empty
        for attr in ['user_id', 'prediction_id', 'channel_id', 'economy']:
            if not hasattr(record, attr):
                setattr(record, attr, None)
        return True

def setup_logger(name: str, log_file: str = None) -> logging.Logger:
    """Set up a colored logger instance with optional file output."""
    
    # Get or create logger
    logger = logging.getLogger(name)
    
    # Clear any existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()
    
    logger.setLevel(logging.INFO)
    logger.propagate = False
    
    # Create console handler with colored formatting
    console_handler = colorlog.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Create colored formatter
    color_formatter = colorlog.ColoredFormatter(
        "%(asctime)s - %(log_color)s%(levelname)-8s%(reset)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        reset=True,
        log_colors={
            'DEBUG':    'cyan',
            'INFO':     'green',
            'WARNING':  'yellow',
            'ERROR':    'red',
            'CRITICAL': 'red,bg_white',
        }
    )
    
    console_handler.setFormatter(color_formatter)
    logger.addHandler(console_handler)
    
    # Add file handler if specified
    if log_file:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        file_handler = logging.FileHandler(
            filename=log_dir / log_file,
            encoding="utf-8",
            mode="a"
        )
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(file_handler)
    
    return logger 