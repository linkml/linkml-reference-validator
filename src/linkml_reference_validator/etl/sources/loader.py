"""Loader for custom JSON API source configurations.

Loads source definitions from YAML files and registers them with the source registry.

Source configurations are read from four places. When the same prefix is
defined in more than one, the most specific one wins:

1. Explicit ``sources_file`` (highest precedence)
2. ``sources:`` section of the explicit main ``config_file``
3. Project-level: ``.linkml-reference-validator-sources.yaml`` (or ``.yml``)
   in the cwd; if both exist, ``.yaml`` wins
4. User-level: ``~/.config/linkml-reference-validator/sources/*.yaml``
   (and ``*.yml``; lowest precedence; files are read in sorted order by
   name and later names win)

Prefixes defined at only one level are always kept.

Examples:
    >>> from linkml_reference_validator.etl.sources.loader import load_custom_sources
    >>> # Load sources from default locations
    >>> sources = load_custom_sources()
"""

import logging
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML

from linkml_reference_validator.models import JSONAPISourceConfig

logger = logging.getLogger(__name__)


PROJECT_SOURCES_FILENAMES = (
    ".linkml-reference-validator-sources.yaml",
    ".linkml-reference-validator-sources.yml",
)


def load_custom_sources(
    config_file: Optional[Path] = None,
    sources_file: Optional[Path] = None,
    *,
    project_dir: Optional[Path] = None,
    user_config_dir: Optional[Path] = None,
) -> list[JSONAPISourceConfig]:
    """Load custom source configurations from various locations.

    Precedence when a prefix is defined more than once (highest first):

    1. Explicit ``sources_file``
    2. Explicit ``config_file``'s ``sources`` section
    3. Project-level: ``.linkml-reference-validator-sources.yaml``
       (then ``.yml``)
    4. User-level: ``<user_config_dir>/sources/*.yaml`` and ``*.yml``

    Args:
        config_file: Optional path to main config file containing 'sources' section
        sources_file: Optional path to dedicated sources config file
        project_dir: Directory holding the project-level sources file
            (default: the current working directory)
        user_config_dir: User config root; sources are read from its
            ``sources/`` subdirectory
            (default: ``~/.config/linkml-reference-validator``)

    Returns:
        List of loaded source configurations, one per prefix

    Examples:
        >>> sources = load_custom_sources()
        >>> isinstance(sources, list)
        True
    """
    if project_dir is None:
        project_dir = Path(".")
    if user_config_dir is None:
        user_config_dir = Path.home() / ".config" / "linkml-reference-validator"

    # Load lowest precedence first; later entries override earlier ones.
    configs: list[JSONAPISourceConfig] = []

    # 4. User-level sources directory, in sorted order for determinism
    user_sources_dir = user_config_dir / "sources"
    if user_sources_dir.exists():
        user_files = [*user_sources_dir.glob("*.yaml"), *user_sources_dir.glob("*.yml")]
        for user_file in sorted(user_files, key=lambda f: f.name):
            configs.extend(_load_sources_from_file(user_file))

    # 3. Project-level sources file (.yml first so .yaml wins if both exist)
    for filename in reversed(PROJECT_SOURCES_FILENAMES):
        project_file = project_dir / filename
        if project_file.exists():
            configs.extend(_load_sources_from_file(project_file))

    # 2. Main config file's 'sources' section
    if config_file and config_file.exists():
        configs.extend(_load_sources_from_main_config(config_file))

    # 1. Explicit sources file
    if sources_file and sources_file.exists():
        configs.extend(_load_sources_from_file(sources_file))

    # Deduplicate by prefix (later entries override earlier ones)
    seen_prefixes: dict[str, JSONAPISourceConfig] = {}
    for config in configs:
        if config.prefix in seen_prefixes:
            logger.debug(f"Overriding source config for prefix: {config.prefix}")
        seen_prefixes[config.prefix] = config

    return list(seen_prefixes.values())


def _load_sources_from_file(file_path: Path) -> list[JSONAPISourceConfig]:
    """Load source configurations from a YAML file.

    File format:
    ```yaml
    sources:
      PREFIX_NAME:
        url_template: "https://api.example.com/{id}"
        fields:
          title: "$.path.to.title"
          content: "$.path.to.content"
        id_patterns:
          - "^PATTERN\\d+$"
        headers:
          Authorization: "Bearer ${API_KEY}"
        store_raw_response: true
    ```

    Args:
        file_path: Path to YAML file

    Returns:
        List of parsed source configurations

    Examples:
        >>> from pathlib import Path
        >>> # Would load from file:
        >>> # configs = _load_sources_from_file(Path("sources.yaml"))
    """
    configs: list[JSONAPISourceConfig] = []

    yaml = YAML(typ="safe")
    data = yaml.load(file_path)

    if not isinstance(data, dict):
        logger.warning(f"Invalid sources file format: {file_path}")
        return configs

    sources_data = data.get("sources", data)
    if not isinstance(sources_data, dict):
        logger.warning(f"No valid 'sources' section in: {file_path}")
        return configs

    for prefix, source_data in sources_data.items():
        # Skip non-source keys
        if not isinstance(source_data, dict) or "url_template" not in source_data:
            continue

        config = _parse_source_config(prefix, source_data)
        if config:
            configs.append(config)
            logger.debug(f"Loaded source config: {prefix}")

    return configs


def _load_sources_from_main_config(config_file: Path) -> list[JSONAPISourceConfig]:
    """Load sources from the 'sources' section of main config file.

    Args:
        config_file: Path to main config file

    Returns:
        List of parsed source configurations
    """
    yaml = YAML(typ="safe")
    data = yaml.load(config_file)

    if not isinstance(data, dict):
        return []

    sources_data = data.get("sources")
    if not isinstance(sources_data, dict):
        return []

    configs: list[JSONAPISourceConfig] = []
    for prefix, source_data in sources_data.items():
        if not isinstance(source_data, dict) or "url_template" not in source_data:
            continue
        config = _parse_source_config(prefix, source_data)
        if config:
            configs.append(config)

    return configs


def _parse_source_config(prefix: str, data: dict) -> Optional[JSONAPISourceConfig]:
    """Parse a single source configuration from dict.

    Args:
        prefix: Source prefix (e.g., 'MGNIFY')
        data: Source configuration dict

    Returns:
        JSONAPISourceConfig if valid, None otherwise

    Examples:
        >>> data = {
        ...     "url_template": "https://api.example.com/{id}",
        ...     "fields": {"title": "$.title"},
        ... }
        >>> config = _parse_source_config("TEST", data)
        >>> config.prefix
        'TEST'
        >>> config.url_template
        'https://api.example.com/{id}'
    """
    url_template = data.get("url_template")
    if not url_template:
        logger.warning(f"Source '{prefix}' missing required 'url_template'")
        return None

    fields = data.get("fields", {})
    if not isinstance(fields, dict):
        logger.warning(f"Source '{prefix}' has invalid 'fields' (must be dict)")
        return None

    if not fields:
        logger.warning(f"Source '{prefix}' has no 'fields' defined")
        return None

    id_patterns = data.get("id_patterns", [])
    if not isinstance(id_patterns, list):
        id_patterns = [id_patterns] if id_patterns else []

    headers = data.get("headers", {})
    if not isinstance(headers, dict):
        headers = {}

    store_raw = data.get("store_raw_response", False)

    return JSONAPISourceConfig(
        prefix=prefix,
        url_template=url_template,
        fields=fields,
        id_patterns=id_patterns,
        headers=headers,
        store_raw_response=bool(store_raw),
    )


def register_custom_sources(
    config_file: Optional[Path] = None,
    sources_file: Optional[Path] = None,
) -> int:
    """Load and register custom sources with the source registry.

    Args:
        config_file: Optional path to main config file
        sources_file: Optional path to dedicated sources file

    Returns:
        Number of sources registered

    Examples:
        >>> count = register_custom_sources()
        >>> isinstance(count, int)
        True
    """
    from linkml_reference_validator.etl.sources.json_api import register_json_api_source

    configs = load_custom_sources(config_file, sources_file)
    registered = 0

    for config in configs:
        register_json_api_source(config)
        registered += 1
        logger.info(f"Registered custom source: {config.prefix}")

    return registered
