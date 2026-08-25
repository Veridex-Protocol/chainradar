"""The source register is a control, not a document (spec 23).

`SourceRegister.is_enabled()` returns False for an unknown `source_id`, so a
collector missing from the register is silently disabled and its coverage
disappears without an error. These tests keep the register and the code in
step, and check that each entry carries the governance fields spec 23 requires.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest

import src.collectors as collectors_pkg
from src.config import SourceRegister, source_register

REGISTER_PATH = Path(__file__).resolve().parents[1] / "config" / "source_register.yaml"


def _collector_source_ids() -> set[str]:
    found: set[str] = set()
    for module_info in pkgutil.walk_packages(collectors_pkg.__path__, "src.collectors."):
        module = importlib.import_module(module_info.name)
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module_info.name:
                continue
            source_id = getattr(obj, "source_id", None)
            if isinstance(source_id, str) and source_id:
                found.add(source_id)
    return found


def test_every_collector_is_registered():
    """An unregistered collector is a silently disabled collector."""
    missing = _collector_source_ids() - set(source_register.sources)
    assert not missing, (
        f"Collectors absent from config/source_register.yaml would never run: {sorted(missing)}"
    )


def test_register_has_no_phantom_sources():
    """Every registered source_id must correspond to a real collector."""
    phantom = set(source_register.sources) - _collector_source_ids()
    assert not phantom, (
        f"Register lists sources with no collector: {sorted(phantom)}. "
        "Sub-providers polled by one collector belong under its `providers` key."
    )


def test_all_registered_sources_are_enabled_by_default():
    for source_id in source_register.sources:
        assert source_register.is_enabled(source_id) is True


def test_kill_switch_disables_a_single_source_only():
    """Disabling one source must not affect its neighbours."""
    register = SourceRegister(REGISTER_PATH)
    target = "ethereum_lists"
    others = [s for s in register.sources if s != target]

    assert register.set_kill_switch(target, True) is True
    assert register.is_enabled(target) is False
    assert all(register.is_enabled(other) for other in others)

    register.set_kill_switch(target, False)
    assert register.is_enabled(target) is True


def test_unknown_source_is_treated_as_disabled():
    """Fail closed: an unknown source must never be polled."""
    assert source_register.is_enabled("not_a_real_source") is False


@pytest.mark.parametrize("source_id", sorted(source_register.sources))
def test_register_entries_carry_governance_fields(source_id):
    """Spec 23: owner, terms URL, access method, fields stored, retention, rate limit."""
    source = source_register.sources[source_id]
    assert source.owner, f"{source_id} has no owner"
    assert source.terms_url, f"{source_id} has no terms URL"
    assert source.access_method, f"{source_id} has no access method"
    assert source.fields_stored, f"{source_id} does not declare fields stored"
    assert source.retention_days > 0
    assert source.rate_limit.requests_per_minute > 0
    assert 0.0 <= source.reliability <= 1.0


def test_no_prohibited_sources_are_registered():
    """LinkedIn and private communities are prohibited by policy (spec 23)."""
    prohibited = ("linkedin", "telegram", "discord")
    for source_id, source in source_register.sources.items():
        haystack = f"{source_id} {source.name} {source.terms_url}".lower()
        for term in prohibited:
            assert term not in haystack, (
                f"{source_id} references a prohibited source '{term}'"
            )
