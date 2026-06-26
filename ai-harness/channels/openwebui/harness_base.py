"""
Base class for AI Harness OpenWebUI tool integrations.

Shared boilerplate: Valves configuration, HTTP helpers (_headers, _post, _get_with_params, _absolute_url).
Each tool file imports this base and declares only its domain-specific tool methods.
"""

import os
import requests
from pydantic import BaseModel, Field


class HarnessBase:
    class Valves(BaseModel):
        harness_url: str = Field(
            default=os.getenv("HARNESS_URL", "http://ai-harness:8090"),
            description="Internal API URL for the AI Harness (Docker DNS name, e.g. http://ai-harness:8090)",
        )
        harness_api_key: str = Field(
            default=os.getenv("HARNESS_API_KEY", ""),
            description="AI Harness API key",
        )
        harness_display_url: str = Field(
            default=os.getenv("HARNESS_DISPLAY_URL", "http://192.168.4.54:8090"),
            description="Browser-accessible URL for media files (LAN IP, e.g. http://192.168.4.54:8090)",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = True

    def _headers(self, content_type: bool = True) -> dict:
        headers = {}

        if content_type:
            headers["Content-Type"] = "application/json"

        if self.valves.harness_api_key:
            headers["X-API-Key"] = self.valves.harness_api_key
            headers["Authorization"] = f"Bearer {self.valves.harness_api_key}"

        return headers

    def _absolute_url(self, url: str) -> str:
        if not url:
            return ""

        if url.startswith(("http://", "https://")):
            # Internal harness URL — rewrite to browser-accessible display URL.
            harness = self.valves.harness_url.rstrip("/")
            display = self.valves.harness_display_url.rstrip("/")
            if url.startswith(harness):
                return f"{display}/{url[len(harness):].lstrip('/')}"
            # Rewrite any http:// internal URL that isn't already the display URL
            # This covers thor.local, localhost, and other LAN hostnames
            if url.startswith("http://") and not url.startswith(display):
                # Extract path portion after hostname[:port]
                rest = url[len("http://"):]
                slash_idx = rest.find("/")
                if slash_idx >= 0:
                    path = rest[slash_idx:]
                    return f"{display}{path}"
            return url  # external URL, return as-is

        # Relative path — prepend display URL
        return f"{display}/{url.lstrip('/')}"

    def _post(self, path: str, payload: dict, timeout: int = 180) -> dict:
        r = requests.post(
            f"{self.valves.harness_url}{path}",
            headers=self._headers(),
            json=payload,
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()

    def _get_with_params(self, path: str, params: dict) -> dict:
        """Helper: GET request with query params."""
        r = requests.get(
            f"{self.valves.harness_url}{path}",
            headers=self._headers(content_type=False),
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()


# OpenWebUI expects the class to be called ``Tools``.
# Each tool file re-exports this class with that name.
class Tools(HarnessBase):
    """Default stub. Each per-group tool file subclasses or aliases this."""
    pass
