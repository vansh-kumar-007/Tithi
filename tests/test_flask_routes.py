"""
Integration tests for Flask routes, exports, and CSS/HTML hero clickability.
"""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app


class TestFlaskRoutesAndExports:
    def setup_method(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.sample_payload = {
            "birth_date": "2004-05-28",
            "lat": 29.3724,
            "lon": 78.1358,
            "timezone": "Asia/Kolkata",
            "location_name": "Bijnor, Uttar Pradesh, India",
            "ayanamsha": "lahiri",
            "lunar_system": "amanta",
            "observance_method": "sunrise",
            "adhika_rule": "nija",
            "start_year": 2024,
            "end_year": 2026,
            "birth_time_mode": "exact",
            "birth_time": "04:00",
        }

    def test_homepage_and_hero_button_not_blocked_by_css(self):
        r = self.client.get("/")
        assert r.status_code == 200
        assert b"btn-hero-calculate" in r.data

        css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "css", "style.css")
        with open(css_path, "r", encoding="utf-8") as fh:
            css = fh.read()
        assert "pointer-events: none;" in css

    def test_results_route_redirects_cleanly(self):
        r = self.client.get("/results")
        assert r.status_code == 302

    def test_timezone_detection_route(self):
        r = self.client.get("/timezone?lat=51.5074&lon=-0.1278")
        assert r.status_code == 200
        assert json.loads(r.data)["timezone"] == "Europe/London"

    def test_calculate_exact_mode(self):
        r = self.client.post(
            "/calculate",
            data=json.dumps(self.sample_payload),
            content_type="application/json",
        )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["panchang"]["lunar_month"]["name_en"] == "Jyeshtha"
        assert data["panchang"]["tithis"][0]["name_en"] == "Navami"
        assert data["panchang"]["tithis"][0]["start_local"] is not None
        assert len(data["birthday_entries"]) == 3
        for e in data["birthday_entries"]:
            assert e["gregorian_date"].startswith(f"{e['year']}-05-") or e["gregorian_date"].startswith(f"{e['year']}-06-")

    def test_calculate_validation_errors(self):
        bad = {**self.sample_payload, "birth_time": ""}
        r = self.client.post("/calculate", data=json.dumps(bad), content_type="application/json")
        assert r.status_code == 400

        bad_range = {**self.sample_payload, "start_year": 1800, "end_year": 2100}
        r2 = self.client.post("/calculate", data=json.dumps(bad_range), content_type="application/json")
        assert r2.status_code == 400

    def test_all_exports(self):
        for endpoint, expected_prefix in [
            ("/export/csv", b"Candidate"),
            ("/export/excel", b"PK"),
            ("/export/pdf", b"%PDF-"),
            ("/export/ics", b"BEGIN:VCALENDAR"),
        ]:
            r = self.client.post(
                endpoint,
                data=json.dumps(self.sample_payload),
                content_type="application/json",
            )
            assert r.status_code == 200, f"{endpoint} returned {r.status_code}"
            assert expected_prefix in r.data[:64] or expected_prefix in r.data[:16]
