from django.core.management.base import BaseCommand
from charts.models import Artist


ARTIST_COUNTRIES = {
    # Kenya
    "Bien": ("Kenya", "KE"),
    "Bensoul": ("Kenya", "KE"),
    "Charisma": ("Kenya", "KE"),
    "Dyana Cods": ("Kenya", "KE"),
    "H_art The Band": ("Kenya", "KE"),
    "H_ART THE BAND": ("Kenya", "KE"),
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

    # Tanzania
    "Ali Kiba": ("Tanzania", "TZ"),
    "Alikiba": ("Tanzania", "TZ"),
    "Barnaba": ("Tanzania", "TZ"),
    "Diamond Platnumz": ("Tanzania", "TZ"),
    "D Voice": ("Tanzania", "TZ"),
    "Harmonize": ("Tanzania", "TZ"),
    "Jay Melody": ("Tanzania", "TZ"),
    "Joel Lwaga": ("Tanzania", "TZ"),
    "Juma Jux": ("Tanzania", "TZ"),
    "Jux": ("Tanzania", "TZ"),
    "Lavalava": ("Tanzania", "TZ"),
    "Marioo": ("Tanzania", "TZ"),
    "Mboso": ("Tanzania", "TZ"),
    "Mbosso": ("Tanzania", "TZ"),
    "Mocco Genius": ("Tanzania", "TZ"),
    "Nandy": ("Tanzania", "TZ"),
    "Rayvanny": ("Tanzania", "TZ"),
    "Zuchu": ("Tanzania", "TZ"),

    # Uganda
    "Azawi": ("Uganda", "UG"),
    "Bebe Cool": ("Uganda", "UG"),
    "Bobi Wine": ("Uganda", "UG"),
    "Eddy Kenzo": ("Uganda", "UG"),
    "Joshua Baraka": ("Uganda", "UG"),
    "Jose Chameleone": ("Uganda", "UG"),
    "Spice Diana": ("Uganda", "UG"),
    "Vinka": ("Uganda", "UG"),

    # Nigeria
    "Asake": ("Nigeria", "NG"),
    "Ayra Starr": ("Nigeria", "NG"),
    "BNXN": ("Nigeria", "NG"),
    "Burna Boy": ("Nigeria", "NG"),
    "Ckay": ("Nigeria", "NG"),
    "CKay": ("Nigeria", "NG"),
    "Davido": ("Nigeria", "NG"),
    "Fireboy DML": ("Nigeria", "NG"),
    "Joeboy": ("Nigeria", "NG"),
    "Kizz Daniel": ("Nigeria", "NG"),
    "Omah Lay": ("Nigeria", "NG"),
    "Rema": ("Nigeria", "NG"),
    "Ruger": ("Nigeria", "NG"),
    "Simi": ("Nigeria", "NG"),
    "Tems": ("Nigeria", "NG"),
    "Wizkid": ("Nigeria", "NG"),
    "Young Jonn": ("Nigeria", "NG"),

    # South Africa
    "Blaq Diamond": ("South Africa", "ZA"),
    "Kabza De Small": ("South Africa", "ZA"),
    "Makhadzi": ("South Africa", "ZA"),
    "Master KG": ("South Africa", "ZA"),
    "Tyla": ("South Africa", "ZA"),

    # United States
    "Ariana Grande": ("United States", "US"),
    "Beyonce": ("United States", "US"),
    "Beyoncé": ("United States", "US"),
    "Bruno Mars": ("United States", "US"),
    "Cardi B": ("United States", "US"),
    "Chris Brown": ("United States", "US"),
    "Drake": ("Canada", "CA"),
    "Future": ("United States", "US"),
    "Kendrick Lamar": ("United States", "US"),
    "Metro Boomin": ("United States", "US"),
    "Molly Santana": ("United States", "US"),
    "Olivia Rodrigo": ("United States", "US"),
    "SZA": ("United States", "US"),
    "Taylor Swift": ("United States", "US"),
    "The Weeknd": ("Canada", "CA"),
    "Travis Scott": ("United States", "US"),

    # United Kingdom / Ireland / other common international entries
    "Adele": ("United Kingdom", "GB"),
    "Central Cee": ("United Kingdom", "GB"),
    "Coldplay": ("United Kingdom", "GB"),
    "Ed Sheeran": ("United Kingdom", "GB"),
    "Olivia Dean": ("United Kingdom", "GB"),
    "Sam Smith": ("United Kingdom", "GB"),

    # Ghana
    "Black Sherif": ("Ghana", "GH"),
    "King Promise": ("Ghana", "GH"),
    "Sarkodie": ("Ghana", "GH"),
    "Shatta Wale": ("Ghana", "GH"),
    "Stonebwoy": ("Ghana", "GH"),

    # Rwanda
    "Bruce Melodie": ("Rwanda", "RW"),
    "The Ben": ("Rwanda", "RW"),

    # Burundi
    "Sat-B": ("Burundi", "BI"),

    # DR Congo
    "Fally Ipupa": ("DR Congo", "CD"),
    "Innoss'B": ("DR Congo", "CD"),
    "Koffi Olomide": ("DR Congo", "CD"),
}


class Command(BaseCommand):
    help = "Update artist country and ISO country_code values for known artists."

    def handle(self, *args, **options):
        updated = 0
        not_found = []

        for artist_name, (country, country_code) in ARTIST_COUNTRIES.items():
            artist = Artist.objects.filter(name__iexact=artist_name).first()

            if not artist:
                not_found.append(artist_name)
                continue

            artist.country = country
            artist.country_code = country_code
            artist.save(update_fields=["country", "country_code"])
            updated += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated: {artist.name} → {country} / {country_code}"
                )
            )

        missing_country = Artist.objects.filter(country_code="").order_by("name")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Done. Updated {updated} artist(s)."))

        if not_found:
            self.stdout.write("")
            self.stdout.write("Names in the mapping not found in your database:")
            for name in not_found:
                self.stdout.write(f"- {name}")

        if missing_country.exists():
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Artists still missing country_code in your database:"
                )
            )

            for artist in missing_country:
                self.stdout.write(f"- {artist.name}")
