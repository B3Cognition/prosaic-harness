"""Separate PostgreSQL adapter for Prosaic Harness."""
__version__ = '0.2.1'

from .store import PostgresRunStore

__all__ = ['PostgresRunStore']
