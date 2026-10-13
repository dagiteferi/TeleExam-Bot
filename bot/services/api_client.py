import asyncio
import json
from typing import Any, Dict, Optional, Type, TypeVar

import aiohttp
from pydantic import BaseModel, ValidationError

from bot.config import settings

# Type variable for Pydantic models
T = TypeVar("T", bound=BaseModel)


class UserBannedError(Exception):
    """Raised when the backend rejects a request because the user is banned.

    Handled centrally by the dispatcher's error handler, which tells the user.
    """

    def __init__(self, reason: Optional[str] = None, banned_until: Optional[str] = None):
        super().__init__("user is banned")
        self.reason = reason
        self.banned_until = banned_until


def _banned_error_from(status: int, text: str) -> Optional[UserBannedError]:
    if status != 403:
        return None
    try:
        error = json.loads(text).get("error", {})
    except (ValueError, AttributeError):
        return None
    if not isinstance(error, dict) or error.get("code") != "user_banned":
        return None
    return UserBannedError(error.get("reason"), error.get("banned_until"))


class ApiClient:
    """
    Singleton API client for interacting with the FastAPI backend.

    Manages a single aiohttp.ClientSession and injects necessary security headers.
    """

    _instance: Optional["ApiClient"] = None
    _session: Optional[aiohttp.ClientSession] = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __new__(cls) -> "ApiClient":
        """Ensures only one instance of ApiClient is created."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def _get_session(self) -> aiohttp.ClientSession:
        """Ensures a single aiohttp.ClientSession is used and is open."""
        if self._session is None or self._session.closed:
            async with self._lock:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession(
                        base_url=str(settings.BACKEND_URL),
                        timeout=aiohttp.ClientTimeout(total=15),  # 15 seconds timeout
                    )
        return self._session

    async def close_session(self) -> None:
        """Closes the aiohttp.ClientSession gracefully."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request(
        self,
        method: str,
        path: str,
        telegram_id: int,
        payload: Optional[Dict[str, Any]] = None,
        response_model: Optional[Type[T]] = None,
        timeout: Optional[int] = None,
    ) -> Optional[T]:
        """
        Makes an HTTP request to the backend, injecting security headers.
        """
        session = await self._get_session()
        headers = {
            "X-Telegram-Secret": settings.BACKEND_SECRET,
            "X-Telegram-Id": str(telegram_id),
            "Content-Type": "application/json",
        }

        # Use custom timeout if provided, otherwise fallback to session default
        request_timeout = aiohttp.ClientTimeout(total=timeout) if timeout else None

        try:
            async with session.request(
                method, path, json=payload, headers=headers, timeout=request_timeout
            ) as response:
                if not response.ok:
                    text = await response.text()
                    banned = _banned_error_from(response.status, text)
                    if banned:
                        raise banned
                    # Log failure for all but non-fatal 409s
                    if response.status != 409:
                        print(f"API request failed for {method} {path}: {response.status}, message='{text}', payload={payload}")
                    
                    if response.status == 409:
                        # For conflict, return the JSON response so the caller can extract session_id
                        try:
                            return await response.json()
                        except:
                            return None
                    return None
                if response.status == 204:  # No Content
                    return None
                data = await response.json()
                if response_model:
                    return response_model.model_validate(data)
                return data
        except UserBannedError:
            raise
        except asyncio.TimeoutError:
            print(f"API request timed out for {method} {path}")
            return None
        except aiohttp.ClientError as e:
            # Log the error, but do not expose sensitive data
            print(f"API request failed for {method} {path}: {e}")
            return None
        except ValidationError as e:
            print(f"Response validation failed for {method} {path}: {e}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred during API request: {e}")
            return None

    _cache: Dict[str, Any] = {}
    _cache_ttl: int = 1 # Disable cache for development

    async def get(
        self,
        path: str,
        telegram_id: int,
        response_model: Optional[Type[T]] = None,
        timeout: Optional[int] = None,
        cache_ttl: Optional[int] = None,
    ) -> Optional[T]:
        """Performs a GET request to the backend with smart caching for discovery.

        cache_ttl overrides the default TTL; only pass it for responses that are
        the same for every user (the cache key does not include the user).
        """
        import time
        
        # Only cache discovery endpoints to avoid stale data in exams
        is_discovery = "/discovery/" in path
        cache_key = f"GET:{path}"
        
        if is_discovery:
            cached = self._cache.get(cache_key)
            if cached:
                data, expiry = cached
                if time.time() < expiry:
                    # Return from cache
                    return response_model.model_validate(data) if response_model else data
        
        # Fresh request
        result = await self._request("GET", path, telegram_id, response_model=response_model, timeout=timeout)
        
        if is_discovery and result is not None:
            # Save to cache
            # Convert result back to dict if it's a Pydantic model for safe caching
            cache_data = result.model_dump() if isinstance(result, BaseModel) else result
            self._cache[cache_key] = (cache_data, time.time() + (cache_ttl or self._cache_ttl))
            
        return result

    async def post(
        self,
        path: str,
        telegram_id: int,
        payload: Dict[str, Any],
        response_model: Optional[Type[T]] = None,
        timeout: Optional[int] = None,
    ) -> Optional[T]:
        """Performs a POST request to the backend."""
        return await self._request("POST", path, telegram_id, payload, response_model, timeout=timeout)

    async def post_multipart(
        self,
        path: str,
        telegram_id: int,
        form_data: aiohttp.FormData,
        response_model: Optional[Type[T]] = None,
        timeout: Optional[int] = None,
    ) -> Optional[T]:
        """Performs a POST request to the backend with multipart form data."""
        session = await self._get_session()
        headers = {
            "X-Telegram-Secret": settings.BACKEND_SECRET,
            "X-Telegram-Id": str(telegram_id),
            # Do NOT set Content-Type for multipart/form-data; aiohttp sets it with the boundary
        }
        
        request_timeout = aiohttp.ClientTimeout(total=timeout) if timeout else None
        
        try:
            async with session.post(
                path, data=form_data, headers=headers, timeout=request_timeout
            ) as response:
                if not response.ok:
                    text = await response.text()
                    banned = _banned_error_from(response.status, text)
                    if banned:
                        raise banned
                    print(f"API multipart request failed for {path}: {response.status}, message='{text}'")
                    return None
                data = await response.json()
                if response_model:
                    return response_model.model_validate(data)
                return data
        except UserBannedError:
            raise
        except Exception as e:
            print(f"API multipart request error: {e}")
            return None

    async def put(
        self,
        path: str,
        telegram_id: int,
        payload: Dict[str, Any],
        response_model: Optional[Type[Type[T]]] = None,
        timeout: Optional[int] = None,
    ) -> Optional[T]:
        """Performs a PUT request to the backend."""
        return await self._request("PUT", path, telegram_id, payload, response_model, timeout=timeout)

    async def get_public(
        self,
        path: str,
        timeout: Optional[int] = None,
    ) -> Optional[Any]:
        """
        Performs a GET request to a public backend endpoint (no auth headers required).
        """
        session = await self._get_session()
        request_timeout = aiohttp.ClientTimeout(total=timeout) if timeout else None
        try:
            async with session.get(path, timeout=request_timeout) as response:
                if not response.ok:
                    text = await response.text()
                    print(f"Public API request failed for GET {path}: {response.status}, body='{text}'")
                    return None
                return await response.json()
        except asyncio.TimeoutError:
            print(f"Public API request timed out for GET {path}")
            return None
        except Exception as e:
            print(f"Public API request error for GET {path}: {e}")
            return None

    # ── App Settings cache ────────────────────────────────────────────────────
    _settings_cache: Dict[str, str] = {}
    _settings_cache_expiry: float = 0.0
    _SETTINGS_TTL: int = 300  # 5 minutes

    async def get_app_settings(self) -> Dict[str, str]:
        """
        Returns the public app settings dict, fetched from /api/public/settings.
        Results are cached for 5 minutes.
        """
        import time
        if time.time() < self._settings_cache_expiry and self._settings_cache:
            return self._settings_cache
        data = await self.get_public("/api/public/settings", timeout=5)
        if isinstance(data, dict):
            self._settings_cache = data
            self._settings_cache_expiry = time.time() + self._SETTINGS_TTL
        return self._settings_cache or {}


# Export a single instance for use throughout the bot
api_client = ApiClient()
