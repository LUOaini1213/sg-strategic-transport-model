"""Loaded by pytest before any test module, so before NumPy: see the note in stm/__init__.py."""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
