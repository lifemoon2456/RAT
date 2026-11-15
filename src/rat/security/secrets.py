import os

import keyring


class SecretStoreError(ValueError):
    def __init__(self):
        super().__init__("secure_storage_unavailable")


class SecretStore:
    SERVICE = "RenPyArabicTranslator.API"

    def __init__(self, *, backend=None):
        self.backend = backend

    def _backend(self):
        backend = self.backend or self._discover_backend()
        # Do not silently accept keyrings.alt/plaintext or an unknown chained fallback.
        allowed = {
            "keyring.backends.Windows",
            "keyring.backends.macOS",
            "keyring.backends.SecretService",
            "keyring.backends.kwallet",
        }
        if self.backend is None and type(backend).__module__ not in allowed:
            raise SecretStoreError()
        return backend

    @staticmethod
    def _discover_backend():
        if os.name == "nt":
            from keyring.backends.Windows import WinVaultKeyring

            backend = WinVaultKeyring()
            _ = backend.priority
            return backend
        return keyring.get_keyring()

    def save(self, profile_id: str, secret: str) -> None:
        if not secret.strip():
            raise ValueError("empty_key")
        try:
            self._backend().set_password(self.SERVICE, profile_id, secret)
        except Exception:
            raise SecretStoreError() from None

    def get(self, profile_id: str) -> str:
        try:
            return self._backend().get_password(self.SERVICE, profile_id) or ""
        except Exception:
            raise SecretStoreError() from None

    def delete(self, profile_id: str) -> None:
        try:
            backend = self._backend()
            if backend.get_password(self.SERVICE, profile_id):
                backend.delete_password(self.SERVICE, profile_id)
        except Exception:
            raise SecretStoreError() from None
