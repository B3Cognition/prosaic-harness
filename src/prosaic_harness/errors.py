"""Safe admission errors, independent of parsers and host execution bindings."""


class WorkflowAdmissionError(ValueError):
    """A stable code and bounded field location, without source data or causes."""

    CODES = frozenset({'invalid_definition', 'invalid_artifact', 'invalid_schema',
                       'unknown_reference', 'policy_denied', 'limit_exceeded',
                       'resource_not_bound', 'binding_mismatch', 'identity_mismatch'})

    def __init__(self, code, location='$'):
        if code not in self.CODES:
            raise ValueError('unknown admission error code')
        self.code = code
        # Locations are supplied by trusted adapters, never parser exception text.
        self.location = ''.join(c for c in str(location)[:256]
                                if c.isascii() and (c.isalnum() or c in '$._[]-')) or '$'
        super().__init__(f'{self.code} at {self.location}')
