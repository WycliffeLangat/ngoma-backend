from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    Artist,
    Certification,
    CertificationRule,
    Country,
    MethodologySetting,
    MonthlyChart,
    MonthlyChartEntry,
    NewsArticle,
    PageContent,
    Platform,
    Release,
    SiteSetting,
)


class PublicAppDataSyncTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser("admin", "admin@example.com", "password")
        self.platform = Platform.objects.create(
            name="Test Platform",
            slug="test-platform",
            short_name="Test",
            supports_singles=True,
            supports_albums=True,
        )
        self.country = Country.objects.create(name="Test Country", code="TC", active=True)
        self.artist = Artist.objects.create(
            name="Original Artist",
            slug="original-artist",
            country="Test Country",
            country_code="TC",
        )
        self.release = Release.objects.create(
            title="Original Song",
            artist=self.artist,
            chart_type="singles",
            canonical_title="original song",
        )
        self.chart = MonthlyChart.objects.create(
            year=2026,
            month=6,
            chart_type="singles",
            label="ignored",
            status="published",
            is_published=True,
        )
        self.combined_entry = MonthlyChartEntry.objects.create(
            chart=self.chart,
            release=self.release,
            rank=1,
            total_points=50,
            platform_count=1,
            platform_max=1,
        )
        self.platform_entry = MonthlyChartEntry.objects.create(
            chart=self.chart,
            platform=self.platform,
            release=self.release,
            rank=1,
            total_points=100,
        )
        self.setting = SiteSetting.objects.create(key="test_site_name", value={"name": "Old Name"})
        self.page_content = PageContent.objects.create(
            page="about", section="intro", title="Old title", content="Old content"
        )
        self.news = NewsArticle.objects.create(
            title="Old headline",
            slug="old-headline",
            category="chart_news",
            status="published",
            is_published=True,
        )
        self.certification = Certification.objects.create(
            release=self.release,
            level="gold",
            total_points=5000,
            is_official=True,
        )
        self.rule, _ = CertificationRule.objects.update_or_create(
            level="gold", defaults={"threshold": 5000, "active": True}
        )
        self.methodology = MethodologySetting.objects.create(
            version="v1", name="Old method", config={"weight": 1}, is_active=True
        )

    def app_data(self):
        response = self.client.get("/api/v1/app-data/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("no-store", response["Cache-Control"])
        return response.json()

    def patch_cms(self, path, payload):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(path, payload, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.client.force_authenticate(user=None)
        return response.json()

    def test_all_public_facing_cms_saves_feed_the_app_payload(self):
        self.patch_cms(
            f"/api/v1/cms/artists/{self.artist.id}/",
            {
                "display_name": "Updated Artist",
                "genre": "Afropop",
                "country": "Kenya",
                "country_code": "KE",
            },
        )
        self.patch_cms(
            f"/api/v1/cms/releases/{self.release.id}/",
            {"title": "Updated Song", "genre": "Afrobeats", "label": "Updated Label"},
        )
        self.patch_cms(
            f"/api/v1/cms/platforms/{self.platform.id}/",
            {"name": "Apple Music Kenya", "color": "#123456"},
        )
        self.patch_cms(
            f"/api/v1/cms/countries/{self.country.id}/",
            {"name": "Republic of Kenya", "region": "East Africa"},
        )
        self.patch_cms(
            f"/api/v1/cms/chart-entries/{self.combined_entry.id}/",
            {"total_points": 77, "featured_artists": "Featured Artist"},
        )
        self.patch_cms(
            f"/api/v1/cms/settings/{self.setting.id}/",
            {"value": {"name": "Updated Site"}},
        )
        self.patch_cms(
            f"/api/v1/cms/page-content/{self.page_content.id}/",
            {"title": "Updated title", "content": "Updated content"},
        )
        self.patch_cms(
            f"/api/v1/cms/news/{self.news.id}/",
            {"title": "Updated headline"},
        )
        self.patch_cms(
            f"/api/v1/cms/certifications/{self.certification.id}/",
            {"total_points": 7777, "notes": "Updated note"},
        )
        self.patch_cms(
            f"/api/v1/cms/certification-rules/{self.rule.id}/",
            {"threshold": 7000},
        )
        self.patch_cms(
            f"/api/v1/cms/methodology/{self.methodology.id}/",
            {"name": "Updated method", "config": {"weight": 2}},
        )

        data = self.app_data()
        row = data["full"]["singles"]["combined"]["June 2026"][0]
        self.assertEqual(row["t"], "Updated Song")
        self.assertEqual(row["a"], "Updated Artist")
        self.assertEqual(row["p"], 77)
        self.assertEqual(row["fa"], "Featured Artist")
        self.assertEqual(row["co"], "Kenya")
        self.assertEqual(row["cc"], "KE")
        self.assertEqual(row["genre"], "Afrobeats")
        self.assertEqual(row["label"], "Updated Label")
        artist = next(item for item in data["artists"] if item["id"] == self.artist.id)
        release = next(item for item in data["releases"] if item["id"] == self.release.id)
        self.assertEqual(artist["country"], "Kenya")
        self.assertEqual(artist["country_code"], "KE")
        self.assertEqual(release["country"], "Kenya")
        self.assertEqual(release["country_code"], "KE")
        platform = next(item for item in data["platforms"] if item["id"] == self.platform.id)
        country = next(item for item in data["countries"] if item["id"] == self.country.id)
        article = next(item for item in data["news"] if item["id"] == self.news.id)
        certification = next(item for item in data["certifications"] if item["id"] == self.certification.id)
        rule = next(item for item in data["certification_rules"] if item["level"] == "gold")
        methodology = next(item for item in data["methodology"] if item["id"] == self.methodology.id)
        self.assertEqual(platform["name"], "Apple Music Kenya")
        self.assertEqual(platform["color"], "#123456")
        self.assertEqual(country["name"], "Republic of Kenya")
        self.assertEqual(data["settings"]["test_site_name"]["name"], "Updated Site")
        self.assertEqual(
            next(item for item in data["page_content"]["about"] if item["id"] == self.page_content.id)["title"],
            "Updated title",
        )
        self.assertEqual(article["title"], "Updated headline")
        self.assertEqual(certification["total_points"], 7777)
        self.assertEqual(rule["threshold"], 7000)
        self.assertEqual(methodology["name"], "Updated method")

    def test_hidden_or_unpublished_records_do_not_leak_to_public_app(self):
        self.certification.is_hidden = True
        self.certification.save(update_fields=["is_hidden"])
        self.news.status = "draft"
        self.news.save(update_fields=["status"])
        self.page_content.is_visible = False
        self.page_content.save(update_fields=["is_visible"])

        data = self.app_data()
        self.assertNotIn(self.certification.id, [item["id"] for item in data["certifications"]])
        self.assertNotIn(self.news.id, [item["id"] for item in data["news"]])
        self.assertNotIn(
            self.page_content.id,
            [item["id"] for item in data["page_content"].get("about", [])],
        )
