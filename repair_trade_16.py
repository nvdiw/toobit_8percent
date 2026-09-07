"""Deprecated: the strategy ledger must be repaired as a chain, not one margin."""
if __name__ == "__main__":
    raise SystemExit("Use repair_local_ledger.py database.db --report audit.json first, then --apply. The old single-trade repair mixed local and exchange accounting.")
