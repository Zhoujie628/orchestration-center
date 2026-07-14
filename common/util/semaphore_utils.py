"""Async semaphore utilities for FastAPI endpoint concurrency control."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

import anyio
from fastapi import HTTPException

@asynccontextmanager
async def try_acquire_semaphore(semaphore: anyio.Semaphore, busy_detail: str = "Server is busy") -> AsyncIterator[None]:
    """Acquire a semaphore with non-blocking semantics, raising 503 if busy.

    Usage::

        async with try_acquire_semaphore(my_semaphore):
            # ... do work ...
    """
    acquired = False
    try:
        semaphore.acquire_nowait()
        acquired = True
        yield
    except anyio.WouldBlock:
        raise HTTPException(status_code=503, detail=busy_detail)
    finally:
        if acquired:
            semaphore.release()
