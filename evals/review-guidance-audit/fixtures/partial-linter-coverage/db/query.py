def load_order(database, tenant_id, order_id):
    return database.query(
        "SELECT * FROM orders WHERE tenant_id = ? AND id = ?",
        tenant_id,
        order_id,
    )
