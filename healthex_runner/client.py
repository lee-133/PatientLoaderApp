# Thin HTTP layer over the HealthEx API
#
# The single place that turns: "call endpoint X" into an
# authenticated HTTP request: takes an auth instance (from auth.py)
# attaches the bearer header to every call
# builds full URLs from base URL + path
# and turns failed responses into a clear HealthExAPIError
#
# loader.py and fhir.py hold patient and project logic
# and call this for the actual HTTP
# Both the REST API and the FHIR server share one
# base URL and JWT, so a single client covers both


from __future__ import annotations
from typing import Any, Optional
import requests
from .auth import HealthExAuth

# Define API endpoint base URL
DEFAULT_BASE_URL = "https://api.healthex.io"


# Error handler when API returns
# error response or unexpected response body
class HealthExAPIError(RuntimeError):

    def __init__(
        self, message: str, *, status: Optional[int] = None, body: Optional[str] = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


# Client to execute authenticated API requests
class HealthExClient:

    def __init__(self, auth: HealthExAuth, *, base_url: str = DEFAULT_BASE_URL) -> None:
        self._auth = auth
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()

    # POST to path w/ JSON body
    # Return parsed JSON response
    def post(self, path: str, *, json: Any = None) -> Any:
        return self._request("POST", path, json=json)

    # GET w/ optional query params
    # Return parsed JSON response
    def get(self, path: str, *, params: Optional[dict[str, Any]] = None) -> Any:
        return self._request("GET", path, params=params)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = f"{self._base_url}/{path.lstrip('/')}"
        headers = {"Accept": "application/json"}
        headers.update(self._auth.bearer_header())

        try:
            response = self._session.request(
                method,
                url,
                json=json,
                params=params,
                headers=headers,
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            body = getattr(getattr(exc, "response", None), "text", None)
            raise HealthExAPIError(
                f"{method} {url} failed: {exc}", status=status, body=body
            ) from exc

        # Some endpoints may return empty body
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise HealthExAPIError(
                f"{method} {url} returned non-JSON body", body=response.text
            ) from exc
