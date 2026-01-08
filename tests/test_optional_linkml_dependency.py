"""Tests for running without optional `linkml` dependency installed."""

import importlib
import sys
from importlib import util as importlib_util


def test_cli_imports_without_linkml(monkeypatch):
    """Importing the CLI should not require `linkml` to be installed."""

    real_find_spec = importlib_util.find_spec

    def fake_find_spec(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "linkml" or name.startswith("linkml."):
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib_util, "find_spec", fake_find_spec)

    # Force a clean import of our package modules under the "no linkml" condition
    for mod in list(sys.modules):
        if mod.startswith("linkml_reference_validator"):
            del sys.modules[mod]

    cli = importlib.import_module("linkml_reference_validator.cli")
    assert getattr(cli, "app", None) is not None


def test_plugins_package_imports_without_linkml(monkeypatch):
    """Importing `linkml_reference_validator.plugins` should not require `linkml`."""

    real_find_spec = importlib_util.find_spec

    def fake_find_spec(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "linkml" or name.startswith("linkml."):
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib_util, "find_spec", fake_find_spec)

    for mod in list(sys.modules):
        if mod.startswith("linkml_reference_validator"):
            del sys.modules[mod]

    plugins = importlib.import_module("linkml_reference_validator.plugins")
    assert getattr(plugins, "__all__", None) == []





