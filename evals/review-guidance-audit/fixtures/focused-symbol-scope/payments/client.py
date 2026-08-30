def refresh_token(token):
    return token.refresh()


def retry_payment(payment, attempts=3):
    """Retry the same idempotent payment operation at most three times."""
    for _ in range(attempts):
        result = payment.try_once()
        if result.accepted:
            return result
    return result


def revoke_token(token):
    token.revoke()
