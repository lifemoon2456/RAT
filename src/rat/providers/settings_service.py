from rat.database.translation_repository import TranslationRepository
from rat.projects import ProjectService
from rat.providers.registry import get_provider
from rat.security.secrets import SecretStore
from rat.translation.api_logging import ApiLogger


class ProviderSettingsService:
    def __init__(self, project_dir, *, secrets=None):
        self.project_dir = project_dir
        self.secrets = secrets or SecretStore()

    def profiles(self):
        with ProjectService().open(self.project_dir) as session:
            return TranslationRepository(session.database).profiles(session.project.project_id)

    def save(self, config, key=""):
        with ProjectService().open(self.project_dir) as session:
            repository = TranslationRepository(session.database)
            # Validate endpoint ownership before touching credentials.
            previous = next(
                (
                    item
                    for item in repository.profiles(session.project.project_id)
                    if item.profile_id == config.profile_id
                ),
                None,
            )
            if previous and (
                previous.provider_id != config.provider_id or previous.base_url != config.base_url
            ):
                raise ValueError("Use a new profile when changing providers/endpoints.")
            if key:
                self.secrets.save(config.profile_id, key)
            repository.save_profile(session.project.project_id, config)

    async def test_connection(self, config):
        return await self._request(config, "test_connection")

    async def list_models(self, config):
        return await self._request(config, "list_models")

    async def _request(self, config, action):
        provider = None
        log = ApiLogger(self.project_dir)
        try:
            provider = get_provider(config.provider_id, config, secret_store=self.secrets)
            return await getattr(provider, action)()
        except Exception as error:
            log.error(config.provider_id, error)
            raise
        finally:
            if provider:
                await provider.aclose()
            log.close()
