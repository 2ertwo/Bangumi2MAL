from __future__ import annotations

import time
from typing import Any, Optional

import httpx


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class BaseApiClient:
    def __init__(self, base_url: str, headers: Optional[dict[str, str]] = None):
        self.client = httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Optional[Exception] = None
        for attempt in range(4):
            try:
                response = self.client.request(method, url, **kwargs)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt == 3:
                    break
                time.sleep(2**attempt)
                continue

            if response.status_code < 400:
                return response

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 3:
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        delay = min(60.0, float(retry_after))
                    except ValueError:
                        delay = float(2**attempt)
                    time.sleep(delay)
                    continue

            detail = ""
            try:
                payload = response.json()
                detail = payload.get("message") or payload.get("error") or str(payload)
            except (ValueError, AttributeError):
                detail = response.text[:300]
            raise ApiError(
                f"API request failed ({response.status_code}): {detail}", response.status_code
            )

        raise ApiError(f"API request failed after retries: {last_error}")
