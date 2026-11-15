import pytest

from rat.domain.translation import ProviderConfig
from rat.providers.settings_service import ProviderSettingsService
from rat.security.secrets import SecretStore, SecretStoreError


class MemoryVault:
    def __init__(self):
        self.values = {}

    def set_password(self, service, profile, key):
        self.values[service, profile] = key

    def get_password(self, service, profile):
        return self.values.get((service, profile))

    def delete_password(self, service, profile):
        self.values.pop((service, profile), None)


def test_keys_are_stored_only_in_the_injected_vault_not_project_files(project):
    vault = MemoryVault()
    config = ProviderConfig(provider_id="openai", model="chosen-model")
    service = ProviderSettingsService(project.path, secrets=SecretStore(backend=vault))
    secret = "SYNTHETIC_SECRET_NEVER_AN_ACTUAL_KEY"
    service.save(config, secret)
    assert service.profiles() == [config]
    assert secret == SecretStore(backend=vault).get(config.profile_id)
    for path in project.path.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()
    SecretStore(backend=vault).delete(config.profile_id)
    assert SecretStore(backend=vault).get(config.profile_id) == ""


def test_unknown_or_plaintext_keyring_backend_is_rejected_without_fallback(monkeypatch):
    vault = MemoryVault()
    monkeypatch.setattr(SecretStore, "_discover_backend", staticmethod(lambda: vault))
    with pytest.raises(SecretStoreError, match="secure_storage_unavailable"):
        SecretStore().save("profile", "secret")
    assert not vault.values


def test_endpoint_change_cannot_inherit_a_key_for_the_old_endpoint(project):
    config = ProviderConfig(provider_id="custom", model="model", base_url="https://one.example/v1")
    service = ProviderSettingsService(project.path, secrets=SecretStore(backend=MemoryVault()))
    service.save(config, "synthetic")
    with pytest.raises(ValueError):
        service.save(config.model_copy(update={"base_url": "https://two.example/v1"}))
