import logging


def get_logger(name: str) -> logging.Logger:
    """
    Returns a configured logger.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        # StreamHandler outputs to console
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
