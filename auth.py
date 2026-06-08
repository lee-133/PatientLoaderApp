# JWT token creating for the HealthEx API.
# JWT token valid for 24 hours.
# Reference: https://docs.healthex.io/authentication


from __future__ import annotations
from typing import Optional
import requests

# Static variables
DEFAULT_BASE_URL = "https://api.healthex.io"
TOKEN_PATH = "/v1/auth/token"


# Auth error class for handling different error types
class AuthError(RuntimeError):
    pass


# Generate JWT from API key/secret
class HealthExAuth:

    def __init__(
        self,
        apiKey: str,
        apiSecret: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not apiKey or not apiSecret:
            raise ValueError("apiKey and apiSecret are required")

        self._apiKey = apiKey
        self._apiSecret = apiSecret
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._token: Optional[str] = None

    # Structure API call to generate JWT token
    # Token is cached for duration of session
    # force_refresh can be used to generate new token, if needed
    def token(self, *, force_refresh: bool = False) -> str:

        if self._token and not force_refresh:
            return self._token

        url = f"{self._base_url}{TOKEN_PATH}"
        payload = {"apiKey": self._apiKey, "apiSecret": self._apiSecret}

        try:
            response = self._session.post(
                url,
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            response = getattr(exc, "response", None)
            if response is not None and response.status_code == 401:
                raise AuthError("API key/secret rejected (401).") from exc
            raise AuthError(f"Auth request to {url} failed: {exc}") from exc
        except ValueError as exc:
            raise AuthError(f"Auth response was not JSON: {response.text}") from exc

        token = body.get("token")
        if not token:
            raise AuthError(f"Auth token missing: {body}")

        self._token = token
        return token

    # Create Bearer Authorization header
    def bearer_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}


# Generate a PATIENT auth token from the patient's own email + password.
# Test patients have credentials (returned once at creation); consent must
# be given AS the patient. Reference: consent flow.
def patient_token(
    email: str,
    password: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    session: Optional[requests.Session] = None,
) -> str:
    if not email or not password:
        raise ValueError("email and password are required for a patient token")

    sess = session or requests.Session()
    url = f"{base_url.rstrip('/')}{TOKEN_PATH}"
    payload = {"email": email, "password": password}

    try:
        response = sess.post(
            url,
            json=payload,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
    except requests.RequestException as exc:
        resp = getattr(exc, "response", None)
        if resp is not None and resp.status_code == 401:
            raise AuthError("Patient email/password rejected (401).") from exc
        raise AuthError(f"Patient auth request to {url} failed: {exc}") from exc
    except ValueError as exc:
        raise AuthError(f"Patient auth response was not JSON: {response.text}") from exc

    token = body.get("token")
    if not token:
        raise AuthError(f"Patient auth token missing: {body}")
    return token
