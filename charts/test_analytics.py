from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .models import SiteEvent


class WebsiteAnalyticsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.admin = User.objects.create_superuser("admin", "admin@example.com", "password")

    def test_public_tracking_and_cms_summary_include_deep_metrics(self):
        self.client.post("/api/v1/track/", {
            "event_type": "pageview",
            "page": "charts",
            "path": "/charts?utm_source=newsletter&utm_campaign=launch",
            "title": "Charts | Ngoma Charts",
            "session_id": "session-one",
            "referrer": "https://example.com/music",
            "referrer_domain": "example.com",
            "utm_source": "newsletter",
            "utm_campaign": "launch",
            "device_type": "mobile",
            "browser": "Chrome",
            "os": "Android",
            "language": "en-KE",
            "timezone": "Africa/Nairobi",
            "viewport_width": 390,
            "viewport_height": 844,
            "screen_width": 390,
            "screen_height": 844,
            "effective_connection_type": "4g",
            "page_load_ms": 1250,
        }, format="json")
        self.client.post("/api/v1/track/", {
            "event_type": "click",
            "page": "charts",
            "label": "listen_spotify",
            "session_id": "session-one",
            "device_type": "mobile",
        }, format="json")
        self.client.post("/api/v1/track/", {
            "event_type": "engagement",
            "page": "charts",
            "label": "page_engagement",
            "session_id": "session-one",
            "scroll_depth": 80,
            "engagement_time_ms": 15000,
        }, format="json")

        event = SiteEvent.objects.get(event_type="pageview")
        self.assertEqual(event.browser, "Chrome")
        self.assertEqual(event.viewport_width, 390)
        self.assertEqual(event.utm_source, "newsletter")

        self.client.force_authenticate(self.admin)
        response = self.client.get("/api/v1/cms/analytics/summary/?range=30d")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["total_pageviews"], 1)
        self.assertEqual(data["totals"]["events"], 3)
        self.assertEqual(data["totals"]["clicks"], 1)
        self.assertEqual(data["totals"]["unique_sessions"], 1)
        self.assertEqual(data["totals"]["unique_sessions_today"], 1)
        self.assertEqual(data["pageviews_by_day"][-1]["unique_sessions"], 1)
        self.assertEqual(max(row["unique_sessions"] for row in data["pageviews_by_hour"]), 1)
        self.assertEqual(max(row["unique_sessions"] for row in data["pageviews_by_weekday"]), 1)
        self.assertEqual(max(row["count"] for row in data["unique_sessions_by_day"]), 1)
        self.assertEqual(max(row["count"] for row in data["unique_sessions_by_hour"]), 1)
        self.assertEqual(max(row["count"] for row in data["unique_sessions_by_weekday"]), 1)
        self.assertEqual(data["performance"]["avg_load_ms"], 1250)
        self.assertEqual(data["engagement"]["engaged_sessions"], 1)
        self.assertEqual(data["engagement"]["bounce_rate"], 0)
        self.assertEqual(data["top_pages"][0]["page"], "charts")
        self.assertEqual(data["top_pages"][0]["avg_scroll_depth"], 80)
        self.assertEqual(data["top_clicks"][0]["label"], "listen_spotify")
        self.assertEqual(data["acquisition"]["referrer_domains"][0]["label"], "example.com")
        self.assertEqual(data["acquisition"]["utm_sources"][0]["label"], "newsletter")
        self.assertEqual(data["devices"]["device_types"][0]["label"], "mobile")
        self.assertEqual(data["devices"]["browsers"][0]["label"], "Chrome")
        self.assertEqual(data["devices"]["viewports"][0]["label"], "390x844")
        self.assertTrue(data["insights"])
