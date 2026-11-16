import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from schedulermp import keeper


class KeeperTests(unittest.TestCase):
    def test_status_is_stopped_when_no_process_is_recorded(self):
        old_path = os.environ.get("PATH", "")
        old_run = os.environ.get("SCHEDULER_RUN_DIR")
        with tempfile.TemporaryDirectory() as folder:
            os.environ["PATH"] = folder
            os.environ["SCHEDULER_RUN_DIR"] = folder
            try:
                self.assertEqual(keeper.read_pid(keeper.keeper_pid_path()), 0)
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    keeper.status()
            finally:
                os.environ["PATH"] = old_path
                if old_run is None:
                    os.environ.pop("SCHEDULER_RUN_DIR", None)
                else:
                    os.environ["SCHEDULER_RUN_DIR"] = old_run
        self.assertIn("status: stopped", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
