"""
Centralized logging configuration for CyberWatch.

Provides structured JSONL logging with rotation, context injection,
and component-specific loggers. Enabled by default with environment
variable configuration.
"""
import logging
import logging.handlers
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional
import traceback


class JSONLFormatter(logging.Formatter):
    """
    Custom formatter that outputs logs in JSON Lines format.
    Each log entry is a single-line JSON object with standardized fields.
    """
    
    def __init__(self, component: str = "cyberwatch"):
        super().__init__()
        self.component = component
        self.hostname = os.getenv("HOSTNAME", os.getenv("COMPUTERNAME", "unknown"))
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format a log record as a JSON line.
        
        Args:
            record: The log record to format
            
        Returns:
            JSON string representation of the log record
        """
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "component": self.component,
            "logger": record.name,
            "message": record.getMessage(),
            "hostname": self.hostname,
            "process_id": record.process,
            "thread_id": record.thread,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception information if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info)
            }
        
        # Add extra fields from the record
        # These can be set using logging.info("msg", extra={"key": "value"})
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)
        
        # Common extra attributes we want to capture
        extra_attrs = [
            "request_id", "task_id", "target", "asn", "measurement_id",
            "duration", "status_code", "user_input", "outcome", "state",
            "error_code", "query", "rows_affected", "batch_size"
        ]
        
        for attr in extra_attrs:
            if hasattr(record, attr):
                log_data[attr] = getattr(record, attr)
        
        return json.dumps(log_data, default=str)


class ContextAdapter(logging.LoggerAdapter):
    """
    Logger adapter that automatically injects context into log records.
    Useful for adding request IDs, task IDs, etc. to all logs in a context.
    """
    
    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        """
        Process the logging call, injecting context into extra fields.
        
        Args:
            msg: The log message
            kwargs: Additional keyword arguments
            
        Returns:
            Tuple of (msg, kwargs) with context injected
        """
        # Merge context with any existing extra fields
        extra = kwargs.get("extra", {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs


def setup_logging(
    component: str = "cyberwatch",
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    max_bytes: Optional[int] = None,
    backup_count: int = 10,
    enable_console: bool = True
) -> logging.Logger:
    """
    Set up logging configuration for a CyberWatch component.
    
    Args:
        component: Component name (api, worker, collector, enrichment, etc.)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file (default: logs/cyberwatch.jsonl)
        max_bytes: Max bytes per log file before rotation (default: 100MB)
        backup_count: Number of backup files to keep (default: 10)
        enable_console: Whether to enable console logging (default: True)
        
    Returns:
        Configured logger instance
    """
    # Get configuration from environment variables with defaults
    log_level = log_level or os.getenv("CYBERWATCH_LOG_LEVEL", "INFO").upper()
    log_file = log_file or os.getenv("CYBERWATCH_LOG_FILE", "logs/cyberwatch.jsonl")
    max_bytes = max_bytes or int(os.getenv("CYBERWATCH_LOG_MAX_BYTES", str(100 * 1024 * 1024)))  # 100MB
    
    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level, logging.INFO)
    
    # Create logger for this component
    logger = logging.getLogger(f"cyberwatch.{component}")
    logger.setLevel(numeric_level)
    logger.propagate = False  # Don't propagate to root logger
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Create logs directory if it doesn't exist
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    # Set up JSON formatter
    formatter = JSONLFormatter(component=component)
    
    # Add rotating file handler
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except (IOError, OSError) as e:
        # If we can't write to file, log to stderr
        sys.stderr.write(f"Failed to set up file logging to {log_file}: {e}\n")
    
    # Add console handler for human-readable output
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        
        # Use simplified format for console
        console_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    # Log initial setup message
    logger.info(
        "Logging configured",
        extra={
            "log_level": log_level,
            "log_file": log_file,
            "max_bytes": max_bytes,
            "backup_count": backup_count,
            "console_enabled": enable_console
        }
    )
    
    return logger


def get_logger(component: str, context: Optional[Dict[str, Any]] = None) -> logging.Logger:
    """
    Get or create a logger for a component with optional context.
    
    Args:
        component: Component name (api, worker, collector, enrichment, etc.)
        context: Optional context dictionary to inject into all logs
        
    Returns:
        Logger or ContextAdapter if context is provided
    """
    logger = logging.getLogger(f"cyberwatch.{component}")
    
    # If logger hasn't been set up yet, set it up with defaults
    if not logger.handlers:
        logger = setup_logging(component)
    
    # Return a context adapter if context is provided
    if context:
        return ContextAdapter(logger, context)
    
    return logger


def log_function_call(logger: logging.Logger, sanitize_fields: Optional[list] = None):
    """
    Decorator to automatically log function calls with inputs and outputs.
    
    Args:
        logger: Logger instance to use
        sanitize_fields: List of parameter names to redact from logs
        
    Returns:
        Decorator function
    
    Example:
        @log_function_call(logger, sanitize_fields=["password", "token"])
        def my_function(username, password):
            pass
    """
    sanitize_fields = sanitize_fields or ["password", "token", "secret", "api_key"]
    
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Sanitize sensitive fields
            sanitized_kwargs = {
                k: "***REDACTED***" if k in sanitize_fields else v
                for k, v in kwargs.items()
            }
            
            logger.debug(
                f"Calling {func.__name__}",
                extra={
                    "function": func.__name__,
                    "args_count": len(args),
                    "kwargs": sanitized_kwargs
                }
            )
            
            try:
                result = func(*args, **kwargs)
                logger.debug(
                    f"Completed {func.__name__}",
                    extra={
                        "function": func.__name__,
                        "outcome": "success"
                    }
                )
                return result
            except Exception as e:
                logger.error(
                    f"Error in {func.__name__}: {str(e)}",
                    exc_info=True,
                    extra={
                        "function": func.__name__,
                        "outcome": "error",
                        "error_type": type(e).__name__
                    }
                )
                raise
        
        return wrapper
    return decorator


# Pre-configure common loggers for easy import
def init_component_loggers():
    """Initialize loggers for all major components."""
    components = ["api", "worker", "collector", "enrichment", "scheduler", "ui", "db"]
    loggers = {}
    
    for component in components:
        loggers[component] = setup_logging(component)
    
    return loggers


# Utility function to sanitize sensitive data
def sanitize_log_data(data: Dict[str, Any], sensitive_keys: Optional[list] = None) -> Dict[str, Any]:
    """
    Sanitize sensitive data from log dictionaries.
    
    Args:
        data: Dictionary containing log data
        sensitive_keys: List of keys to redact (case-insensitive)
        
    Returns:
        Sanitized dictionary with sensitive values replaced
    """
    sensitive_keys = sensitive_keys or [
        "password", "passwd", "pwd", "token", "secret", "api_key",
        "apikey", "auth", "authorization", "neo4j_password"
    ]
    
    sanitized = {}
    for key, value in data.items():
        if any(sensitive in key.lower() for sensitive in sensitive_keys):
            sanitized[key] = "***REDACTED***"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_log_data(value, sensitive_keys)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            sanitized[key] = [sanitize_log_data(item, sensitive_keys) for item in value]
        else:
            sanitized[key] = value
    
    return sanitized
