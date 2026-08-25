"""Comprehensive SSRF penetration and safety tests."""

import pytest
from src.verifier.safe_url import SSRFValidationError, SafeURLValidator


def test_ssrf_blocks_private_ipv4():
    blocked = [
        "http://127.0.0.1:8545",
        "http://127.0.1.1:8545",
        "http://10.0.0.1:8545",
        "http://10.254.254.254:8545",
        "http://172.16.0.1:8545",
        "http://172.31.255.255:8545",
        "http://192.168.0.1:8545",
        "http://192.168.100.200:8545",
        "http://0.0.0.0:8545",
    ]
    for url in blocked:
        with pytest.raises(SSRFValidationError):
            SafeURLValidator.validate_url(url)


def test_ssrf_blocks_cloud_metadata_ip():
    metadata_urls = [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254/computeMetadata/v1/",
        "http://169.254.1.1:8080",
    ]
    for url in metadata_urls:
        with pytest.raises(SSRFValidationError):
            SafeURLValidator.validate_url(url)


def test_ssrf_blocks_ipv6_special_ranges():
    ipv6_blocked = [
        "http://[::1]:8545",
        "http://[fe80::1]:8545",
        "http://[fc00::1]:8545",
        "http://[ff02::1]:8545",
    ]
    for url in ipv6_blocked:
        with pytest.raises(SSRFValidationError):
            SafeURLValidator.validate_url(url)


def test_ssrf_blocks_unauthorized_schemes_and_ports():
    invalid_schemes = [
        "ftp://public.node.com/rpc",
        "file:///etc/passwd",
        "gopher://public.node.com",
        "ws://public.node.com",
    ]
    for url in invalid_schemes:
        with pytest.raises(SSRFValidationError):
            SafeURLValidator.validate_url(url)

    invalid_ports = [
        "http://1.1.1.1:22",
        "http://1.1.1.1:25",
        "http://1.1.1.1:3306",
        "http://1.1.1.1:6379",
        "http://1.1.1.1:27017",
    ]
    for url in invalid_ports:
        with pytest.raises(SSRFValidationError):
            SafeURLValidator.validate_url(url)
