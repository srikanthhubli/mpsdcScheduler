import unittest

from schedulermp.server import _id_list, _limit


class RequestShapeTests(unittest.TestCase):
    def test_limit_rejects_text_and_negative_numbers(self):
        self.assertEqual(_limit({}, {}), 0)
        self.assertEqual(_limit({"limit": "2"}, {}), 2)
        with self.assertRaises(ValueError):
            _limit({"limit": "many"}, {})
        with self.assertRaises(ValueError):
            _limit({"limit": -1}, {})

    def test_id_list_accepts_a_list_or_commas(self):
        self.assertEqual(_id_list([" 101 ", ""], "ownerIds"), ["101"])
        self.assertEqual(_id_list("101, 102", "ownerIds"), ["101", "102"])
        with self.assertRaises(ValueError):
            _id_list({"owner": 1}, "ownerIds")


if __name__ == "__main__":
    unittest.main()
