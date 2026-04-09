"""
Pytest configuration for backend tests.
Exception engine tests are pure unit tests — no DB or network required.
"""
import pytest


# Marker for tests that require a real database connection
def pytest_configure(config):
    config.addinivalue_line("markers", "db: mark test as requiring a database")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
