"""Tests for the retirement registry schema, loader and shipped data."""

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from modelbump.registry import (
    DuplicateModelError,
    Provider,
    ProviderFile,
    Registry,
    RetiredModel,
    Status,
    load_provider_file,
    load_registry,
)

DATA_DIR = Path(__file__).parents[1] / "src" / "modelbump" / "registry" / "data"


def make_model(**overrides: Any) -> RetiredModel:
    fields: dict[str, Any] = {
        "id": "model-a",
        "announced": date(2026, 1, 1),
        "shutdown": date(2026, 3, 1),
        "replacement": "model-b",
    }
    fields.update(overrides)
    return RetiredModel.model_validate(fields)


def make_file(*models: RetiredModel, provider: str = "openai") -> ProviderFile:
    return ProviderFile.model_validate(
        {
            "provider": provider,
            "source_url": "https://example.com/deprecations",
            "retrieved": date(2026, 10, 8),
            "models": models,
        }
    )


# ----------------------------------------------------------- schema rules


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2025, 12, 31), Status.ACTIVE),
        (date(2026, 1, 1), Status.DEPRECATED),
        (date(2026, 2, 28), Status.DEPRECATED),
        (date(2026, 3, 1), Status.RETIRED),
    ],
)
def test_status_on_boundaries(day: date, expected: Status) -> None:
    assert make_model().status_on(day) is expected


def test_status_without_announcement_is_active_until_shutdown() -> None:
    model = make_model(announced=None)
    assert model.status_on(date(2026, 2, 28)) is Status.ACTIVE


def test_rejects_shutdown_before_announcement() -> None:
    with pytest.raises(ValidationError, match="before announced"):
        make_model(announced=date(2026, 5, 1))


def test_rejects_replacement_equal_to_itself() -> None:
    with pytest.raises(ValidationError, match="replacement"):
        make_model(replacement="model-a")


def test_rejects_alias_equal_to_id() -> None:
    with pytest.raises(ValidationError, match="alias"):
        make_model(aliases=("model-a",))


def test_rejects_unknown_field() -> None:
    # Catches typos such as `shutdwn:` in a data file.
    with pytest.raises(ValidationError, match="shutdwn"):
        make_model(shutdwn=date(2026, 3, 1))


def test_rejects_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        make_file(make_model(), provider="acme")


# ---------------------------------------------------------------- registry


def test_lookup_by_id_and_alias() -> None:
    model = make_model(aliases=("model-a-latest",))
    registry = Registry([make_file(model)])
    assert registry.get("model-a") == (Provider.OPENAI, model)
    assert registry.get("model-a-latest") == (Provider.OPENAI, model)
    assert registry.get("model-z") is None
    assert len(registry) == 1
    assert list(registry) == [(Provider.OPENAI, model)]


def test_duplicate_ids_across_files_are_rejected() -> None:
    first = make_file(make_model())
    second = make_file(make_model(id="other", aliases=("model-a",)), provider="google")
    with pytest.raises(DuplicateModelError, match="model-a"):
        Registry([first, second])


def test_load_provider_file_reads_yaml(tmp_path: Path) -> None:
    path = tmp_path / "openai.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "provider": "openai",
                "source_url": "https://example.com/deprecations",
                "retrieved": "2026-10-08",
                "models": [{"id": "model-a", "shutdown": "2026-03-01"}],
            }
        )
    )
    loaded = load_provider_file(path)
    assert loaded.models[0].shutdown == date(2026, 3, 1)


# ------------------------------------------------------------ shipped data


def test_shipped_registry_loads() -> None:
    registry = load_registry()
    assert len(registry) >= 20
    assert len(registry.sources) == len(list(DATA_DIR.glob("*.yaml")))


@pytest.mark.parametrize("path", sorted(DATA_DIR.glob("*.yaml")), ids=lambda p: p.name)
def test_file_name_matches_provider(path: Path) -> None:
    assert load_provider_file(path).provider.value == path.stem


def test_known_retirement_is_correct() -> None:
    # Spot check copied by hand from the Anthropic deprecations page on 2026-10-08.
    found = load_registry().get("claude-3-haiku-20240307")
    assert found is not None
    provider, model = found
    assert provider is Provider.ANTHROPIC
    assert model.announced == date(2026, 2, 19)
    assert model.shutdown == date(2026, 4, 20)
