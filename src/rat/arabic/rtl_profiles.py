import re

from rat.domain.arabic import CompatibilityProfile, RuntimeOptions
from rat.domain.discovery import EngineVersion


def compatibility(version: str | None) -> CompatibilityProfile:
    if not version or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        return CompatibilityProfile(version=None, supported=False, mode="unknown")
    numbers = tuple(map(int, version.split(".")))
    if numbers[0] == 7 or (numbers[0] == 8 and numbers < (8, 2, 0)):
        return CompatibilityProfile(
            version=version,
            supported=False,
            mode="legacy_unverified",
            warnings=("legacy_requires_separate_runtime_validation",),
        )
    if (8, 3, 7) <= numbers < (8, 4, 0):
        return CompatibilityProfile(
            version=version,
            supported=False,
            mode="known_regression",
            warnings=("mixed_direction_regression",),
        )
    if numbers[0] != 8:
        return CompatibilityProfile(version=version, supported=False, mode="unsupported")
    return CompatibilityProfile(
        version=version,
        supported=True,
        mode="native",
        reading_order=numbers >= (8, 4, 0),
        warnings=() if numbers == (8, 5, 3) else ("version_not_live_tested",),
    )


def resolve_profile(detected: EngineVersion, options: RuntimeOptions) -> CompatibilityProfile:
    if detected.confidence == "conflict":
        raise ValueError("engine_version_conflict")
    target = detected.version
    if options.target_version:
        if not options.target_version_confirmed:
            raise ValueError("confirm_target_version")
        if target and target != options.target_version:
            raise ValueError("target_version_conflicts_with_game")
        target = options.target_version
    # An extraction SDK is never evidence of the game's engine version.
    return compatibility(target)
