"""Tests for the evaluation set loader and the data files themselves."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from brandguard.eval.dataset import LabelledRecord, layer_counts, load_testset
from brandguard.schema import Publisher

TESTSET_DIR = Path(__file__).resolve().parents[1] / "data" / "testset"


def test_unknown_layer_is_rejected():
    with pytest.raises(ValidationError):
        LabelledRecord(
            record={"app_id": "x", "source": "mock", "name": "x", "publisher": Publisher(name="p")},
            label="unrelated",
            layer="L99",
            rationale="typo",
        )


@pytest.mark.parametrize("path", sorted(TESTSET_DIR.glob("*.json")))
def test_testset_files_load_and_have_rationale(path):
    records = load_testset(path)
    assert records, f"{path.name} is empty"
    for item in records:
        assert item.rationale.strip(), f"{item.record.app_id} has no rationale"


def test_layer_counts_are_sorted_by_layer():
    records = load_testset(TESTSET_DIR / "ornek_bank.json")
    counts = layer_counts(records)
    assert list(counts) == sorted(counts)
