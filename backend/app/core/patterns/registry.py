"""
Pattern Registry — auto-discovers all AbstractPattern subclasses.
To add a new pattern: drop a new file in core/patterns/ and subclass AbstractPattern.
"""
import importlib
import pkgutil
from pathlib import Path
from app.core.patterns.base import AbstractPattern
from loguru import logger


class PatternRegistry:
    _instance: "PatternRegistry | None" = None

    def __init__(self):
        self._patterns: dict[str, AbstractPattern] = {}

    @classmethod
    def get(cls) -> "PatternRegistry":
        if cls._instance is None:
            cls._instance = PatternRegistry()
            cls._instance._discover()
        return cls._instance

    def _discover(self):
        """Auto-import all modules in core/patterns/ to trigger subclass registration."""
        patterns_dir = Path(__file__).parent
        package = "app.core.patterns"
        for finder, name, _ in pkgutil.iter_modules([str(patterns_dir)]):
            if name in ("base", "registry"):
                continue
            try:
                importlib.import_module(f"{package}.{name}")
            except Exception as e:
                logger.warning(f"Could not load pattern module {name}: {e}")

        for cls in AbstractPattern.__subclasses__():
            try:
                instance = cls()
                self._patterns[instance.name] = instance
                logger.info(f"Registered pattern: {instance.name} v{instance.version}")
            except Exception as e:
                logger.warning(f"Could not instantiate {cls.__name__}: {e}")

    def all(self) -> list[AbstractPattern]:
        return list(self._patterns.values())

    def get_pattern(self, name: str) -> AbstractPattern | None:
        return self._patterns.get(name)

    def names(self) -> list[str]:
        return list(self._patterns.keys())


registry = PatternRegistry.get()
