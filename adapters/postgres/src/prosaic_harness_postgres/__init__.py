"""Separate PostgreSQL adapter for Prosaic Harness."""
__version__ = '0.2.0'

from .store import PostgresRunStore

__all__ = ['PostgresRunStore']
