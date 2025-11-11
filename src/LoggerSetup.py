"""
logger_setup - Centralized logging configuration for Watchtower

This module provides consistent logging configuration across all Watchtower components.
All source files should use setup_logger() instead of configuring logging.basicConfig()
directly to ensure consistent formatting and log levels.
"""
import logging
import sys


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds ANSI color codes to log levels."""

    COLORS = {
        'DEBUG': '\033[0;36m',      # Cyan
        'INFO': '\033[0;37m',       # White
        'WARNING': '\033[0;33m',    # Yellow
        'ERROR': '\033[0;31m',      # Red
        'CRITICAL': '\033[1;31m',   # Bold Red
    }
    RESET = '\033[0m'  # Reset to default color

    def __init__(self, fmt=None, datefmt=None, use_color=None):
        """Initialize colored formatter.

        Args:
            fmt: Log format string
            datefmt: Date format string
            use_color: Whether to use ANSI color codes (auto-detected if None)
        """
        super().__init__(fmt, datefmt)
        # Auto-detect if output supports color (is a TTY)
        if use_color is None:
            use_color = hasattr(sys.stderr, 'isatty') and sys.stderr.isatty()
        self.use_color = use_color

    def format(self, record):
        """Format log record with color codes if enabled."""
        if self.use_color and record.levelname in self.COLORS:
            # Add color to the level name
            levelname_color = self.COLORS[record.levelname] + record.levelname + self.RESET
            record.levelname = levelname_color

        return super().format(record)


def setup_logger(name: str, use_color=None) -> logging.Logger:
    """Get logger with consistent formatting and colored output.

    Configures logging with a standard format including timestamp, level, and message.
    Safe to call multiple times; it only configures on the first call.

    Args:
        name: Logger name (__name__ from calling module for easier debugging)
        use_color: Whether to use colored output (auto-detected if None)

    Returns:
        logging.Logger: Configured logger instance with colored formatting

    Example:
        >>> logger = setup_logger(__name__)
        >>> logger.info("Normal message")
        >>> logger.warning("Yellow warning")
        >>> logger.error("Red error")
    """
    # Check if root logger is already configured
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        # Configure root logger on first call
        handler = logging.StreamHandler(sys.stderr)
        formatter = ColoredFormatter(
            fmt='%(asctime)s - %(levelname)s - [%(name)s] %(message)s',
            use_color=use_color
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        # root_logger.setLevel(logging.INFO)
        root_logger.setLevel(logging.DEBUG)

    return logging.getLogger(name)
