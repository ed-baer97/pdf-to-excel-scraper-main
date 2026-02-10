"""
Redis utilities for rate limiting and caching.

Features:
- Distributed rate limiting (works across multiple workers)
- Automatic fallback to in-memory when Redis unavailable
- Thread-safe operations
"""
from __future__ import annotations

import os
import time
import threading
from collections import defaultdict
from typing import Optional

# Redis URL from environment
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Lazy Redis connection
_redis_client = None
_redis_lock = threading.Lock()
_redis_available = None

# In-memory fallback for rate limiting
_memory_rate_limits: dict[str, list[float]] = defaultdict(list)
_memory_lock = threading.Lock()


def get_redis_client():
    """
    Get or create Redis client.
    Returns None if Redis is not available.
    """
    global _redis_client, _redis_available
    
    if _redis_available is False:
        return None
    
    with _redis_lock:
        if _redis_client is None:
            try:
                import redis
                _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
                # Test connection
                _redis_client.ping()
                _redis_available = True
            except Exception:
                _redis_available = False
                _redis_client = None
        
        return _redis_client


def is_redis_available() -> bool:
    """Check if Redis is available."""
    return get_redis_client() is not None


class RateLimiter:
    """
    Distributed rate limiter with Redis backend.
    Falls back to in-memory if Redis unavailable.
    """
    
    def __init__(
        self,
        key_prefix: str = "ratelimit",
        max_requests: int = 10,
        window_seconds: int = 60,
    ):
        """
        Initialize rate limiter.
        
        Args:
            key_prefix: Redis key prefix
            max_requests: Maximum requests per window
            window_seconds: Window duration in seconds
        """
        self.key_prefix = key_prefix
        self.max_requests = max_requests
        self.window_seconds = window_seconds
    
    def _get_key(self, identifier: str) -> str:
        """Get Redis key for identifier."""
        return f"{self.key_prefix}:{identifier}"
    
    def is_allowed(self, identifier: str) -> tuple[bool, int]:
        """
        Check if request is allowed for identifier.
        
        Args:
            identifier: User ID, IP, or other identifier
        
        Returns:
            Tuple of (is_allowed, seconds_until_reset)
        """
        client = get_redis_client()
        
        if client:
            return self._check_redis(client, identifier)
        else:
            return self._check_memory(identifier)
    
    def _check_redis(self, client, identifier: str) -> tuple[bool, int]:
        """Check rate limit using Redis."""
        key = self._get_key(identifier)
        now = time.time()
        window_start = now - self.window_seconds
        
        pipe = client.pipeline()
        
        # Remove old entries
        pipe.zremrangebyscore(key, 0, window_start)
        
        # Count current entries
        pipe.zcard(key)
        
        # Get oldest entry timestamp
        pipe.zrange(key, 0, 0, withscores=True)
        
        results = pipe.execute()
        current_count = results[1]
        
        if current_count >= self.max_requests:
            # Get reset time from oldest entry
            oldest = results[2]
            if oldest:
                oldest_time = oldest[0][1]
                reset_in = int(oldest_time + self.window_seconds - now) + 1
            else:
                reset_in = self.window_seconds
            return False, max(1, reset_in)
        
        # Add new entry
        client.zadd(key, {str(now): now})
        client.expire(key, self.window_seconds + 1)
        
        return True, 0
    
    def _check_memory(self, identifier: str) -> tuple[bool, int]:
        """Check rate limit using in-memory storage."""
        now = time.time()
        window_start = now - self.window_seconds
        
        with _memory_lock:
            # Clean old entries
            timestamps = _memory_rate_limits[identifier]
            timestamps[:] = [ts for ts in timestamps if ts > window_start]
            
            if len(timestamps) >= self.max_requests:
                reset_in = int(timestamps[0] + self.window_seconds - now) + 1
                return False, max(1, reset_in)
            
            timestamps.append(now)
            return True, 0
    
    def reset(self, identifier: str) -> None:
        """Reset rate limit for identifier."""
        client = get_redis_client()
        
        if client:
            client.delete(self._get_key(identifier))
        else:
            with _memory_lock:
                _memory_rate_limits.pop(identifier, None)
    
    def get_remaining(self, identifier: str) -> int:
        """Get remaining requests for identifier."""
        client = get_redis_client()
        
        if client:
            key = self._get_key(identifier)
            window_start = time.time() - self.window_seconds
            client.zremrangebyscore(key, 0, window_start)
            count = client.zcard(key)
            return max(0, self.max_requests - count)
        else:
            with _memory_lock:
                now = time.time()
                window_start = now - self.window_seconds
                timestamps = _memory_rate_limits[identifier]
                timestamps[:] = [ts for ts in timestamps if ts > window_start]
                return max(0, self.max_requests - len(timestamps))


# Default rate limiters
ai_rate_limiter = RateLimiter(
    key_prefix="ai_requests",
    max_requests=10,
    window_seconds=60,
)

scrape_rate_limiter = RateLimiter(
    key_prefix="scrape_jobs",
    max_requests=3,
    window_seconds=300,  # 5 minutes
)


def cache_get(key: str) -> Optional[str]:
    """Get value from cache."""
    client = get_redis_client()
    if client:
        return client.get(key)
    return None


def cache_set(key: str, value: str, ttl_seconds: int = 3600) -> bool:
    """Set value in cache with TTL."""
    client = get_redis_client()
    if client:
        client.setex(key, ttl_seconds, value)
        return True
    return False


def cache_delete(key: str) -> bool:
    """Delete value from cache."""
    client = get_redis_client()
    if client:
        client.delete(key)
        return True
    return False
