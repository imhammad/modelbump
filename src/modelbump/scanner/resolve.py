"""Map a model ID as written in code to the ID the registry uses (ADR 0024).

Cloud platforms wrap the provider's model IDs in their own forms:

- Amazon Bedrock adds a version: ``anthropic.claude-3-haiku-20240307-v1:0``.
  The finder keeps ``claude-3-haiku-20240307-v1``; dropping ``-v1`` gives the
  registry ID.
- Google Vertex AI writes the date after an ``@``:
  ``claude-3-5-sonnet@20240620`` is ``claude-3-5-sonnet-20240620``.

An ID is only mapped when the mapped form is in the registry, so a form we
do not know is reported as written.
"""

import re
from collections.abc import Iterator

from modelbump.registry import Registry

_BEDROCK_VERSION = re.compile(r"-v[0-9]+$")


def resolve(model_id: str, registry: Registry) -> str | None:
    """Return the registry ID that ``model_id`` refers to, or None."""
    for form in _forms(model_id):
        if registry.get(form) is not None:
            return form
    return None


def _forms(model_id: str) -> Iterator[str]:
    yield model_id
    if "@" in model_id:
        yield model_id.replace("@", "-")
    unversioned = _BEDROCK_VERSION.sub("", model_id)
    if unversioned != model_id:
        yield unversioned
