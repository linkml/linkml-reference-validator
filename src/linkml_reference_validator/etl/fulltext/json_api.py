"""Declarative custom full-text provider driven by FullTextProviderConfig."""

import logging
import os
import re
import time
from typing import Optional

import requests  # type: ignore
from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JsonPathParserError

from linkml_reference_validator.models import (
    FullTextLocation,
    FullTextProviderConfig,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)
from linkml_reference_validator.etl.fulltext.base import FullTextProvider

logger = logging.getLogger(__name__)


class JSONAPIFullTextProvider(FullTextProvider):
    """A full-text provider whose behavior is defined by configuration.

    The ``url_template`` may reference ``{doi}``, ``{pmid}``, or ``{pmcid}``.

    Examples:
        >>> from linkml_reference_validator.models import FullTextProviderConfig
        >>> cfg = FullTextProviderConfig(
        ...     name="myrepo",
        ...     url_template="https://api.example.org/ft/{doi}",
        ...     location_field="$.pdf_url",
        ... )
        >>> provider = JSONAPIFullTextProvider(cfg)
        >>> provider._name
        'myrepo'
        >>> from linkml_reference_validator.models import ReferenceIdentifiers
        >>> provider._build_url(ReferenceIdentifiers(doi="10.1/x"))
        'https://api.example.org/ft/10.1/x'
        >>> provider._build_url(ReferenceIdentifiers(pmid="123")) is None
        True
    """

    def __init__(self, provider_config: FullTextProviderConfig):
        self._config = provider_config

    @classmethod
    def name(cls) -> str:
        return ""  # instances carry the real name; see _name

    @property
    def _name(self) -> str:
        return self._config.name

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        url = self._build_url(ids)
        if url is None:
            return None

        time.sleep(config.rate_limit_delay)
        headers = self._interpolate_headers(self._config.headers)
        headers.setdefault("Accept", "application/json")
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.debug(f"Custom provider '{self._name}' returned {response.status_code}")
            return None

        data = response.json()

        if self._config.text_field:
            text = self._jsonpath(data, self._config.text_field)
            if text:
                return FullTextLocation(
                    text=text, format_hint=self._config.format_hint or "text", provider=self._name
                )

        if self._config.location_field:
            location_url = self._jsonpath(data, self._config.location_field)
            if location_url:
                return FullTextLocation(
                    url=location_url, format_hint=self._config.format_hint, provider=self._name
                )

        return None

    def _build_url(self, ids: ReferenceIdentifiers) -> Optional[str]:
        template = self._config.url_template
        values = {"doi": ids.doi, "pmid": ids.pmid, "pmcid": ids.pmcid}
        for key, value in values.items():
            placeholder = "{" + key + "}"
            if placeholder in template:
                if not value:
                    return None
                template = template.replace(placeholder, value)
        return template

    def _jsonpath(self, data: dict, expression: str) -> Optional[str]:
        try:
            parsed = jsonpath_parse(expression)
        except JsonPathParserError as exc:
            logger.warning(f"Invalid JSONPath '{expression}': {exc}")
            return None
        matches = parsed.find(data)
        if matches and matches[0].value is not None:
            value = matches[0].value
            return value if isinstance(value, str) else str(value)
        return None

    def _interpolate_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Substitute ``${VAR}`` references with environment variables.

        Warns (rather than silently substituting an empty string) when a referenced
        variable is unset, so a missing/misspelled API key surfaces as a clear log
        line instead of a confusing downstream 401.
        """
        pattern = re.compile(r"\$\{([^}]+)\}")

        def replace_env(match: "re.Match[str]") -> str:
            var_name = match.group(1)
            value = os.environ.get(var_name)
            if value is None:
                logger.warning(
                    "Custom provider '%s' header references unset environment "
                    "variable '%s'; substituting an empty string",
                    self._name,
                    var_name,
                )
                return ""
            return value

        return {key: pattern.sub(replace_env, value) for key, value in headers.items()}
