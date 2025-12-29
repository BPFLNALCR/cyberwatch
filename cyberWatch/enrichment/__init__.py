"""
Enrichment module for cyberWatch.

Provides ASN lookup, external API sources, PeeringDB integration,
and graph building utilities.

This module includes shared utilities for robustness:
- CircuitBreaker: Prevents cascading failures when external APIs are down
- RateLimiter: Token-bucket rate limiter for API rate limits
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from cyberWatch.logging_config import get_logger

logger = get_logger("enrichment")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation, requests pass through
    OPEN = "open"          # Circuit tripped, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for external API resilience.
    
    Prevents cascading failures by failing fast when an external service
    is experiencing issues. After failure_threshold consecutive failures,
    the circuit opens and requests fail immediately. After recovery_time
    seconds, the circuit moves to half-open and allows one test request.
    
    Usage:
        breaker = CircuitBreaker(name="ip-api", failure_threshold=5)
        
        if breaker.is_open():
            return cached_or_fallback_value
        
        try:
            result = await external_api_call()
            breaker.record_success()
            return result
        except Exception as e:
            breaker.record_failure()
            raise
    """
    name: str
    failure_threshold: int = 5
    recovery_time: float = 60.0  # seconds before trying again
    half_open_max_calls: int = 1
    
    # Internal state
    _failures: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _half_open_calls: int = field(default=0, init=False)
    
    def is_open(self) -> bool:
        """Check if circuit is open (requests should fail fast)."""
        if self._state == CircuitState.CLOSED:
            return False
        
        if self._state == CircuitState.OPEN:
            # Check if recovery time has passed
            if time.time() - self._last_failure_time >= self.recovery_time:
                self._transition_to_half_open()
                return False
            return True
        
        # HALF_OPEN: allow limited test calls
        if self._state == CircuitState.HALF_OPEN:
            if self._half_open_calls >= self.half_open_max_calls:
                return True
            return False
        
        return False
    
    def record_success(self) -> None:
        """Record a successful call."""
        if self._state == CircuitState.HALF_OPEN:
            # Service recovered, close the circuit
            self._transition_to_closed()
            logger.info(
                f"Circuit breaker '{self.name}' closed after successful recovery",
                extra={"circuit": self.name, "state": "closed", "outcome": "recovered"}
            )
        elif self._state == CircuitState.CLOSED:
            # Reset failure counter on success
            self._failures = 0
    
    def record_failure(self) -> None:
        """Record a failed call."""
        self._failures += 1
        self._last_failure_time = time.time()
        
        if self._state == CircuitState.HALF_OPEN:
            # Failed during recovery test, back to open
            self._transition_to_open()
            logger.warning(
                f"Circuit breaker '{self.name}' re-opened after failed recovery attempt",
                extra={"circuit": self.name, "state": "open", "outcome": "recovery_failed"}
            )
        elif self._state == CircuitState.CLOSED:
            if self._failures >= self.failure_threshold:
                self._transition_to_open()
                logger.warning(
                    f"Circuit breaker '{self.name}' opened after {self._failures} failures",
                    extra={
                        "circuit": self.name,
                        "state": "open",
                        "failures": self._failures,
                        "outcome": "tripped"
                    }
                )
    
    def _transition_to_open(self) -> None:
        """Transition to OPEN state."""
        self._state = CircuitState.OPEN
        self._half_open_calls = 0
    
    def _transition_to_half_open(self) -> None:
        """Transition to HALF_OPEN state."""
        self._state = CircuitState.HALF_OPEN
        self._half_open_calls = 0
        logger.info(
            f"Circuit breaker '{self.name}' entering half-open state",
            extra={"circuit": self.name, "state": "half_open"}
        )
    
    def _transition_to_closed(self) -> None:
        """Transition to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._half_open_calls = 0
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state
    
    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failures": self._failures,
            "failure_threshold": self.failure_threshold,
            "recovery_time": self.recovery_time,
            "time_since_last_failure": time.time() - self._last_failure_time if self._last_failure_time else None,
        }


@dataclass
class RateLimiter:
    """
    Token-bucket rate limiter for API rate limits.
    
    Allows up to max_requests within window_seconds, then blocks
    until tokens become available.
    
    Usage:
        limiter = RateLimiter(max_requests=45, window_seconds=60)  # ip-api limit
        
        if not limiter.try_acquire():
            await asyncio.sleep(limiter.time_until_available())
            limiter.try_acquire()
        
        await make_api_call()
    """
    max_requests: int
    window_seconds: float = 60.0
    
    # Internal state
    _tokens: list = field(default_factory=list, init=False)
    
    def try_acquire(self) -> bool:
        """
        Try to acquire a rate limit token.
        Returns True if acquired, False if rate limited.
        """
        now = time.time()
        
        # Remove expired tokens
        cutoff = now - self.window_seconds
        self._tokens = [t for t in self._tokens if t > cutoff]
        
        if len(self._tokens) >= self.max_requests:
            return False
        
        self._tokens.append(now)
        return True
    
    def time_until_available(self) -> float:
        """
        Returns seconds until a token will be available.
        Returns 0 if a token is available now.
        """
        if len(self._tokens) < self.max_requests:
            return 0.0
        
        now = time.time()
        cutoff = now - self.window_seconds
        
        # Find oldest token that will expire
        valid_tokens = sorted(t for t in self._tokens if t > cutoff)
        if not valid_tokens:
            return 0.0
        
        oldest = valid_tokens[0]
        wait_time = (oldest + self.window_seconds) - now
        return max(0.0, wait_time)
    
    def tokens_available(self) -> int:
        """Return number of tokens currently available."""
        now = time.time()
        cutoff = now - self.window_seconds
        valid_count = sum(1 for t in self._tokens if t > cutoff)
        return max(0, self.max_requests - valid_count)


# Shared circuit breakers for external APIs (singleton instances)
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_time: float = 60.0,
) -> CircuitBreaker:
    """
    Get or create a circuit breaker by name.
    
    Breakers are shared across the application to ensure consistent
    state tracking for each external service.
    """
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_time=recovery_time,
        )
    return _circuit_breakers[name]


# Shared rate limiters for external APIs
_rate_limiters: dict[str, RateLimiter] = {}


def get_rate_limiter(
    name: str,
    max_requests: int,
    window_seconds: float = 60.0,
) -> RateLimiter:
    """
    Get or create a rate limiter by name.
    
    Rate limiters are shared across the application to ensure
    global rate limit compliance.
    """
    if name not in _rate_limiters:
        _rate_limiters[name] = RateLimiter(
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
    return _rate_limiters[name]
