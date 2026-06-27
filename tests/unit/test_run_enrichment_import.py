from __future__ import annotations

import importlib


def test_run_enrichment_imports_without_name_error() -> None:
    module = importlib.import_module("cyberWatch.enrichment.run_enrichment")

    assert hasattr(module, "main")
    assert hasattr(module, "get_neo4j_driver_with_retry")
