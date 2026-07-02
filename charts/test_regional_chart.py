from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from .cms_utils import harmonize_chart_history
from .models import (
    Artist,
    Country,
    MonthlyChart,
    MonthlyChartEntry,
    Platform,
    RegionalChartEntry,
    Release,
)


class RegionalChartCandidatePoolTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            "regional-admin",
            "regional@example.com",
            "password",
        )
        Country.objects.update_or_create(
            code="KE", defaults={"name": "Kenya", "active": True}
        )
        Country.objects.update_or_create(
            code="UG", defaults={"name": "Uganda", "active": True}
        )
        self.platform, _ = Platform.objects.update_or_create(
            slug="apple-music",
            defaults={
                "name": "Apple Music",
                "short_name": "Apple",
                "supports_singles": True,
                "active": True,
            },
        )
        self.second_platform, _ = Platform.objects.update_or_create(
            slug="audiomack",
            defaults={
                "name": "Audiomack",
                "short_name": "Audiomack",
                "supports_singles": True,
                "active": True,
            },
        )
        self.chart = MonthlyChart.objects.create(
            year=2098,
            month=6,
            chart_type="singles",
            label="June 2098",
            status="published",
            is_published=True,
        )

        international_artist = Artist.objects.create(
            name="Global Artist",
            slug="global-artist",
            country="Uganda",
            country_code="UG",
        )
        international_release = Release.objects.create(
            title="Global Number One",
            canonical_title="global number one",
            artist=international_artist,
            chart_type="singles",
        )
        MonthlyChartEntry.objects.create(
            chart=self.chart,
            release=international_release,
            rank=1,
            total_points=50,
            raw_total_points=10_000,
        )

        combined_only_artist = Artist.objects.create(
            name="Combined Only Kenyan Artist",
            slug="combined-only-kenyan-artist",
            country="Kenya",
            country_code="KE",
        )
        self.combined_only_release = Release.objects.create(
            title="Combined Only Kenyan Song",
            canonical_title="combined only kenyan song",
            artist=combined_only_artist,
            chart_type="singles",
        )
        MonthlyChartEntry.objects.create(
            chart=self.chart,
            release=self.combined_only_release,
            rank=2,
            total_points=49,
            raw_total_points=9_000,
        )

        self.kenyan_artists = []
        self.kenyan_releases = []
        for index in range(55):
            artist = Artist.objects.create(
                name=f"Kenyan Artist {index + 1}",
                slug=f"kenyan-artist-{index + 1}",
                country="Kenya",
                country_code="KE",
            )
            release = Release.objects.create(
                title=f"Kenyan Song {index + 1}",
                canonical_title=f"kenyan song {index + 1}",
                artist=artist,
                chart_type="singles",
            )
            MonthlyChartEntry.objects.create(
                chart=self.chart,
                platform=self.platform,
                release=release,
                rank=index + 1,
                total_points=max(50 - index, 0),
                raw_total_points=1_000 - index,
            )
            self.kenyan_artists.append(artist)
            self.kenyan_releases.append(release)

        # Deliberately give the first Kenyan release a contradictory Combined
        # raw score. Its regional score must still be the sum of platform rows.
        MonthlyChartEntry.objects.create(
            chart=self.chart,
            release=self.kenyan_releases[0],
            rank=3,
            total_points=48,
            raw_total_points=1,
        )
        MonthlyChartEntry.objects.create(
            chart=self.chart,
            platform=self.second_platform,
            release=self.kenyan_releases[0],
            rank=1,
            total_points=50,
            raw_total_points=500,
        )

    def test_region_is_independently_aggregated_from_all_platform_rows(self):
        harmonize_chart_history(chart_ids=[self.chart.id])

        rows = RegionalChartEntry.objects.filter(chart=self.chart, region="KE")
        self.assertEqual(rows.count(), 55)
        self.assertEqual(
            list(rows.order_by("rank").values_list("rank", flat=True)),
            list(range(1, 56)),
        )
        leader = rows.get(rank=1)
        self.assertEqual(leader.release_id, self.kenyan_releases[0].id)
        self.assertEqual(leader.raw_total_points, 1_500)
        self.assertEqual(leader.platform_count, 2)
        self.assertFalse(rows.filter(release=self.combined_only_release).exists())

        response = self.client.get("/api/v1/app-data/")
        self.assertEqual(response.status_code, 200, response.content)
        public_rows = response.json()["full"]["singles"]["regions"]["KE"]["June 2098"]
        self.assertEqual(len(public_rows), 50)
        self.assertEqual(public_rows[0]["t"], "Kenyan Song 1")
        self.assertEqual(public_rows[-1]["r"], 50)
        self.assertEqual(public_rows[-1]["p"], 1)
        artist_rows = response.json()["full"]["artists"]["regions"]["KE"]["June 2098"]
        self.assertEqual(len(artist_rows), 50)
        self.assertEqual(artist_rows[0]["t"], "Kenyan Artist 1")
        self.assertEqual(artist_rows[0]["rp"], 1_500)
        self.assertEqual(artist_rows[0]["p"], 50)
        self.assertEqual(artist_rows[-1]["p"], 1)
        self.assertNotIn("Combined Only Kenyan Artist", {row["t"] for row in artist_rows})

    def test_country_edit_resyncs_platform_only_regional_candidate(self):
        harmonize_chart_history(chart_ids=[self.chart.id])
        artist = self.kenyan_artists[-1]
        release_id = artist.releases.get().id
        self.assertTrue(
            RegionalChartEntry.objects.filter(
                chart=self.chart, region="KE", release_id=release_id
            ).exists()
        )

        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            f"/api/v1/cms/artists/{artist.id}/",
            {"country": "Uganda", "country_code": "UG"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(
            RegionalChartEntry.objects.filter(
                chart=self.chart, region="KE", release_id=release_id
            ).exists()
        )
