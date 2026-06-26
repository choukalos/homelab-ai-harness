"""
title: AI Harness Scheduler Tools
author: Chuck
version: 0.1.0
description: Schedule management via the AI Harness scheduler.
"""

import os
import requests
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Inlined HarnessBase — self-contained so this file works standalone in Open WebUI
# ---------------------------------------------------------------------------

class HarnessBase:
    class Valves(BaseModel):
        harness_url: str = Field(
            default=os.getenv("HARNESS_URL", "http://ai-harness:8090"),
            description="Internal API URL for the AI Harness",
        )
        harness_api_key: str = Field(
            default=os.getenv("HARNESS_API_KEY", ""),
            description="AI Harness API key",
        )
        harness_display_url: str = Field(
            default=os.getenv("HARNESS_DISPLAY_URL", "http://192.168.4.54:8090"),
            description="Browser-accessible URL for media files",
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
        display = self.valves.harness_display_url.rstrip("/")
        if url.startswith(("http://", "https://")):
            harness = self.valves.harness_url.rstrip("/")
            # Rewrite Docker internal hostname → display URL
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
            # https:// URLs or display URL as-is (already browser-accessible)
            return url
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
        r = requests.get(
            f"{self.valves.harness_url}{path}",
            headers=self._headers(content_type=False),
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

class Tools(HarnessBase):
    # Add scheduler methods here as needed.
    # The harness exposes: /schedules/* endpoints via the scheduler module.
    pass
