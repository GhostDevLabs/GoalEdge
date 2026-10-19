"""Contract tests for the disabled-by-default EaglePredict integration."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app import eaglepredict
from backend.app.routers import eaglepredict_predictions, router
from backend.app.schemas import EaglePredictPredictionsResponse
from api.index import app as vercel_app


class EaglePredictAdapterTests(unittest.TestCase):
    def test_unconfigured_provider_returns_documented_empty_response(self):
        with patch.object(eaglepredict.settings, "eaglepredict_enabled", False):
            payload = eaglepredict.provider_response()

        response = EaglePredictPredictionsResponse.model_validate(payload)
        self.assertEqual(response.provider, "eaglepredict")
        self.assertEqual(response.status, "provider_not_configured")
        self.assertEqual(response.predictions, [])
        self.assertIn("authorization", response.message.lower())

    def test_configured_but_unimplemented_contract_returns_safe_error(self):
        with (
            patch.object(eaglepredict.settings, "eaglepredict_enabled", True),
            patch.object(eaglepredict.settings, "eaglepredict_base_url", "https://authorized.example"),
            patch.object(eaglepredict.settings, "eaglepredict_api_key", "test-secret"),
        ):
            payload = eaglepredict.provider_response()

        response = EaglePredictPredictionsResponse.model_validate(payload)
        self.assertEqual(response.status, "provider_error")
        self.assertEqual(response.predictions, [])
        self.assertNotIn("test-secret", response.message)

    def test_new_route_does_not_replace_existing_prediction_routes(self):
        paths = {route.path for route in router.routes}
        self.assertIn("/eaglepredict/predictions", paths)
        self.assertTrue({"/tips", "/results", "/livescores", "/fixtures/{fixture_id}"}.issubset(paths))

    def test_endpoint_handler_matches_the_public_response_contract(self):
        with patch.object(eaglepredict.settings, "eaglepredict_enabled", False):
            payload = eaglepredict_predictions()

        self.assertEqual(
            EaglePredictPredictionsResponse.model_validate(payload).status,
            "provider_not_configured",
        )

    def test_vercel_entry_exposes_the_api_prefix_and_disabled_response(self):
        route = next(route for route in vercel_app.routes if route.path == "/api/eaglepredict/predictions")
        self.assertIs(route.endpoint, eaglepredict_predictions)

        with patch.object(eaglepredict.settings, "eaglepredict_enabled", False):
            payload = route.endpoint()

        self.assertEqual(payload["status"], "provider_not_configured")


if __name__ == "__main__":
    unittest.main()
