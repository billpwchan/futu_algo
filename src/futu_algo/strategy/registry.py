"""Strategy registry.

Built-ins register themselves with ``@register``. User strategies can be loaded by

* ``module.path:ClassName`` (importable module), or
* ``path/to/file.py:ClassName`` (a file anywhere on disk), or
* dropping ``.py`` files in a directory listed in ``strategy_paths``; every
  ``Strategy`` subclass with a ``name`` in those files is registered.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any, TypeVar

from futu_algo.errors import StrategyError
from futu_algo.strategy.base import Strategy

_REGISTRY: dict[str, type[Strategy]] = {}
S = TypeVar("S", bound=type[Strategy])


def register(cls: S) -> S:
    if not cls.name:
        raise StrategyError(f"{cls.__name__} needs a non-empty `name` to be registered")
    existing = _REGISTRY.get(cls.name)
    if existing is not None and existing is not cls:
        raise StrategyError(f"Strategy name {cls.name!r} already registered by {existing.__name__}")
    _REGISTRY[cls.name] = cls
    return cls


def _load_builtins() -> None:
    importlib.import_module("futu_algo.strategy.builtin")


def _load_file(path: Path) -> Any:
    module_name = f"futu_algo_user_{path.stem}_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise StrategyError(f"Cannot import strategy file {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_strategy_paths(paths: list[Path]) -> None:
    for base in paths:
        files = [base] if base.is_file() else sorted(Path(base).glob("*.py"))
        for file in files:
            module = _load_file(file)
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, Strategy) and obj is not Strategy and obj.name:
                    _REGISTRY.setdefault(obj.name, obj)


def get_strategy_class(spec: str) -> type[Strategy]:
    _load_builtins()
    if spec in _REGISTRY:
        return _REGISTRY[spec]
    if ":" in spec:
        target, _, class_name = spec.rpartition(":")
        module = (
            _load_file(Path(target)) if target.endswith(".py") else importlib.import_module(target)
        )
        cls = getattr(module, class_name, None)
        if not (inspect.isclass(cls) and issubclass(cls, Strategy)):
            raise StrategyError(f"{spec!r} does not name a Strategy subclass")
        return cls
    raise StrategyError(f"Unknown strategy {spec!r}. Available: {', '.join(sorted(_REGISTRY))}")


def create_strategy(spec: str, params: dict[str, Any] | None = None) -> Strategy:
    return get_strategy_class(spec)(params or {})


def available() -> dict[str, type[Strategy]]:
    _load_builtins()
    return dict(sorted(_REGISTRY.items()))
