from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Callable

import pytest


@contextmanager
def fail_once(
    monkeypatch: pytest.MonkeyPatch, target: object, name: str, error: Exception
) -> Generator[None, None, None]:
    """Make one call to the named callable raise, then restore normal calls."""
    original: Callable[..., object] = getattr(target, name)
    failed = False

    def replacement(*args: Any, **kwargs: Any) -> object:
        nonlocal failed
        if not failed:
            failed = True
            raise error
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(target, name, replacement)
        yield


@contextmanager
def fail_always(
    monkeypatch: pytest.MonkeyPatch, target: object, name: str, error: Exception
) -> Generator[None, None, None]:
    """Make every call to the named callable raise for the context's lifetime."""

    def replacement(*args: Any, **kwargs: Any) -> None:
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(target, name, replacement)
        yield


@contextmanager
def fail_oserror(
    monkeypatch: pytest.MonkeyPatch,
    target: object,
    name: str,
    error_no: int,
    *,
    always: bool = False,
) -> Generator[None, None, None]:
    """Inject an OSError with a specific errno, once or on every call."""
    error = OSError(error_no, os.strerror(error_no))
    injector = fail_always if always else fail_once
    with injector(monkeypatch, target, name, error):
        yield
