def post(entries, tenant_id):
    """Post one tenant's balanced ledger transaction."""
    if sum(entry.amount for entry in entries) != 0:
        raise ValueError("unbalanced transaction")
    return {"tenant_id": tenant_id, "entries": entries}
