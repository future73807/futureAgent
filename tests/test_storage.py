from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from core.storage import LocalStorage, StorageError, attachment_object_key


class LocalStorageTests(unittest.TestCase):
    def test_tenant_key_is_bounded_to_storage_root_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorage(directory)
            key = attachment_object_key("workspace-a", "report.md")
            storage.put_stream(key, BytesIO(b"# Delivery report"), content_type="text/markdown")
            with storage.open_stream(key) as result:
                self.assertEqual(result.read(), b"# Delivery report")
            self.assertTrue((Path(directory) / "workspaces" / "workspace-a" / "report.md").is_file())

    def test_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorage(directory)
            with self.assertRaises(StorageError):
                storage.put_stream("../outside.txt", BytesIO(b"no"), content_type="text/plain")


if __name__ == "__main__":
    unittest.main()
