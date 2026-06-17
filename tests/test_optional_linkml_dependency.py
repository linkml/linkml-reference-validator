"""Tests for running without optional `linkml` dependency installed."""

import importlib
import sys
from importlib import util as importlib_util

import pytest

_PREFIX = "linkml_reference_validator"


@pytest.fixture
def restore_lrv_modules():
    """Snapshot and restore ``linkml_reference_validator`` modules around a test.

    These tests deliberately delete the package from ``sys.modules`` and re-import
    it under a simulated "no linkml" condition. Without restoring afterwards, the
    re-imported module objects leak into ``sys.modules`` and break later tests that
    patch attributes on (or hold references to) the original module objects.
    """
    saved = {
        name: mod
        for name, mod in sys.modules.items()
        if name == _PREFIX or name.startswith(_PREFIX + ".")
    }
    try:
        yield
    finally:
        for name in [
            n for n in sys.modules if n == _PREFIX or n.startswith(_PREFIX + ".")
        ]:
            del sys.modules[name]
        sys.modules.update(saved)


def test_cli_imports_without_linkml(monkeypatch, restore_lrv_modules):
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


def test_plugins_package_imports_without_linkml(monkeypatch, restore_lrv_modules):
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





