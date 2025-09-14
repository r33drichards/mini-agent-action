# easy to fix failing test
import unittest
from unittest import TestCase

def add(a, b):
    return a + b

class Test(TestCase):
    def test_failing(self):
        self.assertEqual(add(1, 2), 3)

if __name__ == "__main__":
    unittest.main()