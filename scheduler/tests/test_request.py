import unittest

from schedulermp.http_client import _ca_candidates, safe_url
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

    def test_log_url_hides_keys(self):
        url = safe_url("https://example.test/Agency/GetDRCDetails?certificateNumber=DRC/1&api_key=secret")
        self.assertIn("certificateNumber=DRC%2F1", url)
        self.assertIn("api_key=%2A%2A%2A", url)
        self.assertNotIn("secret", url)

    def test_ca_candidates_keep_existing_files_once(self):
        found = _ca_candidates()
        self.assertEqual(len(found), len(set(found)))
        for path in found:
            self.assertTrue(path.endswith(".crt") or path.endswith(".pem") or "ca-certificates" in path)


if __name__ == "__main__":
    unittest.main()
