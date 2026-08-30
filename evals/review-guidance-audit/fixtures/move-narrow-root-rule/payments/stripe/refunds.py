def apply_refund(event, store):
    if store.seen(event.id):
        return store.response(event.id)
    return store.refund(event)
