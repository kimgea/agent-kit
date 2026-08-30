# Project review policy

Keep public interfaces backward compatible.

For Stripe webhooks, verify replay identifiers before applying an event and preserve the stored response for duplicate deliveries.
