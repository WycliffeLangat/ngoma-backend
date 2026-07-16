import base64
import io
import tempfile

from django.core.management import call_command
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.models import Q
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from .cms_utils import harmonize_chart_history
from .models import (
    AdminProfile,
    AdminRole,
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
    RegionalChartEntry,
    Release,
    ReleaseArtistCredit,
    SiteSetting,
    ChartUpload,
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
            month=7,
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

    def test_app_data_exposes_sorted_latest_published_month_metadata(self):
        data = self.app_data()
        month_options = data["month_options"]

        self.assertEqual(
            [(item["year"], item["month"]) for item in month_options],
            sorted((item["year"], item["month"]) for item in month_options),
        )
        self.assertEqual(data["months"], [item["label"] for item in month_options])
        self.assertEqual(data["latest_published_month"]["label"], "July 2026")
        self.assertEqual(data["latest_published_month"]["year"], 2026)
        self.assertEqual(data["latest_published_month"]["month"], 7)
        self.assertEqual(data["latest_published_by_chart_type"]["singles"]["label"], "July 2026")

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

    def test_release_save_derives_country_from_lead_artist(self):
        response = self.patch_cms(
            f"/api/v1/cms/releases/{self.release.id}/",
            {
                "title": "Country Drift Test",
                "country": "Tanzania",
                "country_code": "TZ",
            },
        )

        self.release.refresh_from_db()
        self.assertEqual(response["country"], "Test Country")
        self.assertEqual(response["country_code"], "TC")
        self.assertEqual(self.release.country, "Test Country")
        self.assertEqual(self.release.country_code, "TC")

    def test_release_country_stays_blank_when_lead_artist_has_no_country(self):
        blank_artist = Artist.objects.create(name="Blank Artist", slug="blank-artist")
        blank_release = Release.objects.create(
            title="Unassigned Country",
            artist=blank_artist,
            chart_type="albums",
            canonical_title="unassigned country",
            country="Tanzania",
            country_code="TZ",
        )

        response = self.patch_cms(
            f"/api/v1/cms/releases/{blank_release.id}/",
            {
                "title": "Still Unassigned",
                "country": "Tanzania",
                "country_code": "TZ",
            },
        )

        blank_release.refresh_from_db()
        self.assertEqual(response["country"], "")
        self.assertEqual(response["country_code"], "")
        self.assertEqual(blank_release.country, "")
        self.assertEqual(blank_release.country_code, "")

    def test_news_media_prefers_related_release_and_supports_gallery(self):
        self.release.cover_image = "covers/original-song.jpg"
        self.release.save(update_fields=["cover_image"])
        self.artist.image = "artists/original-artist.jpg"
        self.artist.save(update_fields=["image"])
        self.news.cover_image = "news/editorial.jpg"
        self.news.gallery = [{"url": "/media/news/context.jpg", "caption": "Context image"}]
        self.news.related_release = self.release
        self.news.save(update_fields=["cover_image", "gallery", "related_release"])

        data = self.app_data()
        article = next(item for item in data["news"] if item["id"] == self.news.id)
        self.assertGreaterEqual(len(article["media"]), 3)
        self.assertEqual(article["media"][0]["kind"], "release_cover")
        self.assertIn("/media/covers/original-song.jpg", article["media"][0]["url"])
        self.assertTrue(any(item["kind"] == "artist_image" for item in article["media"]))
        self.assertTrue(any(item["kind"] == "gallery" for item in article["media"]))

    def test_artist_country_update_overwrites_divergent_release_country(self):
        self.release.country = "Tanzania"
        self.release.country_code = "TZ"
        self.release.save(update_fields=["country", "country_code"])

        self.patch_cms(
            f"/api/v1/cms/artists/{self.artist.id}/",
            {
                "country": "Kenya",
                "country_code": "KE",
            },
        )

        self.release.refresh_from_db()
        self.assertEqual(self.release.country, "Kenya")
        self.assertEqual(self.release.country_code, "KE")

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
        row = data["full"]["singles"]["combined"]["July 2026"][0]
        self.assertEqual(row["t"], "Updated Song")
        self.assertEqual(row["a"], "Updated Artist")
        self.assertEqual(row["p"], 50)
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
        # Certification totals are derived from the published chart history;
        # changing a rule harmonizes the manual value back to the live total.
        self.assertEqual(certification["total_points"], 50)
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

    def test_cms_summary_loads_before_cached_detailed_insights(self):
        self.client.force_authenticate(self.admin)
        with CaptureQueriesContext(connection) as summary_queries:
            summary = self.client.get("/api/v1/cms/dashboard/")
        self.assertEqual(summary.status_code, 200, summary.content)
        self.assertIn("total_songs", summary.json()["cards"])
        self.assertNotIn("alerts", summary.json())
        self.assertLessEqual(len(summary_queries), 12)

        insights = self.client.get("/api/v1/cms/dashboard/insights/")
        self.assertEqual(insights.status_code, 200, insights.content)
        self.assertIn("alerts", insights.json())
        self.assertIn("top_performing", insights.json())

    def test_cms_large_lists_use_bounded_query_counts(self):
        self.client.force_authenticate(self.admin)
        targets = [
            ("/api/v1/cms/artists/?page_size=10", 12),
            ("/api/v1/cms/releases/?chart_type=singles&page_size=10", 15),
            ("/api/v1/cms/charts/?page_size=10", 8),
        ]
        for url, maximum in targets:
            with self.subTest(url=url):
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.get(url)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertLessEqual(
                    len(queries),
                    maximum,
                    f"{url} used {len(queries)} queries; expected no more than {maximum}",
                )

    def test_chart_options_endpoint_is_small_and_unpaginated(self):
        self.client.force_authenticate(self.admin)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/api/v1/cms/charts/options/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsInstance(response.json(), list)
        self.assertLessEqual(len(queries), 4)
        if response.json():
            self.assertEqual(
                set(response.json()[0]),
                {"id", "year", "month", "label", "chart_type", "status", "is_published"},
            )

    def test_draft_chart_entries_do_not_change_public_artist_history_or_stats(self):
        draft_chart = MonthlyChart.objects.create(
            year=2026, month=8, chart_type="singles", status="draft", is_published=False
        )
        MonthlyChartEntry.objects.create(
            chart=draft_chart,
            release=self.release,
            rank=1,
            total_points=9999,
        )

        response = self.client.get(f"/api/v1/app-data/artist/{self.artist.slug}/")
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["singles_stats"]["total_points"], 50)
        self.assertEqual(len(data["chart_history"]), 1)
        self.assertEqual(data["chart_history"][0]["month"], "July 2026")

    def test_public_year_end_and_analytics_ignore_draft_charts(self):
        draft_chart = MonthlyChart.objects.create(
            year=2026, month=8, chart_type="singles", status="draft", is_published=False
        )
        MonthlyChartEntry.objects.create(
            chart=draft_chart, release=self.release, rank=1, total_points=9999
        )

        year_end = self.client.get("/api/v1/charts/year_end/?chart_type=singles&year=2026")
        self.assertEqual(year_end.status_code, 200, year_end.content)
        release_result = next(
            entry for entry in year_end.json()["entries"]
            if entry["title"] == self.release.title and entry["artist"] == self.artist.name
        )
        self.assertEqual(release_result["total_points"], 50)

        analytics = self.client.get("/api/v1/charts/analytics/?chart_type=singles&year=2026")
        self.assertEqual(analytics.status_code, 200, analytics.content)
        self.assertNotIn("August 2026", analytics.json())

    def test_publish_validates_ranks_and_leaves_chart_editable(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(f"/api/v1/cms/charts/{self.chart.id}/publish/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["is_published"])

        # Publishing must never make a chart read-only — edits stay allowed.
        edit_response = self.client.patch(
            f"/api/v1/cms/chart-entries/{self.combined_entry.id}/",
            {"total_points": 999},
            format="json",
        )
        self.assertEqual(edit_response.status_code, 200, edit_response.content)
        self.client.force_authenticate(user=None)

    def test_data_editor_cannot_publish_or_hard_delete(self):
        editor = User.objects.create_user("data-editor", password="password", is_staff=True)
        AdminProfile.objects.create(user=editor, role=AdminRole.DATA_EDITOR)
        self.client.force_authenticate(editor)

        publish_response = self.client.post(
            f"/api/v1/cms/charts/{self.chart.id}/publish/", {}, format="json"
        )
        self.assertEqual(publish_response.status_code, 403)
        delete_response = self.client.delete(
            f"/api/v1/cms/artists/{self.artist.id}/hard_delete/"
        )
        self.assertEqual(delete_response.status_code, 403)

    def test_news_editor_cannot_mutate_chart_data(self):
        editor = User.objects.create_user("news-editor", password="password", is_staff=True)
        AdminProfile.objects.create(user=editor, role=AdminRole.NEWS_EDITOR)
        self.client.force_authenticate(editor)
        response = self.client.patch(
            f"/api/v1/cms/chart-entries/{self.combined_entry.id}/",
            {"total_points": 999},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

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
        self.combined_entry.refresh_from_db()
        self.platform_entry.refresh_from_db()
        self.assertEqual(self.combined_entry.featured_artists, "Featured Artist & Guest Two")
        self.assertEqual(self.platform_entry.featured_artists, "Featured Artist & Guest Two")
        self.assertEqual(self.combined_entry.release_year, 2026)
        self.assertEqual(self.platform_entry.release_year, 2026)

        data = self.app_data()
        row = data["full"]["singles"]["combined"]["July 2026"][0]
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

    def test_chart_entry_featured_edit_syncs_release_and_sibling_entries(self):
        response = self.patch_cms(
            f"/api/v1/cms/chart-entries/{self.combined_entry.id}/",
            {"featured_artists": "Correct Guest"},
        )
        self.assertEqual(response["featured_artists"], "Correct Guest")

        self.release.refresh_from_db()
        self.combined_entry.refresh_from_db()
        self.platform_entry.refresh_from_db()
        self.assertEqual(self.release.featured_artists, "Correct Guest")
        self.assertEqual(self.combined_entry.featured_artists, "Correct Guest")
        self.assertEqual(self.platform_entry.featured_artists, "Correct Guest")

    def test_remove_featured_artist_credit_command_cleans_only_featured_surfaces(self):
        duo = Artist.objects.create(name="Vestine & Dorcas", slug="vestine-dorcas", artist_type="duo")
        primary_release = Release.objects.create(
            title="Yebo (Nitawale)",
            artist=duo,
            chart_type="singles",
            canonical_title="yebo (nitawale)",
        )
        ReleaseArtistCredit.objects.create(
            release=primary_release,
            artist=duo,
            role="primary",
            position=0,
        )
        ReleaseArtistCredit.objects.create(
            release=self.release,
            artist=duo,
            role="featured",
            position=0,
        )
        ReleaseArtistCredit.objects.create(
            release=self.release,
            artist=self.featured_artist,
            role="featured",
            position=1,
        )
        self.release.featured_artists = "Featured Artist, Vestine & Dorcas"
        self.release.save(update_fields=["featured_artists"])
        self.combined_entry.featured_artists = "Vestine & Dorcas"
        self.combined_entry.save(update_fields=["featured_artists"])
        self.platform_entry.featured_artists = "Featured Artist, Vestine & Dorcas"
        self.platform_entry.save(update_fields=["featured_artists"])
        regional = RegionalChartEntry.objects.create(
            chart=self.chart,
            region="KE",
            release=self.release,
            rank=1,
            total_points=50,
            featured_artists="Vestine & Dorcas",
        )
        upload = ChartUpload.objects.create(
            chart_type="singles",
            year=2026,
            month=7,
            rows_data=[
                {"title": "Original Song", "featured_artists": "Vestine & Dorcas"},
                {"title": "Original Song", "featured_artists": "Featured Artist, Vestine & Dorcas"},
            ],
        )

        call_command(
            "remove_featured_artist_credit",
            "--artist-name",
            "Vestine & Dorcas",
            "--apply",
            stdout=io.StringIO(),
        )

        self.release.refresh_from_db()
        self.combined_entry.refresh_from_db()
        self.platform_entry.refresh_from_db()
        regional.refresh_from_db()
        upload.refresh_from_db()

        self.assertFalse(ReleaseArtistCredit.objects.filter(artist=duo, role="featured").exists())
        self.assertTrue(ReleaseArtistCredit.objects.filter(release=primary_release, artist=duo, role="primary").exists())
        self.assertEqual(self.release.featured_artists, "Featured Artist")
        self.assertEqual(self.combined_entry.featured_artists, "Featured Artist")
        self.assertEqual(self.platform_entry.featured_artists, "Featured Artist")
        self.assertEqual(regional.featured_artists, "Featured Artist")
        self.assertEqual(upload.rows_data[0]["featured_artists"], "")
        self.assertEqual(upload.rows_data[1]["featured_artists"], "Featured Artist")

    def test_canonicalize_vestine_dorcas_keeps_only_allowed_group_songs(self):
        target_names = ["Vestine", "Dorcas", "Vestine & Dorcas"]
        Release.objects.filter(
            Q(artist__name__in=target_names)
            | Q(artist_credits__artist__name__in=target_names)
            | Q(featured_artists__icontains="Vestine")
            | Q(featured_artists__icontains="Dorcas")
            | Q(credited_artists__icontains="Vestine")
            | Q(credited_artists__icontains="Dorcas")
        ).delete()
        Artist.objects.filter(name__in=target_names).delete()

        vestine = Artist.objects.create(
            name="Vestine",
            slug="vestine",
            artist_type="solo",
            country="Kenya",
            country_code="KE",
        )
        dorcas = Artist.objects.create(name="Dorcas", slug="dorcas", artist_type="solo")
        correct_artist = Artist.objects.create(
            name="Correct Artist",
            slug="correct-artist",
            country="Kenya",
            country_code="KE",
        )
        other_guest = Artist.objects.create(name="Other Guest", slug="other-guest")

        yebo = Release.objects.create(
            title="Yebo (Nitawale)",
            artist=vestine,
            chart_type="singles",
            canonical_title="yebo (nitawale)",
            featured_artists="Dorcas",
            credited_artists="Vestine & Dorcas",
        )
        ReleaseArtistCredit.objects.create(release=yebo, artist=vestine, role="primary", position=0)
        ReleaseArtistCredit.objects.create(release=yebo, artist=dorcas, role="featured", position=0)
        emmanuel = Release.objects.create(
            title="Emmanuel",
            artist=vestine,
            chart_type="singles",
            canonical_title="emmanuel",
        )
        ReleaseArtistCredit.objects.create(release=emmanuel, artist=vestine, role="primary", position=0)

        wrong_feature = Release.objects.create(
            title="Pawa",
            artist=correct_artist,
            chart_type="singles",
            canonical_title="pawa",
            featured_artists="Vestine & Dorcas",
            credited_artists="Correct Artist, Vestine",
        )
        ReleaseArtistCredit.objects.create(release=wrong_feature, artist=correct_artist, role="primary", position=0)
        ReleaseArtistCredit.objects.create(release=wrong_feature, artist=vestine, role="featured", position=0)
        ReleaseArtistCredit.objects.create(release=wrong_feature, artist=other_guest, role="featured", position=1)
        wrong_primary = Release.objects.create(
            title="Mistagged Song",
            artist=vestine,
            chart_type="singles",
            canonical_title="mistagged song",
        )
        ReleaseArtistCredit.objects.create(release=wrong_primary, artist=vestine, role="primary", position=0)
        yebo_entry = MonthlyChartEntry.objects.create(
            chart=self.chart,
            release=yebo,
            rank=2,
            total_points=45,
            featured_artists="Dorcas",
        )
        wrong_feature_entry = MonthlyChartEntry.objects.create(
            chart=self.chart,
            release=wrong_feature,
            rank=3,
            total_points=40,
            featured_artists="Vestine & Dorcas",
        )
        MonthlyChartEntry.objects.create(
            chart=self.chart,
            platform=self.platform,
            release=wrong_feature,
            rank=2,
            total_points=40,
            raw_total_points=40,
            featured_artists="Vestine & Dorcas",
        )
        MonthlyChartEntry.objects.create(
            chart=self.chart,
            release=wrong_primary,
            rank=4,
            total_points=35,
        )
        regional = RegionalChartEntry.objects.create(
            chart=self.chart,
            region="KE",
            release=wrong_feature,
            rank=1,
            total_points=40,
            featured_artists="Vestine & Dorcas",
        )
        upload = ChartUpload.objects.create(
            chart_type="singles",
            year=2026,
            month=7,
            rows_data=[
                {
                    "title": "Yebo (Nitawale)",
                    "artist": "Vestine",
                    "featured_artists": "Dorcas",
                    "credited_artists": "Vestine & Dorcas",
                },
                {
                    "title": "Pawa",
                    "artist": "Correct Artist ft. Vestine & Dorcas",
                    "featured_artists": "Vestine & Dorcas",
                    "credited_artists": "Correct Artist, Vestine",
                },
                {
                    "title": "Mistagged Song",
                    "artist": "Vestine",
                    "featured_artists": "Dorcas",
                },
            ],
        )

        call_command("canonicalize_vestine_dorcas", "--apply", stdout=io.StringIO())

        group = Artist.objects.get(name="Vestine & Dorcas")
        self.assertEqual(group.artist_type, "group")
        self.assertEqual(group.country_code, "KE")

        yebo.refresh_from_db()
        emmanuel.refresh_from_db()
        wrong_feature.refresh_from_db()
        wrong_primary.refresh_from_db()
        yebo_entry.refresh_from_db()
        wrong_feature_entry.refresh_from_db()
        regional.refresh_from_db()
        upload.refresh_from_db()
        vestine.refresh_from_db()
        dorcas.refresh_from_db()

        self.assertEqual(yebo.artist, group)
        self.assertEqual(emmanuel.artist, group)
        self.assertEqual(
            list(yebo.artist_credits.order_by("position").values_list("artist__name", "role")),
            [("Vestine & Dorcas", "primary")],
        )
        self.assertEqual(
            list(emmanuel.artist_credits.order_by("position").values_list("artist__name", "role")),
            [("Vestine & Dorcas", "primary")],
        )
        self.assertEqual(yebo.featured_artists, "")
        self.assertEqual(yebo.credited_artists, "")
        self.assertEqual(yebo_entry.featured_artists, "")

        self.assertEqual(wrong_feature.artist, correct_artist)
        self.assertEqual(wrong_feature.featured_artists, "Other Guest")
        self.assertEqual(wrong_feature.credited_artists, "Correct Artist")
        self.assertEqual(
            list(wrong_feature.artist_credits.order_by("position").values_list("artist__name", "role")),
            [("Correct Artist", "primary"), ("Other Guest", "featured")],
        )
        self.assertEqual(wrong_feature_entry.featured_artists, "Other Guest")
        self.assertEqual(regional.featured_artists, "Other Guest")

        self.assertEqual(wrong_primary.status, "archived")
        self.assertFalse(MonthlyChartEntry.objects.filter(release=wrong_primary).exists())
        self.assertEqual(vestine.status, "archived")
        self.assertEqual(dorcas.status, "archived")
        self.assertEqual(upload.rows_data[0]["artist"], "Vestine & Dorcas")
        self.assertEqual(upload.rows_data[0]["featured_artists"], "")
        self.assertEqual(upload.rows_data[0]["credited_artists"], "")
        self.assertEqual(upload.rows_data[1]["artist"], "Correct Artist")
        self.assertEqual(upload.rows_data[1]["featured_artists"], "")
        self.assertEqual(upload.rows_data[1]["credited_artists"], "Correct Artist")
        self.assertEqual(upload.rows_data[2]["artist"], "")
        self.assertEqual(upload.rows_data[2]["featured_artists"], "")

    def test_cms_blocks_vestine_dorcas_on_disallowed_releases_and_canonicalizes_allowed_aliases(self):
        target_names = ["Vestine", "Dorcas", "Vestine & Dorcas"]
        Release.objects.filter(
            Q(artist__name__in=target_names)
            | Q(artist_credits__artist__name__in=target_names)
            | Q(featured_artists__icontains="Vestine")
            | Q(featured_artists__icontains="Dorcas")
            | Q(credited_artists__icontains="Vestine")
            | Q(credited_artists__icontains="Dorcas")
        ).delete()
        Artist.objects.filter(name__in=target_names).delete()
        group = Artist.objects.create(name="Vestine & Dorcas", slug="vestine-dorcas-cms", artist_type="group")
        vestine = Artist.objects.create(name="Vestine", slug="vestine-cms", artist_type="solo")

        self.client.force_authenticate(self.admin)
        blocked = self.client.patch(
            f"/api/v1/cms/releases/{self.release.id}/",
            {"featured_artist_ids": [group.id]},
            format="json",
        )
        self.assertEqual(blocked.status_code, 400, blocked.content)
        self.assertIn("Yebo (Nitawale) and Emmanuel", str(blocked.content))
        self.assertFalse(
            ReleaseArtistCredit.objects.filter(
                release=self.release,
                artist__name="Vestine & Dorcas",
            ).exists()
        )

        yebo = Release.objects.create(
            title="Yebo (Nitawale)",
            artist=self.artist,
            chart_type="singles",
            canonical_title="yebo (nitawale)",
        )
        allowed = self.client.patch(
            f"/api/v1/cms/releases/{yebo.id}/",
            {"primary_artist_ids": [vestine.id]},
            format="json",
        )
        self.assertEqual(allowed.status_code, 200, allowed.content)
        self.client.force_authenticate(user=None)
        yebo.refresh_from_db()
        self.assertEqual(yebo.artist, group)
        self.assertEqual(
            list(yebo.artist_credits.values_list("artist__name", "role")),
            [("Vestine & Dorcas", "primary")],
        )


class ChartHistoryHarmonizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            "harmonize-admin",
            "harmonize@example.com",
            "password",
        )
        self.artist = Artist.objects.create(
            name="History Artist",
            slug="history-artist",
        )
        self.release_a = Release.objects.create(
            title="Release A",
            canonical_title="release a",
            artist=self.artist,
            chart_type="singles",
        )
        self.release_b = Release.objects.create(
            title="Release B",
            canonical_title="release b",
            artist=self.artist,
            chart_type="singles",
        )
        self.january = MonthlyChart.objects.create(
            year=2099,
            month=1,
            chart_type="singles",
            label="January 2099",
            status="published",
            is_published=True,
        )
        self.february = MonthlyChart.objects.create(
            year=2099,
            month=2,
            chart_type="singles",
            label="February 2099",
            status="published",
            is_published=True,
        )
        MonthlyChartEntry.objects.create(
            chart=self.january,
            release=self.release_a,
            rank=1,
            total_points=100,
            peak_rank=99,
        )
        MonthlyChartEntry.objects.create(
            chart=self.january,
            release=self.release_b,
            rank=2,
            total_points=50,
            peak_rank=99,
        )
        self.february_a = MonthlyChartEntry.objects.create(
            chart=self.february,
            release=self.release_a,
            rank=2,
            total_points=40,
            prev_rank=None,
            peak_rank=99,
        )
        MonthlyChartEntry.objects.create(
            chart=self.february,
            release=self.release_b,
            rank=1,
            total_points=60,
            prev_rank=None,
            peak_rank=99,
        )
        CertificationRule.objects.update_or_create(
            level="gold",
            defaults={"threshold": 100, "active": True},
        )

    def test_entry_edit_harmonizes_all_dependent_surfaces(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            f"/api/v1/cms/chart-entries/{self.february_a.id}/",
            {"total_points": 80},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)

        january_a = MonthlyChartEntry.objects.get(
            chart=self.january,
            release=self.release_a,
        )
        february_a = MonthlyChartEntry.objects.get(
            chart=self.february,
            release=self.release_a,
        )
        february_b = MonthlyChartEntry.objects.get(
            chart=self.february,
            release=self.release_b,
        )
        self.assertEqual((february_a.rank, february_b.rank), (1, 2))
        self.assertEqual(february_a.prev_rank, 1)
        self.assertEqual(february_b.prev_rank, 2)
        self.assertEqual(january_a.peak_rank, 1)
        self.assertEqual(february_a.peak_rank, 1)

        certification = Certification.objects.get(
            release=self.release_a,
            level="gold",
        )
        self.assertEqual(certification.total_points, 100)

        public = self.client.get("/api/v1/app-data/").json()
        row = next(
            item
            for item in public["full"]["singles"]["combined"]["February 2099"]
            if item["release_id"] == self.release_a.id
        )
        self.assertEqual(row["r"], 1)
        self.assertEqual(row["last_month"], 1)
        self.assertEqual(row["peak_rank"], 1)

    def test_scoped_harmonization_only_reranks_changed_chart(self):
        march = MonthlyChart.objects.create(
            year=2099,
            month=3,
            chart_type="singles",
            status="published",
            is_published=True,
        )
        march_a = MonthlyChartEntry.objects.create(
            chart=march,
            release=self.release_a,
            rank=1,
            total_points=50,
            raw_total_points=10,
        )
        march_b = MonthlyChartEntry.objects.create(
            chart=march,
            release=self.release_b,
            rank=2,
            total_points=49,
            raw_total_points=100,
        )

        self.february_a.raw_total_points = 100
        self.february_a.save(update_fields=["raw_total_points"])
        result = harmonize_chart_history(chart_ids=[self.february.id])

        self.february_a.refresh_from_db()
        march_a.refresh_from_db()
        march_b.refresh_from_db()
        self.assertEqual(result["charts"], 1)
        self.assertGreaterEqual(result["history_charts"], 3)
        self.assertEqual(self.february_a.rank, 1)
        self.assertEqual(
            (march_a.rank, march_b.rank),
            (1, 2),
            "An unchanged month must not be re-ranked during another month's upload.",
        )
        self.assertEqual(march_a.prev_rank, self.february_a.rank)

    def test_chart_publish_and_unpublish_rebuild_cross_month_history(self):
        june = MonthlyChart.objects.create(
            year=2100,
            month=6,
            chart_type="singles",
            status="published",
            is_published=True,
        )
        july = MonthlyChart.objects.create(
            year=2100,
            month=7,
            chart_type="singles",
            status="approved",
            is_published=False,
        )
        august = MonthlyChart.objects.create(
            year=2100,
            month=8,
            chart_type="singles",
            status="published",
            is_published=True,
        )

        for chart, rows in (
            (june, ((self.release_b, 1, 60), (self.release_a, 2, 40))),
            (july, ((self.release_a, 1, 80), (self.release_b, 2, 20))),
            (august, ((self.release_b, 1, 60), (self.release_a, 2, 40))),
        ):
            for release, rank, raw_points in rows:
                MonthlyChartEntry.objects.create(
                    chart=chart,
                    release=release,
                    rank=rank,
                    total_points=51 - rank,
                    raw_total_points=raw_points,
                    prev_rank=None,
                    peak_rank=99,
                )

        self.client.force_authenticate(self.admin)
        publish_response = self.client.post(
            f"/api/v1/cms/charts/{july.id}/publish/",
            {},
            format="json",
        )
        self.assertEqual(publish_response.status_code, 200, publish_response.content)

        july_a = MonthlyChartEntry.objects.get(chart=july, release=self.release_a)
        august_a = MonthlyChartEntry.objects.get(chart=august, release=self.release_a)
        self.assertEqual(july_a.prev_rank, 2)
        self.assertEqual(august_a.prev_rank, 1)

        public = self.client.get("/api/v1/app-data/").json()
        july_row = next(
            row
            for row in public["full"]["singles"]["combined"]["July 2100"]
            if row["release_id"] == self.release_a.id
        )
        august_row = next(
            row
            for row in public["full"]["singles"]["combined"]["August 2100"]
            if row["release_id"] == self.release_a.id
        )
        self.assertEqual(july_row["movement"], "+1")
        self.assertEqual(july_row["last_month"], 2)
        self.assertEqual(august_row["movement"], "-1")
        self.assertEqual(august_row["last_month"], 1)

        unpublish_response = self.client.post(
            f"/api/v1/cms/charts/{july.id}/unpublish/",
            {},
            format="json",
        )
        self.assertEqual(
            unpublish_response.status_code,
            200,
            unpublish_response.content,
        )

        august_a.refresh_from_db()
        self.assertIsNone(august_a.prev_rank)
        public = self.client.get("/api/v1/app-data/").json()
        self.assertNotIn(
            "July 2100",
            public["full"]["singles"]["combined"],
        )
        august_row = next(
            row
            for row in public["full"]["singles"]["combined"]["August 2100"]
            if row["release_id"] == self.release_a.id
        )
        self.assertEqual(august_row["movement"], "re-entry")
        self.assertEqual(august_row["last_month"], "—")
