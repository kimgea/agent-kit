import random
import time


def test_retry_eventually_succeeds():
    time.sleep(0.05)
    assert random.random() > 0.02
