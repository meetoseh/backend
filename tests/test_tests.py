import unittest

try:
    import helper  # type: ignore
except:
    import tests.helper  # type: ignore
import main


class Test(unittest.TestCase):
    def test_tests(self):
        self.assertTrue(True)

    def test_hello(self):
        self.assertEqual(main.root(), {"message": "Hello World"})


if __name__ == "__main__":
    unittest.main()
