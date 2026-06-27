#!/usr/bin/env python3
"""
Quick test script to validate CyberWatch logging implementation.
Run this to verify logging is working correctly.
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cyberWatch.logging_config import setup_logging, get_logger, sanitize_log_data


def test_basic_logging():
    """Test basic logging functionality."""
    print("Testing basic logging...")
    
    logger = setup_logging("test", log_file="logs/test.jsonl")
    
    logger.debug("This is a DEBUG message")
    logger.info("This is an INFO message")
    logger.warning("This is a WARNING message")
    logger.error("This is an ERROR message")
    
    print("✓ Basic logging test passed\n")


def test_structured_logging():
    """Test structured logging with extra fields."""
    print("Testing structured logging...")
    
    logger = get_logger("test")
    
    logger.info(
        "Processing user request",
        extra={
            "request_id": "test-123",
            "user_input": {"target": "8.8.8.8"},
            "action": "process_start",
            "duration": 1234.56,
            "outcome": "success"
        }
    )
    
    print("✓ Structured logging test passed\n")


def test_sensitive_data_redaction():
    """Test that sensitive data is redacted."""
    print("Testing sensitive data redaction...")
    
    logger = get_logger("test")
    
    sensitive_data = {
        "username": "admin",
        "password": "super_secret_123",
        "api_key": "sk-1234567890",
        "neo4j_password": "graph_secret",
        "regular_field": "visible_data"
    }
    
    sanitized = sanitize_log_data(sensitive_data)
    
    assert sanitized["password"] == "***REDACTED***"
    assert sanitized["api_key"] == "***REDACTED***"
    assert sanitized["neo4j_password"] == "***REDACTED***"
    assert sanitized["regular_field"] == "visible_data"
    
    logger.info("Logged with redaction", extra=sanitized)
    
    print("✓ Sensitive data redaction test passed\n")


def test_error_logging():
    """Test error logging with exceptions."""
    print("Testing error logging with exceptions...")
    
    logger = get_logger("test")
    
    try:
        # Intentionally cause an error
        result = 1 / 0
    except ZeroDivisionError as e:
        logger.error(
            "Math error occurred",
            exc_info=True,
            extra={
                "error_type": type(e).__name__,
                "outcome": "error"
            }
        )
    
    print("✓ Error logging test passed\n")


def test_component_logging():
    """Test different component loggers."""
    print("Testing component-specific loggers...")
    
    components = ["api", "worker", "collector", "enrichment", "db"]
    
    for component in components:
        logger = get_logger(component)
        logger.info(f"{component.capitalize()} component initialized", extra={"component": component})
    
    print("✓ Component logging test passed\n")


async def test_async_logging():
    """Test logging in async context."""
    print("Testing async logging...")
    
    logger = get_logger("test")
    
    async def async_operation():
        logger.info("Starting async operation", extra={"action": "async_start"})
        await asyncio.sleep(0.1)
        logger.info("Completed async operation", extra={"action": "async_complete", "outcome": "success"})
    
    await async_operation()
    
    print("✓ Async logging test passed\n")


def main():
    """Run all tests."""
    print("=" * 60)
    print("CyberWatch Logging Test Suite")
    print("=" * 60)
    print()
    
    try:
        test_basic_logging()
        test_structured_logging()
        test_sensitive_data_redaction()
        test_error_logging()
        test_component_logging()
        asyncio.run(test_async_logging())
        
        print("=" * 60)
        print("All tests passed! ✓")
        print("=" * 60)
        print()
        print("Check logs/test.jsonl for output")
        print("Run: cat logs/test.jsonl | jq '.'")
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
