from django.core.management.base import BaseCommand
from django.db import transaction, IntegrityError

from charts.models import (
    Artist,
    Release,
    PlatformChartEntry,
    MonthlyChartEntry,
    Certification,
    NewsArticle,
)


# ===========================================================================
# 1. NAME NORMALISATION  (variant / duplicate / mojibake  ->  official name)
# ---------------------------------------------------------------------------
# These collapse rows that are really the SAME artist. Where casing or
# rendering was ambiguous, the official spelling was taken from Wikipedia /
# Music In Africa (e.g. "H_art the Band", "Alikiba", "CKay", "Mbosso").
# The command merges duplicates losslessly: releases and their chart entries
# are re-pointed to the surviving artist before the duplicate row is removed.
# ===========================================================================
NAME_FIXES = {
    # --- Encoding corruption (UTF-8 stored as Latin-1) -> correct unicode ---
    "BeyoncÃ©": "Beyoncé",
    "ROSÃ‰": "ROSÉ",
    "JoÃ© DwÃ¨t FilÃ©": "Joé Dwèt Filé",
    "Nikita Keringâ€™": "Nikita Kering",
    "Nikita Kering’": "Nikita Kering",
    # --- Casing / spacing duplicates -> single canonical form ---
    "Bruce africa": "Bruce Africa",
    "Jay melody": "Jay Melody",
    "mudra d viral": "Mudra D Viral",
    "Lilmaina": "Lil Maina",
    "DYANA CODS": "Dyana Cods",
    "Tyler, The creator": "Tyler, The Creator",
    "Bnxn": "BNXN",
    # --- Official-spelling consolidation (variant -> official) ---
    "Ali Kiba": "Alikiba",
    "Ckay": "CKay",
    "Mboso": "Mbosso",
    "Juma Jux": "Jux",
    "H_ART THE BAND": "H_art the Band",
    "H_art The Band": "H_art the Band",
}


# ===========================================================================
# 2. ARTIST -> (country, ISO 3166-1 alpha-2 code)
# ---------------------------------------------------------------------------
# Entries tagged "# verify" are best-effort guesses for niche / regional
# acts — please confirm these, since you know the roster better than any
# public source does.
# ===========================================================================
ARTIST_COUNTRIES = {
    # ---------------- Kenya ----------------
    "Bien": ("Kenya", "KE"),
    "Bien ft. Scar": ("Kenya", "KE"),
    "Bensoul": ("Kenya", "KE"),
    "Charisma": ("Kenya", "KE"),
    "Dyana Cods": ("Kenya", "KE"),
    "H_art the Band": ("Kenya", "KE"),
    "Iyanii": ("Kenya", "KE"),
    "Juxx": ("Kenya", "KE"),
    "Khaligraph Jones": ("Kenya", "KE"),
    "Matata": ("Kenya", "KE"),
    "Mejja": ("Kenya", "KE"),
    "Nikita Kering": ("Kenya", "KE"),
    "Nyashinski": ("Kenya", "KE"),
    "Octopizzo": ("Kenya", "KE"),
    "Otile Brown": ("Kenya", "KE"),
    "Sauti Sol": ("Kenya", "KE"),
    "Savara": ("Kenya", "KE"),
    "Wakadinali": ("Kenya", "KE"),
    "Willy Paul": ("Kenya", "KE"),
    "YBW Smith": ("Kenya", "KE"),
    "Zerb": ("Kenya", "KE"),
    "Bahati": ("Kenya", "KE"),
    "Nadia Mukami": ("Kenya", "KE"),
    "Boutross": ("Kenya", "KE"),
    "Breeder LW": ("Kenya", "KE"),
    "Bridget Blue": ("Kenya", "KE"),
    "Buruklyn Boyz": ("Kenya", "KE"),
    "BURUKLYN BOYZ": ("Kenya", "KE"),
    "Coster Ojwang": ("Kenya", "KE"),
    "Fathermoh": ("Kenya", "KE"),
    "Gody Tennor": ("Kenya", "KE"),
    "Jabidii": ("Kenya", "KE"),
    "Kaka Talanta": ("Kenya", "KE"),
    "Kell Kay": ("Kenya", "KE"),
    "Lil Maina": ("Kenya", "KE"),
    "Mad Clan": ("Kenya", "KE"),
    "Mr Seed": ("Kenya", "KE"),
    "Mudra D Viral": ("Kenya", "KE"),
    "Mutoriah": ("Kenya", "KE"),
    "Najeeriii": ("Kenya", "KE"),
    "Njerae": ("Kenya", "KE"),
    "Odongo Swagg": ("Kenya", "KE"),
    "OgaObinna": ("Kenya", "KE"),
    "Prince Indah": ("Kenya", "KE"),
    "Salim Junior": ("Kenya", "KE"),
    "Scar Mkadinali": ("Kenya", "KE"),
    "Ssaru": ("Kenya", "KE"),
    "Stephen Kasolo": ("Kenya", "KE"),
    "Toxic Lyrikali": ("Kenya", "KE"),
    "Trio Mio": ("Kenya", "KE"),
    "Wadagliz": ("Kenya", "KE"),
    "Wanavokali": ("Kenya", "KE"),
    "Watendawili": ("Kenya", "KE"),
    "Zzero Sufuri": ("Kenya", "KE"),
    "Fancy Fingers Refix - Fancy Fingers": ("Kenya", "KE"),
    "Emma Jalamo": ("Kenya", "KE"),
    "Joseph Kamaru": ("Kenya", "KE"),
    "Guardian Angel": ("Kenya", "KE"),
    "Angela Chibalonza": ("Kenya", "KE"),
    "Bella Kombo": ("Kenya", "KE"),
    "Eunice Njeri": ("Kenya", "KE"),
    "Isaiah Ndungu": ("Kenya", "KE"),
    "Phyllis Mbuthia": ("Kenya", "KE"),
    "Vicky Brilliance": ("Kenya", "KE"),
    "DJ Lyta": ("Kenya", "KE"),
    "DJ WIZZY 254": ("Kenya", "KE"),
    "SEAN MMG": ("Kenya", "KE"),
    "Koppa Gekon": ("Kenya", "KE"),         # verify
    "Amiso thwango": ("Kenya", "KE"),       # verify
    "Anni3": ("Kenya", "KE"),               # verify
    "Big yasa": ("Kenya", "KE"),            # verify
    "Excess Van": ("Kenya", "KE"),          # verify
    "From The Hood Music": ("Kenya", "KE"), # verify
    "Geniusjini x66": ("Kenya", "KE"),      # verify
    "Keemlyf": ("Kenya", "KE"),             # verify
    "Lexsil": ("Kenya", "KE"),              # verify
    "Mr Right": ("Kenya", "KE"),            # verify
    "Mr.Tee": ("Kenya", "KE"),              # verify
    "Ndotz": ("Kenya", "KE"),               # verify
    "Obby Alpha": ("Kenya", "KE"),          # verify
    "Othicho Jasuba": ("Kenya", "KE"),      # verify
    "prodbycpkshawn": ("Kenya", "KE"),      # verify
    "Soundkraft": ("Kenya", "KE"),          # verify
    "Spoiler": ("Kenya", "KE"),             # verify
    "Stella Mengele": ("Kenya", "KE"),      # verify
    "Toby Mr Romantic": ("Kenya", "KE"),    # verify
    "Tonny Young": ("Kenya", "KE"),         # verify
    "Uncle Eddy": ("Kenya", "KE"),          # verify
    "Mega": ("Kenya", "KE"),                # verify
    "Kouz1": ("Kenya", "KE"),               # verify
    "M.O.B": ("Kenya", "KE"),               # verify
    "HOOD BOYZ": ("Kenya", "KE"),           # verify
    "KODONGKLAN": ("Kenya", "KE"),          # verify
    "ZIGGY MADUDU": ("Kenya", "KE"),        # verify
    "Stanley & The Turbines": ("Kenya", "KE"),  # verify
    "Sosa The Prodigy": ("Kenya", "KE"),    # verify
    "Justin Vibes": ("Kenya", "KE"),        # verify

    # ---------------- Tanzania ----------------
    "Alikiba": ("Tanzania", "TZ"),
    "Barnaba": ("Tanzania", "TZ"),
    "Diamond Platnumz": ("Tanzania", "TZ"),
    "D Voice": ("Tanzania", "TZ"),
    "Harmonize": ("Tanzania", "TZ"),
    "Jay Melody": ("Tanzania", "TZ"),
    "Joel Lwaga": ("Tanzania", "TZ"),
    "Jux": ("Tanzania", "TZ"),
    "Lavalava": ("Tanzania", "TZ"),
    "Marioo": ("Tanzania", "TZ"),
    "Mbosso": ("Tanzania", "TZ"),
    "Mocco Genius": ("Tanzania", "TZ"),
    "Nandy": ("Tanzania", "TZ"),
    "Rayvanny": ("Tanzania", "TZ"),
    "Zuchu": ("Tanzania", "TZ"),
    "Aslam Tz": ("Tanzania", "TZ"),
    "Billnass": ("Tanzania", "TZ"),
    "Bruce Africa": ("Tanzania", "TZ"),
    "Darassa": ("Tanzania", "TZ"),
    "Dayoo": ("Tanzania", "TZ"),
    "Dully Sykes": ("Tanzania", "TZ"),
    "Ibraah": ("Tanzania", "TZ"),
    "Maua Sama": ("Tanzania", "TZ"),
    "Phina": ("Tanzania", "TZ"),
    "Roma Mkatoliki": ("Tanzania", "TZ"),
    "Stamina Shorwebwenzi": ("Tanzania", "TZ"),
    "Whozu": ("Tanzania", "TZ"),
    "Christina Shusho": ("Tanzania", "TZ"),
    "Zabron Singers": ("Tanzania", "TZ"),
    "Neema Gospel Choir": ("Tanzania", "TZ"),
    "Chege": ("Tanzania", "TZ"),            # verify (Kenyan & Tanzanian acts share this name)
    "DOBA GENJE": ("Tanzania", "TZ"),       # verify
    "Lony Bway": ("Tanzania", "TZ"),        # verify
    "Mr Pilato": ("Tanzania", "TZ"),        # verify
    "Yammi": ("Tanzania", "TZ"),            # verify
    "Shad Mziki": ("Tanzania", "TZ"),       # verify
    "Bruni Star": ("Tanzania", "TZ"),       # verify
    "Minister Danybless": ("Tanzania", "TZ"),  # verify

    # ---------------- Uganda ----------------
    "Azawi": ("Uganda", "UG"),
    "Bebe Cool": ("Uganda", "UG"),
    "Bobi Wine": ("Uganda", "UG"),
    "Eddy Kenzo": ("Uganda", "UG"),
    "Joshua Baraka": ("Uganda", "UG"),
    "Jose Chameleone": ("Uganda", "UG"),
    "Spice Diana": ("Uganda", "UG"),
    "Vinka": ("Uganda", "UG"),

    # ---------------- Rwanda ----------------
    "Bruce Melodie": ("Rwanda", "RW"),
    "The Ben": ("Rwanda", "RW"),
    "Israel Mbonyi": ("Rwanda", "RW"),

    # ---------------- DR Congo ----------------
    "Fally Ipupa": ("DR Congo", "CD"),
    "Koffi Olomide": ("DR Congo", "CD"),
    "YA LEVIS": ("DR Congo", "CD"),
    "Papi Clever & Dorcas": ("DR Congo", "CD"),  # verify (Congolese gospel duo based in Rwanda)

    # ---------------- Côte d'Ivoire ----------------
    "Debordo Leekunfa": ("Côte d'Ivoire", "CI"),

    # ---------------- Nigeria ----------------
    "Asake": ("Nigeria", "NG"),
    "Ayra Starr": ("Nigeria", "NG"),
    "BNXN": ("Nigeria", "NG"),
    "Burna Boy": ("Nigeria", "NG"),
    "CKay": ("Nigeria", "NG"),
    "Davido": ("Nigeria", "NG"),
    "Fireboy DML": ("Nigeria", "NG"),
    "Joeboy": ("Nigeria", "NG"),
    "Joefes": ("Nigeria", "NG"),
    "Kizz Daniel": ("Nigeria", "NG"),
    "Omah Lay": ("Nigeria", "NG"),
    "Rema": ("Nigeria", "NG"),
    "Ruger": ("Nigeria", "NG"),
    "Simi": ("Nigeria", "NG"),
    "Tems": ("Nigeria", "NG"),
    "Wizkid": ("Nigeria", "NG"),
    "Young Jonn": ("Nigeria", "NG"),
    "Ada Ehi": ("Nigeria", "NG"),
    "Adekunle Gold": ("Nigeria", "NG"),
    "Chike": ("Nigeria", "NG"),
    "Crayon": ("Nigeria", "NG"),
    "Dunsin Oyekan": ("Nigeria", "NG"),
    "Fido": ("Nigeria", "NG"),
    "Johnny Drille": ("Nigeria", "NG"),
    "Mercy Chinwo": ("Nigeria", "NG"),
    "Minister GUC": ("Nigeria", "NG"),
    "Patoranking": ("Nigeria", "NG"),
    "Qing Madi": ("Nigeria", "NG"),
    "Seyi Vibez": ("Nigeria", "NG"),
    "Victony": ("Nigeria", "NG"),
    "BoyPee": ("Nigeria", "NG"),

    # ---------------- Ghana ----------------
    "Black Sherif": ("Ghana", "GH"),
    "King Promise": ("Ghana", "GH"),
    "Sarkodie": ("Ghana", "GH"),
    "Shatta Wale": ("Ghana", "GH"),
    "Stonebwoy": ("Ghana", "GH"),
    "MOLIY": ("Ghana", "GH"),

    # ---------------- South Africa ----------------
    "Blaq Diamond": ("South Africa", "ZA"),
    "Kabza De Small": ("South Africa", "ZA"),
    "Makhadzi": ("South Africa", "ZA"),
    "Master KG": ("South Africa", "ZA"),
    "Tyla": ("South Africa", "ZA"),
    "Caiiro": ("South Africa", "ZA"),
    "Dlala Thukzin": ("South Africa", "ZA"),
    "Felo Le Tee": ("South Africa", "ZA"),
    "Khalil Harrison": ("South Africa", "ZA"),
    "Nandipha808": ("South Africa", "ZA"),
    "OSKIDO": ("South Africa", "ZA"),
    "TitoM": ("South Africa", "ZA"),
    "Tyler ICU": ("South Africa", "ZA"),

    # ---------------- United States ----------------
    "Ariana Grande": ("United States", "US"),
    "Beyoncé": ("United States", "US"),
    "Bruno Mars": ("United States", "US"),
    "Cardi B": ("United States", "US"),
    "Chris Brown": ("United States", "US"),
    "Future": ("United States", "US"),
    "Kendrick Lamar": ("United States", "US"),
    "Metro Boomin": ("United States", "US"),
    "Molly Santana": ("United States", "US"),
    "Olivia Rodrigo": ("United States", "US"),
    "SZA": ("United States", "US"),
    "Taylor Swift": ("United States", "US"),
    "Travis Scott": ("United States", "US"),
    "21 Savage": ("United States", "US"),
    "BigXthaPlug": ("United States", "US"),
    "Billie Eilish": ("United States", "US"),
    "Chandler Moore": ("United States", "US"),
    "Doechii": ("United States", "US"),
    "Don Toliver": ("United States", "US"),
    "Eminem": ("United States", "US"),
    "Frank Ocean": ("United States", "US"),
    "GloRilla": ("United States", "US"),
    "Gunna": ("United States", "US"),
    "J. Cole": ("United States", "US"),
    "Juice WRLD": ("United States", "US"),
    "Kanye West": ("United States", "US"),
    "Ken Carson": ("United States", "US"),
    "Khalid": ("United States", "US"),
    "Lady Gaga": ("United States", "US"),
    "Lil Tecca": ("United States", "US"),
    "Lil Uzi Vert": ("United States", "US"),
    "Megan Thee Stallion": ("United States", "US"),
    "Nicki Minaj": ("United States", "US"),
    "Playboi Carti": ("United States", "US"),
    "Quavo": ("United States", "US"),
    "Rod Wave": ("United States", "US"),
    "Sabrina Carpenter": ("United States", "US"),
    "SahBabii": ("United States", "US"),
    "Sasha Alex Sloan": ("United States", "US"),
    "Sexyy Red": ("United States", "US"),
    "Summer Walker": ("United States", "US"),
    "Tyler, The Creator": ("United States", "US"),
    "Yeat": ("United States", "US"),
    "YoungBoy Never Broke Again": ("United States", "US"),
    "One Voice Children's Choir": ("United States", "US"),

    # ---------------- Canada ----------------
    "Drake": ("Canada", "CA"),
    "The Weeknd": ("Canada", "CA"),
    "347aidan": ("Canada", "CA"),
    "PARTYNEXTDOOR": ("Canada", "CA"),
    "Preston Pablo": ("Canada", "CA"),

    # ---------------- United Kingdom ----------------
    "Adele": ("United Kingdom", "GB"),
    "Central Cee": ("United Kingdom", "GB"),
    "Coldplay": ("United Kingdom", "GB"),
    "Ed Sheeran": ("United Kingdom", "GB"),
    "Olivia Dean": ("United Kingdom", "GB"),
    "Sam Smith": ("United Kingdom", "GB"),
    "Dave": ("United Kingdom", "GB"),
    "Darkoo": ("United Kingdom", "GB"),
    "Nines": ("United Kingdom", "GB"),
    "Years & Years": ("United Kingdom", "GB"),

    # ---------------- Jamaica ----------------
    "Gyptian": ("Jamaica", "JM"),
    "Shenseea": ("Jamaica", "JM"),
    "Skillibeng": ("Jamaica", "JM"),
    "Vybz Kartel": ("Jamaica", "JM"),
    "Sophia George": ("Jamaica", "JM"),
    "Govana": ("Jamaica", "JM"),
    # NOTE: "SleepTherapy" is deliberately NOT mapped. It is a generic
    # white-noise / sleep-sounds catalogue name (rain, fireplace ambience),
    # not a real charting artist — recommend removing it from the data rather
    # than assigning a country. It will appear in the "STILL missing" report.

    # ---------------- Other international ----------------
    "Rihanna": ("Barbados", "BB"),
    "Loreen": ("Sweden", "SE"),
    "Alan Walker": ("Norway", "NO"),
    "Hanumankind": ("India", "IN"),
    "Maxi Priest": ("United Kingdom", "GB"),
    "ROSÉ": ("South Korea", "KR"),
    "Joé Dwèt Filé": ("France", "FR"),  # verify (French artist of Haitian descent)
}


class Command(BaseCommand):
    help = (
        "Normalise duplicate/variant artist names to their official spelling "
        "(merging rows losslessly), then set country and ISO country_code for "
        "every known artist."
    )

    # ----- merge helpers --------------------------------------------------
    def _merge_release(self, src_rel, dst_artist):
        """Re-point one release onto dst_artist, folding into an existing twin."""
        twin = (
            Release.objects.filter(
                canonical_title=src_rel.canonical_title,
                artist=dst_artist,
                chart_type=src_rel.chart_type,
            )
            .exclude(pk=src_rel.pk)
            .first()
        )
        if twin is None:
            src_rel.artist = dst_artist
            src_rel.save(update_fields=["artist"])
            return
        # A matching release already exists under the target artist:
        # move all child rows onto it, then drop the now-empty duplicate.
        for Model in (PlatformChartEntry, MonthlyChartEntry, Certification):
            for child in list(Model.objects.filter(release=src_rel)):
                try:
                    with transaction.atomic():
                        child.release = twin
                        child.save(update_fields=["release"])
                except IntegrityError:
                    child.delete()  # exact duplicate chart row
        src_rel.delete()

    def _merge_artist(self, src, dst):
        for rel in list(src.releases.all()):
            self._merge_release(rel, dst)
        NewsArticle.objects.filter(related_artist=src).update(related_artist=dst)
        src.delete()

    # ----- main -----------------------------------------------------------
    def handle(self, *args, **options):
        renamed, merged = [], []

        with transaction.atomic():
            for wrong, correct in NAME_FIXES.items():
                src = Artist.objects.filter(name__exact=wrong).first()
                if not src:
                    continue
                dst = (
                    Artist.objects.filter(name__iexact=correct)
                    .exclude(pk=src.pk)
                    .first()
                )
                if dst:
                    self._merge_artist(src, dst)
                    merged.append((wrong, correct))
                else:
                    src.name = correct
                    src.save(update_fields=["name"])
                    renamed.append((wrong, correct))

        updated, not_found = 0, []
        for name, (country, code) in ARTIST_COUNTRIES.items():
            artist = Artist.objects.filter(name__iexact=name).first()
            if not artist:
                not_found.append(name)
                continue
            artist.country = country
            artist.country_code = code
            artist.save(update_fields=["country", "country_code"])
            updated += 1
            self.stdout.write(
                self.style.SUCCESS(f"Updated: {artist.name} -> {country} / {code}")
            )

        # ----- report -----
        self.stdout.write("")
        if renamed:
            self.stdout.write(self.style.SUCCESS(f"Renamed {len(renamed)} artist(s):"))
            for w, c in renamed:
                self.stdout.write(f"  {w!r} -> {c!r}")
        if merged:
            self.stdout.write(self.style.SUCCESS(f"Merged {len(merged)} duplicate(s):"))
            for w, c in merged:
                self.stdout.write(f"  {w!r} merged into {c!r}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Done. Set country on {updated} artist(s)."))

        if not_found:
            self.stdout.write("")
            self.stdout.write("Names in the mapping not found in your database:")
            for name in not_found:
                self.stdout.write(f"- {name}")

        missing = Artist.objects.filter(country_code="").order_by("name")
        if missing.exists():
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING("Artists STILL missing a country_code:")
            )
            for artist in missing:
                self.stdout.write(f"- {artist.name}")
