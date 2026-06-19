import importlib


def test_core_modules_import_without_live_services():
    modules = [
        "cyberWatch.enrichment.run_enrichment",
        "cyberWatch.workers.worker",
        "cyberWatch.collector.dns_collector",
        "cyberWatch.api.routes.settings",
    ]

    for module in modules:
        importlib.import_module(module)
