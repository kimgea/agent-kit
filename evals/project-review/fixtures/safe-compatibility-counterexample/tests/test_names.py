from events.names import INTERNAL_CAPTURE_COMPLETE, PUBLIC_PAYMENT_CAPTURED


def test_public_name_is_preserved():
    assert PUBLIC_PAYMENT_CAPTURED == "payment.captured"
    assert INTERNAL_CAPTURE_COMPLETE == PUBLIC_PAYMENT_CAPTURED
