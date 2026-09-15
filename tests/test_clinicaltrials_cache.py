"""ClinicalTrials identifier aliases must share source and cache identities."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from linkml_reference_validator.etl.reference_fetcher import (
    EXTRACTOR_CACHE_VERSION,
    ReferenceFetcher,
)
from linkml_reference_validator.etl.sources.clinicaltrials import ClinicalTrialsSource
from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
)


ALIASES = [
    "NCT12345678",
    "clinicaltrials:NCT12345678",
    "CLINICALTRIALS:NCT12345678",
    " ClinicalTrials:nct12345678 ",
    "nct12345678",
    "trial:NCT12345678",
]
CANONICAL = "clinicaltrials:NCT12345678"


def test_committed_trial_fixture_uses_canonical_path(test_config, trial_server):
    """Fixture cache hits must work on case-sensitive filesystems without HTTP."""
    test_config.fetch_full_text = False
    requests, state = trial_server
    state["status"] = 503
    fetcher = ReferenceFetcher(test_config)
    expected = fetcher.get_cache_path("clinicaltrials:NCT00000001")
    assert expected.name in {path.name for path in expected.parent.iterdir()}
    result = fetcher.fetch("NCT00000001")
    assert result is not None
    assert result.title == "A Phase III Study of Drug X for Treatment of Disease Y"
    assert requests == []


@pytest.mark.parametrize("reference_id", ["NCT1234567", "NCT123456789", "NCTabcdefgh"])
def test_near_miss_trial_ids_remain_unknown(trial_config, reference_id):
    """Only bare NCT IDs matching the source's eight-digit pattern are claimed."""
    fetcher = ReferenceFetcher(trial_config)
    assert fetcher._parse_reference_id(reference_id) == ("UNKNOWN", reference_id)
    assert fetcher.normalize_reference_id(reference_id) == reference_id


@pytest.mark.parametrize("second_target", ["C", "clinicaltrials"])
def test_cache_paths_do_not_reapply_unrelated_prefix_maps(tmp_path, second_target):
    """Fetching applies an unrelated prefix alias once, including on disk reads."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path,
        reference_prefix_map={"A": "B", "B": second_target},
        fetch_full_text=False,
    )
    path = tmp_path / "B_NCT12345678.md"
    path.write_text(
        "---\nreference_id: B:NCT12345678\n"
        f"extractor_version: {EXTRACTOR_CACHE_VERSION}\n"
        "content_type: summary\n---\n\nExisting evidence\n"
    )
    fetcher = ReferenceFetcher(config)
    assert fetcher.normalize_reference_id("A:NCT12345678") == "B:NCT12345678"
    assert fetcher.get_cache_path("B:NCT12345678") == path
    result = fetcher.fetch("A:NCT12345678")
    assert result is not None
    assert result.content == "Existing evidence"


@pytest.fixture
def trial_server(monkeypatch):
    """Serve real HTTP trial responses and record every attempted fetch."""
    requests = []
    state = {"status": 200}

    class Handler(BaseHTTPRequestHandler):
        """Provide a minimal ClinicalTrials API response or a service failure."""

        def do_GET(self):
            """Record the request and return the selected response."""
            requests.append(self.path)
            self.send_response(state["status"])
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "protocolSection": {
                            "identificationModule": {"briefTitle": "Local trial"},
                            "descriptionModule": {"briefSummary": "Trial evidence"},
                        }
                    }
                ).encode()
            )

        def log_message(self, format, *args):
            """Keep the test server quiet."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        "linkml_reference_validator.etl.sources.clinicaltrials.CLINICALTRIALS_API_URL",
        f"http://127.0.0.1:{server.server_port}/studies/{{nct_id}}",
    )
    try:
        yield requests, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def trial_config(tmp_path):
    """Use isolated public/private caches and a mixed-case prefix alias."""
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "public",
        private_cache_dir=tmp_path / "private",
        reference_prefix_map={"trial": "ClinicalTrials"},
        fetch_full_text=False,
        rate_limit_delay=0,
    )


@pytest.mark.parametrize("reference_id", ALIASES)
def test_trial_alias_normalization(trial_config, reference_id):
    """Bare IDs, case variants, and configured aliases have one identity."""
    fetcher = ReferenceFetcher(trial_config)
    normalized = fetcher.normalize_reference_id(reference_id)
    assert normalized == CANONICAL
    assert fetcher.normalize_reference_id(normalized) == CANONICAL
    assert ReferenceSourceRegistry.get_source(normalized) is ClinicalTrialsSource
    assert fetcher.get_cache_path(normalized).name == "clinicaltrials_NCT12345678.md"
    if reference_id.startswith("trial:"):
        # Path helpers retain their existing contract: aliases are resolved by
        # normalize_reference_id (or fetch), not applied again during disk I/O.
        assert fetcher.get_cache_path(reference_id).name == "trial_NCT12345678.md"
    else:
        assert (
            fetcher.get_cache_path(reference_id).name == "clinicaltrials_NCT12345678.md"
        )


@pytest.mark.parametrize("reference_id", ALIASES)
def test_existing_canonical_cache_reused(trial_config, trial_server, reference_id):
    """A new fetcher reads an existing canonical cache without any HTTP call."""
    requests, state = trial_server
    state["status"] = 503
    path = trial_config.get_cache_dir() / "clinicaltrials_NCT12345678.md"
    text = (
        f"---\nreference_id: {CANONICAL}\n"
        f"extractor_version: {EXTRACTOR_CACHE_VERSION}\n"
        "title: Existing trial\ncontent_type: summary\n---\n\nTrial evidence\n"
    )
    path.write_text(text)
    result = ReferenceFetcher(trial_config).fetch(reference_id)
    assert result is not None
    assert result.title == "Existing trial"
    assert requests == []
    assert path.read_text() == text
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("reference_id", ALIASES)
def test_trial_fetch_memory_disk_and_force_refresh(
    trial_config, trial_server, reference_id
):
    """Aliases reuse fetched evidence, while force-refresh always calls the API."""
    requests, state = trial_server
    fetcher = ReferenceFetcher(trial_config)
    first = fetcher.fetch(reference_id)
    assert first is not None
    assert first.reference_id == CANONICAL
    for alias in ALIASES:
        assert fetcher.fetch(alias) is first
    assert list(fetcher._cache) == [CANONICAL]
    assert requests == ["/studies/NCT12345678"]
    for alias in ALIASES:
        cached = ReferenceFetcher(trial_config).fetch(alias)
        assert cached is not None
        assert cached.content == first.content
    assert len(requests) == 1
    refreshed = fetcher.fetch(ALIASES[2], force_refresh=True)
    assert refreshed is not None
    assert fetcher.fetch(ALIASES[0]) is refreshed
    assert len(requests) == 2
    state["status"] = 503
    assert fetcher.fetch(ALIASES[0], force_refresh=True) is None
    assert len(requests) == 3
    assert ReferenceFetcher(trial_config).fetch(ALIASES[0]) is not None
    assert len(requests) == 3
    assert [p.name for p in trial_config.get_cache_dir().iterdir()] == [
        "clinicaltrials_NCT12345678.md"
    ]


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("reference_id", ALIASES)
def test_trial_cache_write_normalizes(trial_config, reference_id, private):
    """Disk writes canonicalize NCT syntax, preserve aliases, and isolate private data."""
    fetcher = ReferenceFetcher(trial_config)
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id=reference_id, content="Trial evidence", content_type="summary"
        ),
        private=private,
    )
    directory = (
        trial_config.get_private_cache_dir()
        if private
        else trial_config.get_cache_dir()
    )
    # Source records already carry canonical IDs. If a caller supplies an alias
    # directly, persistence must not reinterpret it using configured mappings.
    filename = (
        "trial_NCT12345678.md"
        if reference_id.startswith("trial:")
        else "clinicaltrials_NCT12345678.md"
    )
    path = directory / filename
    assert path.exists()
    loaded = ReferenceFetcher(trial_config)._load_from_disk(reference_id)
    if private:
        assert loaded is None
        assert path.stat().st_mode & 0o777 == 0o600
    else:
        assert loaded is not None
        assert loaded.content == "Trial evidence"
