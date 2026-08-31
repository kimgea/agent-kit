from api.enums import DeliveryState


def test_wire_values_are_stable():
    assert int(DeliveryState.PENDING) == 1
    assert int(DeliveryState.SENT) == 2
