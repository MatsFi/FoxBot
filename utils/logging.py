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
    
    # Add prediction market context filter
    logger.addFilter(PredictionMarketFilter())
    
    # Create console handler with colored formatting
    console_handler = colorlog.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Create colored formatter with context
    color_formatter = colorlog.ColoredFormatter(
        "%(asctime)s - %(log_color)s%(levelname)-8s%(reset)s - %(message)s"
        "%(if_user_id)s [user:%(user_id)s]%(end_if)s"
        "%(if_prediction_id)s [pred:%(prediction_id)s]%(end_if)s"
        "%(if_channel_id)s [channel:%(channel_id)s]%(end_if)s"
        "%(if_economy)s [economy:%(economy)s]%(end_if)s",
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
        # Detailed formatter for file logs
        file_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s"
            "%(if_user_id)s [user:%(user_id)s]%(end_if)s"
            "%(if_prediction_id)s [pred:%(prediction_id)s]%(end_if)s"
            "%(if_channel_id)s [channel:%(channel_id)s]%(end_if)s"
            "%(if_economy)s [economy:%(economy)s]%(end_if)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger 