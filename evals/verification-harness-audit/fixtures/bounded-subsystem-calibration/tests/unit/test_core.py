import unittest

from src.core import rectangle_area


class CoreTests(unittest.TestCase):
    def test_rectangle_area(self):
        self.assertEqual(12, rectangle_area(3, 4))
        self.assertEqual(0, rectangle_area(0, 4))
