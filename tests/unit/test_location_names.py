"""Place suggestions remain optional and bounded by the selected location."""

import httpx

from drone_media_manager.grouping.names import GooglePlacesProvider, NameLookup


def test_google_places_requests_only_names_and_ids() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "places": [
                    {"id": "place-1", "displayName": {"text": "Praia do Bode"}},
                    {"id": "place-2", "displayName": {"text": "Praia do Bode"}},
                    {"id": "place-3", "displayName": {"text": "Morro do Pico"}},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        names = GooglePlacesProvider("private-key", client=client).suggest_names(
            -3.85, -32.42, 500
        )

    assert [(item.name, item.place_id) for item in names] == [
        ("Praia do Bode", "place-1"),
        ("Morro do Pico", "place-3"),
    ]
    assert len(requests) == 1
    assert requests[0].url == "https://places.googleapis.com/v1/places:searchNearby"
    assert requests[0].headers["X-Goog-FieldMask"] == "places.id,places.displayName"
    assert requests[0].headers["X-Goog-Api-Key"] == "private-key"
    assert requests[0].read().decode().find('"radius":500') >= 0


def test_nearby_lookup_reuses_short_lived_result_and_api_failure_allows_manual() -> (
    None
):
    calls = 0

    class Provider:
        def suggest_names(self, lat: float, lon: float, radius: int) -> list[object]:
            nonlocal calls
            calls += 1
            raise httpx.ConnectError("offline")

    lookup = NameLookup(Provider())
    assert lookup.suggest_names(-3.85, -32.42, 500) == []
    assert lookup.suggest_names(-3.8501, -32.4201, 500) == []
    assert calls == 1
