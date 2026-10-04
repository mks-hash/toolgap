"""Existing SGLang admin control transport; caller owns prefix/model identity."""

import time
from typing import Callable, Optional

import httpx


class PrefetchRejected(RuntimeError):
    """Server rejected admission or a control payload; generation may continue."""


class PrefetchClient:
    def __init__(
        self,
        base_url: str,
        *,
        headers=None,
        timeout=2.0,
        transport=None,
        on_event: Optional[Callable] = None,
    ):
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            transport=transport,
        )
        self.on_event = on_event

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self):
        await self._http.aclose()

    async def _request(self, action, operation_id, **fields):
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 128:
            raise ValueError("operation_id must contain 1..128 characters")

        def emit(phase):
            if self.on_event:
                self.on_event(
                    dict(
                        action=action,
                        operation_id=operation_id,
                        phase=phase,
                        at_ns=time.monotonic_ns(),
                    )
                )

        emit("send")
        try:
            response = await self._http.post(
                "/hicache/prefetch",
                json=dict(action=action, operation_id=operation_id, **fields),
            )
            if response.status_code == 400:
                raise PrefetchRejected(response.json().get("message", "rejected"))
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success"):
                raise PrefetchRejected(payload.get("message", "rejected"))
            return payload["result"]
        finally:
            emit("receive_or_error")

    async def submit(self, operation_id, input_ids, *, cache_salt=None, ttl_ms=10000):
        if not input_ids or any(type(t) is not int or t < 0 for t in input_ids):
            raise ValueError("Provide exact nonnegative integer token IDs")
        if cache_salt is not None and (
            not isinstance(cache_salt, str) or len(cache_salt) > 256
        ):
            raise ValueError("cache_salt must be a string of at most256 characters")
        if type(ttl_ms) is not int or not 1 <= ttl_ms <= 60000:
            raise ValueError("ttl_ms must be in1..60000")
        return await self._request(
            "submit",
            operation_id,
            input_ids=list(input_ids),
            cache_salt=cache_salt,
            ttl_ms=ttl_ms,
        )

    async def status(self, operation_id):
        return await self._request("status", operation_id)

    async def cancel(self, operation_id):
        return await self._request("cancel", operation_id)
