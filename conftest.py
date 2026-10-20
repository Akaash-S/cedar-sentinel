import os
import boto3
import pytest


def pytest_runtest_setup(item):
    if "live" in item.keywords:
        has_creds = False
        try:
            session = boto3.Session()
            creds = session.get_credentials()
            if creds is not None:
                has_creds = True
        except Exception:
            has_creds = False

        if not has_creds:
            pytest.skip("Skipping live test: AWS credentials not present in environment")
