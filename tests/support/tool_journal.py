class MemoryJournal:
    """Test-only public protocol fixture; RunStore never contains effect records."""
    identity = "owned-ledger-v1"
    contract_version = "tool-journal-v1"

    def __init__(self):
        self.records = {}
        self.claims = []

    def claim(self, namespace, key, signature):
        from prosaic_runtime import ToolClaim
        self.claims.append((namespace, key))
        record = self.records.get((namespace, key))
        if record is None:
            self.records[(namespace, key)] = (signature, None)
            return ToolClaim('new', signature, claim_token='fence-v1')
        signature, outcome = record
        return ToolClaim('uncertain', signature) if outcome is None else ToolClaim('replay', signature, outcome=outcome)

    def commit(self, namespace, key, token, outcome):
        assert token == 'fence-v1'
        signature, _ = self.records[(namespace, key)]
        self.records[(namespace, key)] = (signature, outcome)
