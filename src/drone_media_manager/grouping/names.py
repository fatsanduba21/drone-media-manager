"""Optional place-name candidates; editorial confirmation remains human owned."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True)
class NameCandidate:
    name: str
    place_id: str


class LocationProvider(Protocol):
    def suggest_names(
        self, lat: float, lon: float, radius: int
    ) -> list[NameCandidate]: ...


class GooglePlacesProvider:
    """Query only IDs and display names from Nearby Search (New)."""

    URL = "https://places.googleapis.com/v1/places:searchNearby"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.client = client

    def suggest_names(self, lat: float, lon: float, radius: int) -> list[NameCandidate]:
        payload = {
            "languageCode": "pt-BR",
            "maxResultCount": 5,
            "rankPreference": "DISTANCE",
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": radius,
                }
            },
        }
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.id,places.displayName",
        }
        if self.client is None:
            with httpx.Client(timeout=3.0) as client:
                response = client.post(self.URL, json=payload, headers=headers)
        else:
            response = self.client.post(self.URL, json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            return []
        places = body.get("places", [])
        if not isinstance(places, list):
            return []
        candidates: list[NameCandidate] = []
        seen: set[str] = set()
        for place in places:
            if not isinstance(place, dict):
                continue
            display = place.get("displayName")
            name = display.get("text") if isinstance(display, dict) else None
            place_id = place.get("id")
            clean_name = name.strip() if isinstance(name, str) else ""
            if (
                isinstance(name, str)
                and isinstance(place_id, str)
                and clean_name
                and place_id
                and clean_name.casefold() not in seen
            ):
                candidates.append(NameCandidate(clean_name, place_id))
                seen.add(clean_name.casefold())
        return candidates


class NameLookup:
    """Briefly reuse nearby responses to avoid repeat calls during a review."""

    def __init__(self, provider: LocationProvider | None) -> None:
        self.provider = provider
        self._cache: dict[
            tuple[float, float, int], tuple[float, list[NameCandidate]]
        ] = {}

    def suggest_names(self, lat: float, lon: float, radius: int) -> list[NameCandidate]:
        if self.provider is None:
            return []
        key = (round(lat, 3), round(lon, 3), radius)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        try:
            names = self.provider.suggest_names(lat, lon, radius)
        except (httpx.HTTPError, ValueError, TypeError):
            names = []
        if len(self._cache) >= 256:
            self._cache.clear()
        self._cache[key] = (now + 300, names)
        return names
