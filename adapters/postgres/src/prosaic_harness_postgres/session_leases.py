"""Scoped conversation leases use the existing bounded renewal lifecycle."""
from .leases import PostgresLease


class PostgresSessionLease(PostgresLease):
    def __init__(self, store, session_id, scope_content, scope_identity, started):
        super().__init__(store, session_id, started)
        self.session_id = session_id
        self.scope_content = scope_content
        self.scope_identity = scope_identity
