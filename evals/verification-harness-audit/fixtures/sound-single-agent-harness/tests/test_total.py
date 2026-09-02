def total(values):
    return sum(values)


def test_total_contract():
    assert total([2, 3]) == 5
    assert total([]) == 0
    assert total([-2, 3]) == 1
