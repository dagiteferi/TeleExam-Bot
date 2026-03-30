import asyncio
from typing import Any, Dict, Optional, Type, TypeVar

import aiohttp
from pydantic import BaseModel, ValidationError

from bot.config import settings

# Type variable for Pydantic models
T = TypeVar("T", bound=BaseModel)


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
    _cache_ttl: int = 600 # 10 minutes

    async def get(
        self,
        path: str,
        telegram_id: int,
        response_model: Optional[Type[T]] = None,
        timeout: Optional[int] = None,
    ) -> Optional[T]:
        """Performs a GET request to the backend with smart caching for discovery."""
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
            self._cache[cache_key] = (cache_data, time.time() + self._cache_ttl)
            
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

    async def delete(
        self,
        path: str,
        telegram_id: int,
        response_model: Optional[Type[T]] = None,
        timeout: Optional[int] = None,
    ) -> Optional[T]:
        """Performs a DELETE request to the backend."""
        return await self._request("DELETE", path, telegram_id, response_model=response_model, timeout=timeout)


# Export a single instance for use throughout the bot
api_client = ApiClient()
