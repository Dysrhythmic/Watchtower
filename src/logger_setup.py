"""
logger_setup - Centralized logging configuration for Watchtower

This module provides consistent logging configuration across all Watchtower components.
All source files should use setup_logger() instead of configuring logging.basicConfig()
directly to ensure consistent formatting and log levels.

Example:
    from logger_setup import setup_logger
    logger = setup_logger(__name__)
    logger.info("Message logged with consistent formatting")
"""
import logging


def setup_logger(name: str) -> logging.Logger:
    """Get logger with consistent Watchtower formatting.

    Configures logging with a standard format including timestamp, level, and message.
    Safe to call multiple times - logging.basicConfig() only configures on first call.

    Args:
        name: Logger name (typically __name__ from calling module)

    Returns:
        logging.Logger: Configured logger instance
    """
    logging.basicConfig(
        format='%(asctime)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    return logging.getLogger(name)
