"""Typed views of Zoho's Blueprint responses.

Each model keeps the original JSON in ``raw``, so fields this library does
not name are still there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TransitionField:
    """A field shown on a transition.

    ``reported_mandatory`` is what Zoho's GET says. It is not reliable:
    a transition can refuse to run without fields the GET reports as not
    mandatory. Treat a ``MandatoryFieldsMissing`` error as the truth.
    """

    api_name: str | None
    label: str | None
    data_type: str | None
    reported_mandatory: bool
    read_only: bool
    raw: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> TransitionField:
        return cls(
            api_name=raw.get("api_name"),
            label=raw.get("display_label") or raw.get("field_label"),
            data_type=raw.get("data_type"),
            reported_mandatory=bool(raw.get("mandatory") or raw.get("system_mandatory")),
            read_only=bool(raw.get("read_only") or raw.get("field_read_only")),
            raw=raw,
        )


@dataclass(frozen=True)
class Transition:
    """A transition the record can take from its current state."""

    id: str
    name: str
    next_state: str | None
    criteria_matched: bool
    fields: list[TransitionField]
    raw: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Transition:
        return cls(
            id=str(raw.get("id")),
            name=str(raw.get("name")),
            next_state=raw.get("next_field_value"),
            criteria_matched=raw.get("criteria_matched", True) is not False,
            fields=[TransitionField.from_api(f) for f in raw.get("fields") or []],
            raw=raw,
        )


@dataclass(frozen=True)
class BlueprintState:
    """Where a record stands in its Blueprint, and where it can go."""

    process_name: str | None
    field_api_name: str | None
    state: str | None
    transitions: list[Transition]
    raw: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> BlueprintState:
        blueprint = body.get("blueprint") or {}
        info = blueprint.get("process_info") or {}
        return cls(
            process_name=info.get("name"),
            field_api_name=info.get("api_name") or info.get("field_name"),
            state=info.get("field_value"),
            transitions=[Transition.from_api(t) for t in blueprint.get("transitions") or []],
            raw=body,
        )

    def transition(self, name: str) -> Transition | None:
        """The available transition with this exact name, or None."""
        for transition in self.transitions:
            if transition.name == name:
                return transition
        return None

    @property
    def transition_names(self) -> list[str]:
        return [t.name for t in self.transitions]
