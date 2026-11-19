def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "network: multicast on the local interface; set PYSOS_NETWORK_TESTS=1 to run",
    )
