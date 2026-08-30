def apply_webhook(event, store):
    if store.seen(event.id):
        return store.response(event.id)
    return store.apply(event)
