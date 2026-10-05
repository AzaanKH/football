"""
Model Store

Holds the trained WeeklyPredictor for the API and reloads it when the model
file changes on disk (e.g. after the scheduler's Tuesday retrain), so a
running server never serves a stale model and never needs a restart.
"""

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class ModelStore:
    """Thread-safe, lazily (re)loaded model keyed on the file's modification time."""

    def __init__(self, path: str, loader: Callable[[str], object]):
        """
        Args:
            path: Model pickle path
            loader: Function loading a model from path (e.g. WeeklyPredictor.load)
        """
        self.path = path
        self._loader = loader
        self._lock = threading.Lock()
        self._model = None
        self._loaded_mtime: Optional[int] = None
        self._failed_mtime: Optional[int] = None
        self.loaded_at: Optional[datetime] = None
        self.last_error: Optional[str] = None

    def _file_mtime(self) -> Optional[int]:
        try:
            return os.stat(self.path).st_mtime_ns
        except FileNotFoundError:
            return None

    def get(self):
        """
        Return the current model, reloading first if the file changed.

        A file that fails to load keeps the previous model in service and is
        not retried until the file changes again. Returns None if no model
        has ever loaded.
        """
        mtime = self._file_mtime()
        if mtime is None or mtime in (self._loaded_mtime, self._failed_mtime):
            return self._model

        with self._lock:
            if mtime not in (self._loaded_mtime, self._failed_mtime):
                try:
                    self._model = self._loader(self.path)
                    self._loaded_mtime = mtime
                    self._failed_mtime = None
                    self.loaded_at = datetime.now(timezone.utc)
                    self.last_error = None
                    logger.info(f"Loaded model from {self.path}")
                except Exception as e:
                    self._failed_mtime = mtime
                    self.last_error = f"{type(e).__name__}: {e}"
                    logger.error(f"Failed to load model from {self.path}: {self.last_error}")
            return self._model

    def status(self) -> dict:
        """Describe the loaded model for /model_status."""
        return {
            'path': self.path,
            'file_exists': self._file_mtime() is not None,
            'loaded_at': self.loaded_at.isoformat() if self.loaded_at else None,
            'last_load_error': self.last_error,
        }
