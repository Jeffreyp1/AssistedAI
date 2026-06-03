import os
import sys

# Make 'tools', 'analysis', 'models', and 'store' importable from the backend root.
sys.path.insert(0, os.path.dirname(__file__))

import pytest

from tools import fda_client, pubmed_client, trials_client


@pytest.fixture(autouse=True)
def _clear_api_caches():
    """Reset the clients' module-level TTL caches so tests stay isolated."""
    for client in (pubmed_client, trials_client, fda_client):
        client.search.cache_clear()
    yield
