"""A small client for Zoho CRM's Blueprint API.

Docs: https://www.zoho.com/crm/developer/docs/api/v8/blueprint-details.html
and https://www.zoho.com/crm/developer/docs/api/v8/update-blueprint.html
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any

import requests

from zoho_blueprint.errors import (
    PartialSave,
    TransitionNotAvailable,
    ZohoAPIError,
    error_for,
)
from zoho_blueprint.models import BlueprintState, Transition

TokenProvider = Callable[[], str]

DEFAULT_API_DOMAIN = "https://www.zohoapis.com"
DEFAULT_ACCOUNTS_URL = "https://accounts.zoho.com"


class RefreshTokenAuth:
    """Turns a long-lived refresh token into access tokens, as needed.

    Zoho access tokens last an hour. This caches one and fetches a new one a
    minute before it expires, or when :meth:`invalidate` is called. Use the
    accounts URL of your data center (``accounts.zoho.eu``, ``.in``, ...).
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        accounts_url: str = DEFAULT_ACCOUNTS_URL,
        session: requests.Session | None = None,
    ) -> None:
        self._params = {
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        }
        self._url = accounts_url.rstrip("/") + "/oauth/v2/token"
        self._session = session or requests.Session()
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            if self._token is None or time.monotonic() >= self._expires_at:
                response = self._session.post(self._url, params=self._params, timeout=30)
                body = _json(response)
                token = body.get("access_token")
                if response.status_code >= 400 or not token:
                    raise ZohoAPIError(
                        str(body.get("error") or "TOKEN_REFRESH_FAILED"),
                        "could not refresh the Zoho access token",
                        body,
                        response.status_code,
                    )
                self._token = str(token)
                self._expires_at = time.monotonic() + float(body.get("expires_in", 3600)) - 60
            return self._token

    def invalidate(self) -> None:
        """Forget the cached token, so the next call fetches a new one."""
        with self._lock:
            self._token = None


class BlueprintClient:
    """Reads and runs Blueprint transitions on Zoho CRM records.

    Args:
        token: An access token, or a callable that returns one (such as
            :class:`RefreshTokenAuth`).
        api_domain: Your data center's API domain, such as
            ``https://www.zohoapis.eu``.
        version: The CRM API version.
        session: A ``requests.Session`` to reuse.
        timeout: Seconds to wait for each request.
    """

    def __init__(
        self,
        token: str | TokenProvider,
        api_domain: str = DEFAULT_API_DOMAIN,
        version: str = "v8",
        session: requests.Session | None = None,
        timeout: float = 30,
    ) -> None:
        self._token: TokenProvider = (lambda: token) if isinstance(token, str) else token
        self._base = f"{api_domain.rstrip('/')}/crm/{version}"
        self._session = session or requests.Session()
        self._timeout = timeout

    # -- Blueprint ---------------------------------------------------------

    def get_state(self, module: str, record_id: str) -> BlueprintState:
        """The record's current Blueprint state and its available transitions.

        Raises:
            RecordNotInProcess: The record is in no Blueprint.
        """
        body = self.request("GET", f"/{module}/{record_id}/actions/blueprint")
        return BlueprintState.from_api(body)

    def execute(
        self,
        module: str,
        record_id: str,
        transition: str | Transition,
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one transition, by name or as returned by :meth:`get_state`.

        A name is looked up among the record's available transitions first.

        Raises:
            TransitionNotAvailable: No available transition has that name.
            MandatoryFieldsMissing: Zoho wants fields that ``data`` lacks.
            PartialSave: Zoho saved the data but did not run the transition.
        """
        if isinstance(transition, str):
            state = self.get_state(module, record_id)
            found = state.transition(transition)
            if found is None:
                raise TransitionNotAvailable(transition, state.state, state.transition_names)
            transition = found
        body = self.request(
            "PUT",
            f"/{module}/{record_id}/actions/blueprint",
            json={"blueprint": [{"transition_id": transition.id, "data": dict(data or {})}]},
        )
        if "partial" in str(body.get("message", "")).lower():
            raise PartialSave(transition.name, body)
        return body

    def walk(
        self,
        module: str,
        record_id: str,
        path: Sequence[str],
        data: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> BlueprintState:
        """Run transitions in order, the way a person would in the UI.

        Each transition's checks, date stamps and after-actions run, which a
        record created or updated straight into a later state skips.

        Args:
            path: Transition names, in order.
            data: Field values for each transition, keyed by transition name.

        Returns:
            The record's state after the last transition.

        Raises:
            TransitionNotAvailable: A step is not available when reached. The
                transitions before it have already run.
        """
        data = data or {}
        state = self.get_state(module, record_id)
        for name in path:
            found = state.transition(name)
            if found is None:
                raise TransitionNotAvailable(name, state.state, state.transition_names)
            self.execute(module, record_id, found, data.get(name))
            state = self.get_state(module, record_id)
        return state

    # -- Records -----------------------------------------------------------

    def iter_records(
        self,
        module: str,
        fields: Sequence[str],
        sort_by: str = "Created_Time",
        sort_order: str = "desc",
        per_page: int = 200,
    ) -> Iterator[dict[str, Any]]:
        """Every record of a module, newest first by default, page by page."""
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "fields": ",".join(fields),
                "per_page": per_page,
                "sort_by": sort_by,
                "sort_order": sort_order,
            }
            if page_token:
                params["page_token"] = page_token
            body = self.request("GET", f"/{module}", params=params)
            yield from body.get("data") or []
            info = body.get("info") or {}
            page_token = info.get("next_page_token")
            if not info.get("more_records") or not page_token:
                return

    def stage_history(self, deal_id: str) -> list[dict[str, Any]]:
        """A Deal's Stage History rows, as Zoho returns them."""
        body = self.request(
            "GET",
            f"/Deals/{deal_id}/Stage_History",
            params={"fields": "Stage,Last_Modified_Time"},
        )
        return list(body.get("data") or [])

    # -- Transport ---------------------------------------------------------

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send a request and return its JSON, or raise a ZohoAPIError.

        A 204 (no content) returns an empty dict. An expired token is
        refreshed and the request sent once more.
        """
        for attempt in (1, 2):
            response = self._session.request(
                method,
                self._base + path,
                headers={"Authorization": f"Zoho-oauthtoken {self._token()}"},
                timeout=self._timeout,
                **kwargs,
            )
            if response.status_code == 204:
                return {}
            body = _json(response)
            if response.status_code == 401 and attempt == 1 and hasattr(self._token, "invalidate"):
                self._token.invalidate()
                continue
            error = _error_in(body)
            if response.status_code >= 400 or error is not None:
                code, message, details = error or ("HTTP_ERROR", response.reason or "", {})
                raise error_for(code, message, details, response.status_code)
            return body
        raise AssertionError("unreachable")  # pragma: no cover


def _json(response: requests.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {"data": body}


def _error_in(body: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
    """Zoho's error, whether at the top level or in the first item of ``data``."""
    candidates: list[Any] = [body]
    for key in ("data", "blueprint"):
        items = body.get(key)
        if isinstance(items, list) and items:
            candidates.append(items[0])
    for item in candidates:
        if isinstance(item, dict) and str(item.get("status", "")).lower() == "error":
            return (
                str(item.get("code") or "ERROR"),
                str(item.get("message") or ""),
                item.get("details") or {},
            )
    return None
