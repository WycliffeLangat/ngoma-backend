import base64
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
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
        self.second_artist = Artist.objects.create(
            name="Second Artist", slug="second-artist", country="Uganda", country_code="UG"
        )
        self.third_artist = Artist.objects.create(
            name="Third Artist", slug="third-artist", country="Tanzania", country_code="TZ"
        )
        self.featured_artist = Artist.objects.create(
            name="Featured Artist", slug="featured-artist", country="Ghana", country_code="GH"
        )
        self.featured_artist_two = Artist.objects.create(
            name="Guest Two", slug="guest-two", country="Nigeria", country_code="NG"
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

    def test_cms_multipart_image_uploads_are_persisted(self):
        image_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            self.client.force_authenticate(self.admin)

            release_response = self.client.patch(
                f"/api/v1/cms/releases/{self.release.id}/",
                {
                    "cover_image": SimpleUploadedFile(
                        "cover.png", image_bytes, content_type="image/png"
                    )
                },
                format="multipart",
            )
            self.assertEqual(release_response.status_code, 200, release_response.content)
            self.release.refresh_from_db()
            self.assertTrue(self.release.cover_image.name.startswith("covers/"))
            self.assertIn("/media/covers/", release_response.json()["cover_image"])

            artist_response = self.client.patch(
                f"/api/v1/cms/artists/{self.artist.id}/",
                {
                    "image": SimpleUploadedFile(
                        "artist.png", image_bytes, content_type="image/png"
                    )
                },
                format="multipart",
            )
            self.assertEqual(artist_response.status_code, 200, artist_response.content)
            self.artist.refresh_from_db()
            self.assertTrue(self.artist.image.name.startswith("artists/"))
            self.assertIn("/media/artists/", artist_response.json()["image"])
            self.client.force_authenticate(user=None)

    def test_all_public_facing_cms_saves_feed_the_app_payload(self):
        initial_revision = self.app_data()["revision"]
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
        self.assertNotEqual(data["revision"], initial_revision)
        revision_response = self.client.get("/api/v1/app-data/revision/")
        self.assertEqual(revision_response.status_code, 200)
        self.assertEqual(revision_response.json()["revision"], data["revision"])
        self.assertIn("no-store", revision_response["Cache-Control"])
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

    def test_multiple_main_and_featured_artists_are_structured_and_formatted(self):
        response = self.patch_cms(
            f"/api/v1/cms/releases/{self.release.id}/",
            {
                "primary_artist_ids": [self.artist.id, self.second_artist.id, self.third_artist.id],
                "featured_artist_ids": [self.featured_artist.id, self.featured_artist_two.id],
                "credited_artists": "Additional vocal credits",
                "songwriters": "Writer One, Writer Two",
                "producers": "Producer One",
                "release_date": "2026-05-15",
                "release_year": 2026,
                "isrc": "TEST12345678",
                "genre": "Afropop",
                "label": "Test Label",
                "distributor": "Test Distributor",
                "radio_info": "Clean radio edit available",
            },
        )
        self.assertEqual(response["artist_credit"], "Original Artist, Second Artist & Third Artist ft. Featured Artist & Guest Two")
        self.assertEqual(response["primary_artist_ids"], [self.artist.id, self.second_artist.id, self.third_artist.id])
        self.assertEqual(response["featured_artist_ids"], [self.featured_artist.id, self.featured_artist_two.id])

        data = self.app_data()
        row = data["full"]["singles"]["combined"]["June 2026"][0]
        release = next(item for item in data["releases"] if item["id"] == self.release.id)
        expected_credit = "Original Artist, Second Artist & Third Artist ft. Featured Artist & Guest Two"

        self.assertEqual(row["artist_credit"], expected_credit)
        self.assertEqual(release["artist_credit"], expected_credit)
        self.assertEqual([item["public_name"] for item in row["primary_artists"]], [
            "Original Artist", "Second Artist", "Third Artist"
        ])
        self.assertEqual([item["public_name"] for item in row["featured_artist_profiles"]], [
            "Featured Artist", "Guest Two"
        ])
        self.assertEqual(release["songwriters"], "Writer One, Writer Two")
        self.assertEqual(release["producers"], "Producer One")
        self.assertEqual(release["distributor"], "Test Distributor")
        self.assertEqual(release["radio_info"], "Clean radio edit available")

        public_artist_ids = {item["id"] for item in data["artists"]}
        self.assertTrue({
            self.artist.id,
            self.second_artist.id,
            self.third_artist.id,
            self.featured_artist.id,
            self.featured_artist_two.id,
        }.issubset(public_artist_ids))

        detail_response = self.client.get("/api/v1/app-data/artist/second-artist/")
        self.assertEqual(detail_response.status_code, 200, detail_response.content)
        detail = detail_response.json()
        self.assertIn(self.release.id, [item["id"] for item in detail["releases"]])
        self.assertIn(self.release.id, [item["release_id"] for item in detail["chart_history"]])
