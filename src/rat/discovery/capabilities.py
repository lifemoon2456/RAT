from rat.domain.discovery import GameInventory


def capabilities(inventory: GameInventory) -> tuple[str, ...]:
    modes = []
    if any(
        item.extension in {".rpy", ".rpym"} and item.language is None for item in inventory.files
    ):
        modes.append("source_scan")
    if any(item.language == "arabic" and item.sha256 for item in inventory.files):
        modes.append("existing_arabic_templates")
    if not modes:
        modes.append("no_supported_text_source")
    return tuple(modes)
