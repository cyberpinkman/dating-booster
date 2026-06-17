import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from subprocess import CompletedProcess

from dating_boost.core.encryption import DataKeyProvider, EncryptionError, _security_cli_available


class EncryptionTests(unittest.TestCase):
    def test_keychain_lookup_timeout_raises_encryption_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                "os.environ",
                {"DATING_BOOST_KEY_PROVIDER": "keychain", "DATING_BOOST_KEYCHAIN_TIMEOUT_SECONDS": "0.1"},
            ):
                with patch(
                    "dating_boost.core.encryption.subprocess.run",
                    side_effect=subprocess.TimeoutExpired(["security", "find-generic-password"], 0.1),
                ):
                    provider = DataKeyProvider(Path(temp_dir))

                    with self.assertRaisesRegex(EncryptionError, "lookup timed out"):
                        provider.load_existing_key()

    def test_keychain_store_timeout_raises_encryption_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                "os.environ",
                {"DATING_BOOST_KEY_PROVIDER": "keychain", "DATING_BOOST_KEYCHAIN_TIMEOUT_SECONDS": "0.1"},
            ):
                with patch(
                    "dating_boost.core.encryption.subprocess.run",
                    side_effect=subprocess.TimeoutExpired(["security", "add-generic-password"], 0.1),
                ):
                    provider = DataKeyProvider(Path(temp_dir))

                    with self.assertRaisesRegex(EncryptionError, "store timed out"):
                        provider.store_key(b"x" * 32)

    def test_keychain_lookup_is_cached_per_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"DATING_BOOST_KEY_PROVIDER": "keychain"}):
                with patch(
                    "dating_boost.core.encryption.subprocess.run",
                    return_value=CompletedProcess(["security"], 44, "", "missing"),
                ) as run:
                    provider = DataKeyProvider(Path(temp_dir))

                    self.assertIsNone(provider.load_existing_key())
                    self.assertIsNone(provider.load_existing_key())
                    self.assertEqual(run.call_count, 1)

    def test_security_cli_probe_timeout_returns_unavailable(self):
        with patch.dict("os.environ", {"DATING_BOOST_KEYCHAIN_TIMEOUT_SECONDS": "0.1"}):
            with patch(
                "dating_boost.core.encryption.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["security", "-h"], 0.1),
            ):
                self.assertFalse(_security_cli_available())


if __name__ == "__main__":
    unittest.main()
