"""Execution counts use real schemas and cached publications, independently of issues."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from linkml.validator import Validator  # type: ignore[import-untyped]
from typer.testing import CliRunner

from linkml_reference_validator.cli import app
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)

QUOTE = "Protein X functions in cell cycle regulation"


@pytest.fixture
def counting_setup(tmp_path, fixtures_dir):
    """Provide a real schema, cache, plugin and reusable LinkML validator."""
    schema = tmp_path / "schema.yaml"
    schema.write_text("""
id: https://example.org/counts
name: counts
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/
default_prefix: ex
classes:
  Evidence:
    tree_root: true
    attributes:
      reference:
        range: string
      supporting_text:
        range: string
      snippet:
        range: string
        implements: [linkml:excerpt]
      title:
        range: string
""")
    cache = tmp_path / "cache"
    cache.mkdir()
    for source in fixtures_dir.glob("*.md"):
        (cache / source.name).write_text(source.read_text())
    plugin = ReferenceValidationPlugin(
        config=ReferenceValidationConfig(
            cache_dir=cache, fetch_full_text=False, skip_prefixes=["GO"]
        )
    )
    return (
        schema,
        cache,
        plugin,
        Validator(schema=str(schema), validation_plugins=[plugin]),
    )


@pytest.mark.parametrize(
    "instance, expected, issues",
    [
        (
            {
                "reference": "PMID:TEST001",
                "supporting_text": QUOTE,
                "snippet": QUOTE,
                "title": QUOTE,
            },
            (2, 0, 0, 2),
            0,
        ),
        (
            {
                "reference": "PMID:TEST001",
                "supporting_text": "This quotation is fabricated",
            },
            (1, 0, 0, 0),
            1,
        ),
        ({"reference": "PMID:TEST001", "title": QUOTE}, (0, 0, 0, 1), 0),
        ({"reference": "PMID:TEST001", "title": "Wrong title"}, (0, 0, 0, 1), 1),
        (
            {
                "reference": "PMID:TEST001",
                "supporting_text": "A fabricated quotation",
                "title": "Wrong title",
            },
            (1, 0, 0, 1),
            1,
        ),
        ({"reference": "GO:123", "title": QUOTE}, (0, 0, 0, 0), 0),
        ({"reference": "UNSUPPORTED:123", "title": QUOTE}, (0, 0, 0, 0), 1),
        ({"reference": "GO:123", "supporting_text": QUOTE}, (0, 1, 0, 0), 0),
        ({"reference": "UNSUPPORTED:123", "supporting_text": QUOTE}, (0, 0, 1, 0), 1),
        ({"supporting_text": ""}, (0, 0, 0, 0), 1),
        ({"supporting_text": QUOTE}, (0, 0, 0, 0), 0),
    ],
)
def test_plugin_execution_counts(counting_setup, instance, expected, issues):
    """Count comparisons, including failures, without treating issues or skips as checks."""
    _, _, plugin, validator = counting_setup
    report = validator.validate(instance)
    assert len(report.results) == issues
    assert (
        plugin.snippets_checked,
        plugin.snippets_skipped,
        plugin.snippets_unavailable,
        plugin.titles_checked,
    ) == expected
    validator.validate({})
    assert (
        plugin.snippets_checked,
        plugin.snippets_skipped,
        plugin.snippets_unavailable,
        plugin.titles_checked,
    ) == (0, 0, 0, 0)


def test_cli_counts_across_lists_and_files(counting_setup, tmp_path):
    """Aggregate each validation call once and list only failing paths in the summary."""
    schema, cache, _, _ = counting_setup
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps(
            [{"reference": "PMID:TEST001", "supporting_text": QUOTE, "snippet": QUOTE}]
            * 2
        )
    )
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {"reference": "PMID:TEST001", "supporting_text": "A fabricated quotation"}
        )
    )
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("bare scalar")
    result = CliRunner().invoke(
        app,
        [
            "validate",
            "data",
            str(good),
            str(bad),
            str(invalid),
            "--schema",
            str(schema),
            "--cache-dir",
            str(cache),
            "--no-full-text",
        ],
    )
    assert result.exit_code == 1, result.output
    summary = result.output.split("Validation Summary:")[1]
    assert "Snippets checked: 5" in summary
    assert "Issues found: 1" in summary
    assert str(bad) in summary and str(invalid) in summary
    assert str(good) not in summary


@pytest.mark.parametrize(
    "data, checks",
    [({}, 0), ([], 0), ({"reference": "PMID:TEST001", "supporting_text": QUOTE}, 1)],
)
def test_cli_clean_counts(counting_setup, tmp_path, data, checks):
    """A clean run exposes whether any snippets were compared without changing exit status."""
    schema, cache, _, _ = counting_setup
    path: Path = tmp_path / "data.json"
    path.write_text(json.dumps(data))
    result = CliRunner().invoke(
        app,
        [
            "validate",
            "data",
            str(path),
            "--schema",
            str(schema),
            "--cache-dir",
            str(cache),
            "--no-full-text",
        ],
    )
    assert result.exit_code == 0, result.output
    assert f"Snippets checked: {checks}" in result.output
    assert "Issues found: 0" in result.output
    assert ("No snippet comparisons were performed" in result.output) == (checks == 0)


def test_unavailable_http_reference(counting_setup):
    """An actual HTTP failure emits an issue but cannot count as a comparison."""
    requested_paths = []

    class UnavailableHandler(BaseHTTPRequestHandler):
        """Serve a deterministic missing-reference response."""

        def do_GET(self):
            """Reject the requested reference."""
            requested_paths.append(self.path)
            self.send_error(404)

        def log_message(self, format, *args):
            """Suppress routine test server logging."""

    _, _, plugin, validator = counting_setup
    server = ThreadingHTTPServer(("127.0.0.1", 0), UnavailableHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        report = validator.validate(
            {
                "reference": f"http://127.0.0.1:{server.server_port}/missing.txt",
                "supporting_text": QUOTE,
            }
        )
        assert len(report.results) == 1
        assert plugin.snippets_checked == 0
        assert plugin.snippets_unavailable == 1
        assert requested_paths == ["/missing.txt"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("data", [None, "scalar", [None, 42, "scalar"]])
def test_invalid_input_summary(counting_setup, tmp_path, data):
    """Invalid input stays a failing file with zero checks and no fabricated issues."""
    schema, cache, _, _ = counting_setup
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data))
    result = CliRunner().invoke(
        app,
        [
            "validate",
            "data",
            str(path),
            "--schema",
            str(schema),
            "--cache-dir",
            str(cache),
            "--no-full-text",
        ],
    )
    assert result.exit_code == 1, result.output
    summary = result.output.split("Validation Summary:")[1]
    assert "Snippets checked: 0" in summary
    assert "Issues found: 0" in summary
    assert summary.count(str(path)) == 1


@pytest.mark.parametrize("content", [None, "broken: [yaml"])
def test_unreadable_file_summary(counting_setup, tmp_path, content):
    """Read and parse failures retain the path and allow later files to be checked."""
    schema, cache, _, _ = counting_setup
    broken = tmp_path / "broken.yaml"
    if content is not None:
        broken.write_text(content)
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"reference": "PMID:TEST001", "supporting_text": QUOTE}))
    result = CliRunner().invoke(
        app,
        [
            "validate",
            "data",
            str(broken),
            str(good),
            "--schema",
            str(schema),
            "--cache-dir",
            str(cache),
            "--no-full-text",
        ],
    )
    assert result.exit_code == 1, result.output
    assert "Validation Summary:" in result.output
    summary = result.output.split("Validation Summary:")[1]
    assert str(broken) in summary
    assert str(good) not in summary
    assert "Snippets checked: 1" in summary
