from .query import load_invoices


def invoices_route(database, session):
    return load_invoices(database, session.tenant_id)
