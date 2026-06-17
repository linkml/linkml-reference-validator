"""Load and register declarative custom full-text providers from YAML.

Search order mirrors sources/loader.py:
1. Explicit providers_file
2. Project-level: .linkml-reference-validator-fulltext.yaml
3. User-level: ~/.config/linkml-reference-validator/fulltext/*.yaml
"""

import logging
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML

from linkml_reference_validator.models import FullTextProviderConfig
from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry
from linkml_reference_validator.etl.fulltext.json_api import JSONAPIFullTextProvider

logger = logging.getLogger(__name__)


def load_custom_full_text_providers(
    providers_file: Optional[Path] = None,
) -> list[FullTextProviderConfig]:
    """Load custom provider configs from the standard locations.

    Examples:
        >>> configs = load_custom_full_text_providers()
        >>> isinstance(configs, list)
        True
    """
    configs: list[FullTextProviderConfig] = []

    if providers_file and providers_file.exists():
        configs.extend(_load_from_file(providers_file))

    project_file = Path(".linkml-reference-validator-fulltext.yaml")
    if project_file.exists():
        configs.extend(_load_from_file(project_file))

    user_dir = Path.home() / ".config" / "linkml-reference-validator" / "fulltext"
    if user_dir.exists():
        for yaml_file in sorted(user_dir.glob("*.yaml")):
            configs.extend(_load_from_file(yaml_file))

    deduped: dict[str, FullTextProviderConfig] = {}
    for cfg in configs:
        deduped[cfg.name] = cfg
    return list(deduped.values())


def _load_from_file(file_path: Path) -> list[FullTextProviderConfig]:
    yaml = YAML(typ="safe")
    data = yaml.load(file_path)
    if not isinstance(data, dict):
        logger.warning(f"Invalid full-text providers file: {file_path}")
        return []

    providers_data = data.get("full_text_providers", data)
    if not isinstance(providers_data, dict):
        return []

    configs: list[FullTextProviderConfig] = []
    for name, body in providers_data.items():
        if not isinstance(body, dict) or "url_template" not in body:
            continue
        configs.append(
            FullTextProviderConfig(
                name=name,
                url_template=body["url_template"],
                location_field=body.get("location_field"),
                text_field=body.get("text_field"),
                format_hint=body.get("format_hint"),
                headers=body.get("headers", {}) if isinstance(body.get("headers"), dict) else {},
            )
        )
    return configs


def register_custom_full_text_providers(
    providers_file: Optional[Path] = None,
) -> int:
    """Load and register custom providers; return the number registered.

    Examples:
        >>> count = register_custom_full_text_providers()
        >>> isinstance(count, int)
        True
    """
    configs = load_custom_full_text_providers(providers_file)
    for cfg in configs:
        FullTextProviderRegistry.register_instance(cfg.name, JSONAPIFullTextProvider(cfg))
        logger.info(f"Registered custom full-text provider: {cfg.name}")
    return len(configs)
