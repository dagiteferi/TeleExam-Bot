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
                        base_url=settings.BACKEND_URL,
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
    ) -> Optional[T]:
        """
        Makes an HTTP request to the backend, injecting security headers.

        Args:
            method: HTTP method (e.g., "GET", "POST").
            path: API endpoint path (e.g., "/users/upsert").
            telegram_id: The Telegram user ID to include in headers.
            payload: Dictionary to be sent as JSON body.
            response_model: Optional Pydantic model to parse the response into.

        Returns:
            Parsed response data or None on error.
        """
        session = await self._get_session()
        headers = {
            "X-Telegram-Secret": settings.BACKEND_SECRET,
            "X-Telegram-Id": str(telegram_id),
            "Content-Type": "application/json",
        }

        try:
            async with session.request(
                method, path, json=payload, headers=headers
            ) as response:
                response.raise_for_status()  # Raise an exception for 4xx or 5xx status codes
                if response.status == 204:  # No Content
                    return None
                data = await response.json()
                if response_model:
                    return response_model.model_validate(data)
                return data
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

    async def get(
        self,
        path: str,
        telegram_id: int,
        response_model: Optional[Type[T]] = None,
    ) -> Optional[T]:
        """Performs a GET request to the backend."""
        return await self._request("GET", path, telegram_id, response_model=response_model)

    async def post(
        self,
        path: str,
        telegram_id: int,
        payload: Dict[str, Any],
        response_model: Optional[Type[T]] = None,
    ) -> Optional[T]:
        """Performs a POST request to the backend."""
        return await self._request("POST", path, telegram_id, payload, response_model)

    async def put(
        self,
        path: str,
        telegram_id: int,
        payload: Dict[str, Any],
        response_model: Optional[Type[T]] = None,
    ) -> Optional[T]:
        """Performs a PUT request to the backend."""
        return await self._request("PUT", path, telegram_id, payload, response_model)

    async def delete(
        self,
        path: str,
        telegram_id: int,
        response_model: Optional[Type[T]] = None,
    ) -> Optional[T]:
        """Performs a DELETE request to the backend."""
        return await self._request("DELETE", path, telegram_id, response_model=response_model)


# Export a single instance for use throughout the bot
api_client = ApiClient()
