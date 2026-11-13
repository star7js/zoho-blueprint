"""Errors raised by zoho_blueprint.

Every error from Zoho keeps the response's ``code``, ``message``,
``details`` and HTTP ``status`` so nothing is lost in translation.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class ZohoBlueprintError(Exception):
    """Base class for every error this library raises."""


class ZohoAPIError(ZohoBlueprintError):
    """Zoho answered with an error.

    Attributes:
        code: Zoho's error code, such as ``"INVALID_DATA"``.
        message: Zoho's message text.
        details: Zoho's ``details`` object, or an empty dict.
        status: The HTTP status code.
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        status: int | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        self.status = status
        super().__init__(f"{code}: {message}" if message else code)


class MandatoryFieldsMissing(ZohoAPIError):
    """A transition was refused because required fields were not sent.

    Zoho answers ``MANDATORY_NOT_FOUND`` / "mandatory param missing". The
    fields named in the response, if any, are in ``fields``. Note that the
    Blueprint GET may report these same fields as not mandatory.
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(code, message, details, status)
        self.fields: list[str] = _field_names(self.details)
        if self.fields:
            self.args = (f"{code}: {message} ({', '.join(self.fields)})",)


class RecordNotInProcess(ZohoAPIError):
    """The record is not in any Blueprint process (``RECORD_NOT_IN_PROCESS``)."""


class RecordLocked(ZohoAPIError):
    """The record is locked (``RECORD_LOCKED``)."""


class RecordInBlueprint(ZohoAPIError):
    """A plain record update touched a field the Blueprint owns.

    Zoho answers ``RECORD_IN_BLUEPRINT`` when, for example, a Deal's Stage
    is updated directly while a Blueprint governs it. Use the Blueprint
    transitions instead.
    """


class PartialSave(ZohoBlueprintError):
    """Zoho saved the transition's data but did not complete the transition.

    Zoho answers this as a success, with the message "transition saved
    partially", so a client that only checks for success would think the
    record moved when it did not.
    """

    def __init__(self, transition: str, response: dict[str, Any]) -> None:
        self.transition = transition
        self.response = response
        super().__init__(
            f"transition {transition!r} was saved partially, not completed: "
            "send every field the transition requires"
        )


class TransitionNotAvailable(ZohoBlueprintError):
    """The named transition is not available from the record's current state."""

    def __init__(self, transition: str, state: str | None, available: Sequence[str]) -> None:
        self.transition = transition
        self.state = state
        self.available = list(available)
        offered = ", ".join(repr(name) for name in self.available) or "none"
        super().__init__(
            f"transition {transition!r} is not available from state {state!r}; available: {offered}"
        )


_ERRORS: dict[str, type[ZohoAPIError]] = {
    "MANDATORY_NOT_FOUND": MandatoryFieldsMissing,
    "RECORD_NOT_IN_PROCESS": RecordNotInProcess,
    "RECORD_LOCKED": RecordLocked,
    "RECORD_IN_BLUEPRINT": RecordInBlueprint,
}


def error_for(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    status: int | None = None,
) -> ZohoAPIError:
    """Build the most specific error class for a Zoho error code."""
    if code == "INVALID_DATA" and "mandatory" in (message or "").lower():
        return MandatoryFieldsMissing(code, message, details, status)
    return _ERRORS.get(code, ZohoAPIError)(code, message, details, status)


def _field_names(details: dict[str, Any]) -> list[str]:
    """Pull field API names out of an error's details, whatever its shape."""
    names: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value and value not in names:
            names.append(value)
        elif isinstance(value, dict):
            add(value.get("api_name"))
        elif isinstance(value, list):
            for item in value:
                add(item)

    keys = (
        "validation_error",  # what a refused Blueprint PUT sends: [{"api_name": ...}, ...]
        "api_name",
        "api_names",
        "fields",
        "field",
        "missing_fields",
        "expected_data",
    )
    for key in keys:
        if key in details:
            add(details[key])
    return names
