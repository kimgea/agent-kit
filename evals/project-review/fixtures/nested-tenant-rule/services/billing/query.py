def load_invoices(database, authenticated_tenant_id):
    return database.execute("SELECT * FROM invoices ORDER BY created_at")
