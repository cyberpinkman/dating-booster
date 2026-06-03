from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ENCRYPTED_PAYLOAD_SCHEMA_VERSION = 1
KEYCHAIN_BINDING_SCHEMA_VERSION = 1
BACKUP_RECOVERY_KEY_SCHEMA_VERSION = 1
ENVELOPE_ALGORITHM = "AES-256-GCM"
RECOVERY_KEY_KDF = "PBKDF2-HMAC-SHA256"
RECOVERY_KEY_ITERATIONS = 600_000
RECOVERY_KEY_ASSOCIATED_DATA = b"dating_boost_backup_recovery_key_v1"
KEYCHAIN_SERVICE = "dating-booster"
LOCAL_KEY_NAME = ".dating_boost_key"


class EncryptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class EncryptionStatus:
    enabled: bool
    provider: str
    key_id: str | None


class PayloadCipher:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.provider = DataKeyProvider(self.root)

    def status(self) -> EncryptionStatus:
        key = self.provider.load_or_create_key()
        return EncryptionStatus(True, self.provider.provider_name, _key_id(key))

    def status_without_creating_key(self) -> EncryptionStatus:
        key = self.provider.load_existing_key()
        return EncryptionStatus(key is not None, self.provider.provider_name, _key_id(key) if key else None)

    def encrypt_json(self, payload: Any, *, associated_data: str) -> str:
        key = self.provider.load_or_create_key()
        nonce = secrets.token_bytes(12)
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        aesgcm = _aesgcm(key)
        ciphertext = aesgcm.encrypt(nonce, data, associated_data.encode("utf-8"))
        envelope = {
            "schema_version": ENCRYPTED_PAYLOAD_SCHEMA_VERSION,
            "encrypted": True,
            "algorithm": ENVELOPE_ALGORITHM,
            "key_id": _key_id(key),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        return json.dumps(envelope, ensure_ascii=False, sort_keys=True)

    def decrypt_json(self, stored: str, *, associated_data: str) -> Any:
        try:
            envelope = json.loads(stored)
        except json.JSONDecodeError as exc:
            raise EncryptionError("stored payload is not valid JSON") from exc
        if not isinstance(envelope, dict) or envelope.get("encrypted") is not True:
            return envelope
        if envelope.get("algorithm") != ENVELOPE_ALGORITHM:
            raise EncryptionError(f"unsupported payload encryption algorithm: {envelope.get('algorithm')}")
        key = self.provider.load_existing_key()
        if key is None:
            raise EncryptionError("payload decryption key is unavailable")
        try:
            nonce = base64.b64decode(str(envelope["nonce"]))
            ciphertext = base64.b64decode(str(envelope["ciphertext"]))
            plaintext = _aesgcm(key).decrypt(nonce, ciphertext, associated_data.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - normalize cryptography/key errors.
            raise EncryptionError("payload decryption failed") from exc
        return json.loads(plaintext.decode("utf-8"))

    def rotate_key(self) -> bytes:
        return self.provider.rotate_key()

    def encrypt_recovery_key(self, passphrase: str) -> dict[str, Any]:
        if not passphrase:
            raise EncryptionError("recovery passphrase is required")
        data_key = self.provider.load_or_create_key()
        salt = secrets.token_bytes(16)
        wrapping_key = _derive_recovery_wrapping_key(passphrase, salt)
        nonce = secrets.token_bytes(12)
        ciphertext = _aesgcm(wrapping_key).encrypt(nonce, data_key, RECOVERY_KEY_ASSOCIATED_DATA)
        return {
            "schema_version": BACKUP_RECOVERY_KEY_SCHEMA_VERSION,
            "encrypted": True,
            "algorithm": ENVELOPE_ALGORITHM,
            "kdf": RECOVERY_KEY_KDF,
            "iterations": RECOVERY_KEY_ITERATIONS,
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

    def decrypt_recovery_key(self, envelope: dict[str, Any], passphrase: str) -> bytes:
        if not passphrase:
            raise EncryptionError("recovery passphrase is required")
        if envelope.get("schema_version") != BACKUP_RECOVERY_KEY_SCHEMA_VERSION:
            raise EncryptionError("unsupported backup recovery key schema")
        if envelope.get("algorithm") != ENVELOPE_ALGORITHM or envelope.get("kdf") != RECOVERY_KEY_KDF:
            raise EncryptionError("unsupported backup recovery key envelope")
        try:
            salt = base64.b64decode(str(envelope["salt"]))
            nonce = base64.b64decode(str(envelope["nonce"]))
            ciphertext = base64.b64decode(str(envelope["ciphertext"]))
            iterations = int(envelope.get("iterations") or RECOVERY_KEY_ITERATIONS)
            wrapping_key = _derive_recovery_wrapping_key(passphrase, salt, iterations=iterations)
            data_key = _aesgcm(wrapping_key).decrypt(nonce, ciphertext, RECOVERY_KEY_ASSOCIATED_DATA)
        except Exception as exc:  # noqa: BLE001 - normalize key/password/envelope failures.
            raise EncryptionError("backup recovery key decryption failed") from exc
        if len(data_key) != 32:
            raise EncryptionError("backup recovery key has invalid length")
        return data_key

    def store_raw_key(self, key: bytes) -> None:
        self.provider.store_key(key)


class DataKeyProvider:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.account = hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()
        self.provider_name = self._provider_name()

    def load_or_create_key(self) -> bytes:
        env_key = os.environ.get("DATING_BOOST_TEST_KEY")
        if env_key:
            return _normalize_key_material(env_key.encode("utf-8"))
        if self.provider_name == "keychain":
            existing = self._load_keychain_key()
            if existing is not None:
                return existing
            key = secrets.token_bytes(32)
            self._store_keychain_key(key)
            return key
        existing = self._load_local_key()
        if existing is not None:
            return existing
        key = secrets.token_bytes(32)
        self.store_key(key)
        return key

    def load_existing_key(self) -> bytes | None:
        env_key = os.environ.get("DATING_BOOST_TEST_KEY")
        if env_key:
            return _normalize_key_material(env_key.encode("utf-8"))
        if self.provider_name == "keychain":
            return self._load_keychain_key()
        return self._load_local_key()

    def rotate_key(self) -> bytes:
        key = secrets.token_bytes(32)
        self.store_key(key)
        return key

    def store_key(self, key: bytes) -> None:
        if len(key) != 32:
            raise EncryptionError("data encryption key must be 32 bytes")
        if self.provider_name == "keychain" and not os.environ.get("DATING_BOOST_TEST_KEY"):
            self._store_keychain_key(key)
            return
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / LOCAL_KEY_NAME
        path.write_text(base64.b64encode(key).decode("ascii") + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _provider_name(self) -> str:
        explicit = os.environ.get("DATING_BOOST_KEY_PROVIDER")
        if explicit in {"local", "keychain"}:
            return explicit
        if platform.system() == "Darwin" and _security_cli_available():
            return "keychain"
        return "local"

    def _load_local_key(self) -> bytes | None:
        path = self.root / LOCAL_KEY_NAME
        if not path.exists():
            return None
        try:
            return base64.b64decode(path.read_text(encoding="utf-8").strip())
        except Exception as exc:  # noqa: BLE001
            raise EncryptionError("local data key is unreadable") from exc

    def _load_keychain_key(self) -> bytes | None:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", self.account, "-w"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        try:
            return base64.b64decode(result.stdout.strip())
        except Exception as exc:  # noqa: BLE001
            raise EncryptionError("keychain data key is unreadable") from exc

    def _store_keychain_key(self, key: bytes) -> None:
        encoded = base64.b64encode(key).decode("ascii")
        result = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                self.account,
                "-w",
                encoded,
                "-U",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise EncryptionError(result.stderr.strip() or "failed to store keychain data key")


def payload_is_encrypted(stored: str) -> bool:
    try:
        payload = json.loads(stored)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("encrypted") is True


def _aesgcm(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - dependency smoke catches this.
        raise EncryptionError("cryptography package is required for encrypted storage") from exc
    return AESGCM(key)


def _normalize_key_material(material: bytes) -> bytes:
    try:
        decoded = base64.b64decode(material, validate=True)
    except Exception:
        decoded = b""
    if len(decoded) == 32:
        return decoded
    return hashlib.sha256(material).digest()


def _derive_recovery_wrapping_key(passphrase: str, salt: bytes, *, iterations: int = RECOVERY_KEY_ITERATIONS) -> bytes:
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError as exc:  # pragma: no cover - dependency smoke catches this.
        raise EncryptionError("cryptography package is required for backup recovery keys") from exc
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _key_id(key: bytes) -> str:
    return "key_" + hashlib.sha256(key).hexdigest()[:16]


def _security_cli_available() -> bool:
    try:
        result = subprocess.run(["security", "-h"], check=False, capture_output=True, text=True)
    except OSError:
        return False
    return result.returncode in {0, 1, 64}
