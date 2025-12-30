"""
Logging utility with clear prefixes and configurable levels
"""

import os
import sys
from enum import Enum
from typing import Optional


class LogLevel(Enum):
    """Log levels"""
    DEBUG = 0
    INFO = 1
    ERROR = 2


class Logger:
    """Simple logger with prefix support"""
    
    def __init__(self, level: str = "INFO"):
        """Initialize logger with log level"""
        level_upper = level.upper()
        if level_upper == "DEBUG":
            self.level = LogLevel.DEBUG
        elif level_upper == "ERROR":
            self.level = LogLevel.ERROR
        else:
            self.level = LogLevel.INFO
    
    def _should_log(self, message_level: LogLevel) -> bool:
        """Check if message should be logged based on current level"""
        return message_level.value >= self.level.value
    
    def debug(self, message: str):
        """Log debug message"""
        if self._should_log(LogLevel.DEBUG):
            print(f"[DEBUG] {message}", file=sys.stderr)
    
    def info(self, message: str):
        """Log info message"""
        if self._should_log(LogLevel.INFO):
            print(f"[INFO]  {message}")
    
    def error(self, message: str):
        """Log error message"""
        if self._should_log(LogLevel.ERROR):
            print(f"[ERROR] {message}", file=sys.stderr)
    
    def success(self, message: str):
        """Log success message (info level)"""
        if self._should_log(LogLevel.INFO):
            print(f"[INFO]  ✓ {message}")
    
    def warning(self, message: str):
        """Log warning message (info level)"""
        if self._should_log(LogLevel.INFO):
            print(f"[INFO]  ⚠️  {message}")


# Global logger instance
_logger: Optional[Logger] = None


def get_logger() -> Logger:
    """Get or create global logger instance"""
    global _logger
    if _logger is None:
        log_level = os.getenv('LOG_LEVEL', 'INFO')
        _logger = Logger(log_level)
    return _logger


def set_log_level(level: str):
    """Set global logger level"""
    global _logger
    _logger = Logger(level)

