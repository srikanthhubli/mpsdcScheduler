import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from schedulermp.clock import active_window, legacy_finished, legacy_open_count, normalize_schedule


TZ = ZoneInfo("Asia/Kolkata")


class ClockTests(unittest.TestCase):
    def test_window_opens_at_the_chosen_time_and_closes_after_the_hours(self):
        start = datetime(2026, 11, 10, 1, 0, tzinfo=TZ)
        self.assertIsNone(active_window(start - timedelta(minutes=1), "01:00", 4))
        window = active_window(start, "01:00", 4)
        self.assertEqual(window[0], start)
        self.assertEqual(window[1], start + timedelta(hours=4))
        self.assertIsNone(active_window(start + timedelta(hours=4), "01:00", 4))

    def test_window_can_cross_midnight(self):
        now = datetime(2026, 11, 11, 0, 30, tzinfo=TZ)
        window = active_window(now, "22:00", 4)
        self.assertEqual(window[0], datetime(2026, 11, 10, 22, 0, tzinfo=TZ))

    def test_legacy_turns_off_only_when_every_row_is_done(self):
        self.assertFalse(legacy_finished([]))
        self.assertTrue(legacy_finished([{"status": "SUCCESS"}, {"status": "SKIPPED"}]))
        self.assertFalse(legacy_finished([{"status": "SUCCESS"}, {"status": "FAILED"}]))
        self.assertEqual(legacy_open_count([{"status": "STOPPED"}, {"status": "SUCCESS"}]), 1)

    def test_schedule_rejects_a_bad_hour_count(self):
        with self.assertRaises(ValueError):
            normalize_schedule({"legacy": {"hours": 20}})


if __name__ == "__main__":
    unittest.main()
