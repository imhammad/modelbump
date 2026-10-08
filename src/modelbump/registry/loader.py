"""Load the retirement data files and look models up by ID."""

from collections.abc import Iterable, Iterator
from importlib.resources import files
from importlib.resources.abc import Traversable

import yaml

from modelbump.registry.models import Provider, ProviderFile, RetiredModel


class DuplicateModelError(ValueError):
    """Raised when the same model ID appears in more than one entry."""


def load_provider_file(path: Traversable) -> ProviderFile:
    """Read and validate one YAML data file."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ProviderFile.model_validate(data)


class Registry:
    """All known retirements, indexed by every model ID and alias."""

    def __init__(self, sources: Iterable[ProviderFile]) -> None:
        self._sources = tuple(sources)
        self._by_id: dict[str, tuple[Provider, RetiredModel]] = {}
        for source in self._sources:
            for model in source.models:
                for model_id in model.all_ids():
                    if model_id in self._by_id:
                        raise DuplicateModelError(f"{model_id} appears more than once")
                    self._by_id[model_id] = (source.provider, model)

    @property
    def sources(self) -> tuple[ProviderFile, ...]:
        """The data files this registry was built from."""
        return self._sources

    def get(self, model_id: str) -> tuple[Provider, RetiredModel] | None:
        """Return the provider and entry for ``model_id``, or None if unknown."""
        return self._by_id.get(model_id)

    def __iter__(self) -> Iterator[tuple[Provider, RetiredModel]]:
        for source in self._sources:
            for model in source.models:
                yield source.provider, model

    def __len__(self) -> int:
        return sum(len(source.models) for source in self._sources)


def load_registry() -> Registry:
    """Load every data file shipped inside the package."""
    data_dir = files("modelbump.registry") / "data"
    paths = sorted(
        (p for p in data_dir.iterdir() if p.name.endswith(".yaml")), key=lambda p: p.name
    )
    return Registry(load_provider_file(p) for p in paths)
