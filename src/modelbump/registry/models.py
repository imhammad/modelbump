"""Data model for the retirement registry.

Every field is checked when a data file is loaded, so a typo in a YAML file
fails the tests instead of silently producing wrong warnings later.
"""

from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class Provider(StrEnum):
    """LLM providers whose retirements we track."""

    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OPENAI = "openai"


class Status(StrEnum):
    """Where a model is in its life cycle on a given day."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class EarlierPlan(BaseModel):
    """A retirement plan the provider announced and later replaced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    announced: date | None = None
    shutdown: date
    shutdown_is_earliest: bool = False


class RetiredModel(BaseModel):
    """One model version that a provider has announced it will shut down."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, description="Model ID exactly as used in API calls.")
    aliases: tuple[str, ...] = Field(
        default=(), description="Other IDs that point to this same model."
    )
    announced: date | None = Field(
        default=None, description="Day the provider announced the deprecation."
    )
    shutdown: date = Field(description="Day API calls to this model stop working.")
    shutdown_is_earliest: bool = Field(
        default=False,
        description="True when the source only promises the shutdown no sooner than this day.",
    )
    replacement: str | None = Field(
        default=None,
        description="Replacement the source page recommended on the day we retrieved it.",
    )
    superseded: tuple[EarlierPlan, ...] = Field(
        default=(), description="Earlier retirement plans for this model, oldest first."
    )
    notes: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.announced is not None and self.shutdown < self.announced:
            raise ValueError(f"{self.id}: shutdown {self.shutdown} is before announced")
        ids = self.all_ids()
        if len(set(ids)) != len(ids):
            raise ValueError(f"{self.id}: an alias repeats the id or another alias")
        if self.replacement in ids:
            raise ValueError(f"{self.id}: replacement cannot be the model itself")
        for plan in self.superseded:
            if (
                plan.announced is not None
                and self.announced is not None
                and plan.announced >= self.announced
            ):
                raise ValueError(
                    f"{self.id}: a superseded plan must be announced before the current one"
                )
        return self

    def all_ids(self) -> tuple[str, ...]:
        """Return the main ID followed by every alias."""
        return (self.id, *self.aliases)

    def status_on(self, day: date) -> Status:
        """Return the model's status on ``day``, using the current plan.

        A model is retired from its shutdown day onwards, and deprecated from
        the announcement day until then.
        """
        if day >= self.shutdown:
            return Status.RETIRED
        if self.announced is not None and day >= self.announced:
            return Status.DEPRECATED
        return Status.ACTIVE


class ProviderFile(BaseModel):
    """The contents of one ``data/<provider>.yaml`` file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Provider
    source_url: HttpUrl = Field(description="Page the data was copied from.")
    retrieved: date = Field(description="Day we last checked the data against the source.")
    models: tuple[RetiredModel, ...] = Field(min_length=1)
