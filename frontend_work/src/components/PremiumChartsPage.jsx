import { useEffect, useMemo, useState } from "react";

// Flag-derived accent colors shared with the Year End country tags.
const COUNTRY_ACCENTS = {
  BB: "#00267F", CA: "#D80621", CD: "#007FFF", CI: "#F77F00", CL: "#D52B1E", DE: "#FFCE00", FR: "#0055A4",
  GB: "#012169", GH: "#CE1126", IN: "#FF9933", JM: "#009B3A", KE: "#006600",
  KR: "#CD2E3A", NG: "#008751", NO: "#BA0C2F", PR: "#ED0000", RW: "#00A1DE", SE: "#006AA7",
  TZ: "#1EB53A", UG: "#D90000", US: "#3C3B6E", ZA: "#007749", ZW: "#319208",
};

function regionBadge(code) {
  const key = String(code || "").trim().toUpperCase();
  return { accent: COUNTRY_ACCENTS[key] || "#69716B" };
}

// Complete artist -> country map (generated from the full roster).
// The chart uses the API's country_code first; this is the fallback when
// the API doesn't supply one. 'SleepTherapy' is intentionally absent
// (it is a generic sleep-sounds catalogue name, not a real artist).
const ARTIST_COUNTRY_FALLBACK = {
  "21 Savage": { country: "United States", code: "US" },
  "347aidan": { country: "Canada", code: "CA" },
  "Ada Ehi": { country: "Nigeria", code: "NG" },
  "Adekunle Gold": { country: "Nigeria", code: "NG" },
  "Adele": { country: "United Kingdom", code: "GB" },
  "Alan Walker": { country: "Norway", code: "NO" },
  "Alikiba": { country: "Tanzania", code: "TZ" },
  "Amiso thwango": { country: "Kenya", code: "KE" },
  "Angela Chibalonza": { country: "Kenya", code: "KE" },
  "Anni3": { country: "Kenya", code: "KE" },
  "Ariana Grande": { country: "United States", code: "US" },
  "Asake": { country: "Nigeria", code: "NG" },
  "Aslam Tz": { country: "Tanzania", code: "TZ" },
  "Ayra Starr": { country: "Nigeria", code: "NG" },
  "Azawi": { country: "Uganda", code: "UG" },
  "Bahati": { country: "Kenya", code: "KE" },
  "Barnaba": { country: "Tanzania", code: "TZ" },
  "Bebe Cool": { country: "Uganda", code: "UG" },
  "Bella Kombo": { country: "Kenya", code: "KE" },
  "Bensoul": { country: "Kenya", code: "KE" },
  "BeyoncÃ©": { country: "United States", code: "US" },
  "Beyoncé": { country: "United States", code: "US" },
  "Bien": { country: "Kenya", code: "KE" },
  "Bien ft. Scar": { country: "Kenya", code: "KE" },
  "Big yasa": { country: "Kenya", code: "KE" },
  "BigXthaPlug": { country: "United States", code: "US" },
  "Billie Eilish": { country: "United States", code: "US" },
  "Billnass": { country: "Tanzania", code: "TZ" },
  "Black Sherif": { country: "Ghana", code: "GH" },
  "Blaq Diamond": { country: "South Africa", code: "ZA" },
  "Bnxn": { country: "Nigeria", code: "NG" },
  "BNXN": { country: "Nigeria", code: "NG" },
  "Bobi Wine": { country: "Uganda", code: "UG" },
  "Boutross": { country: "Kenya", code: "KE" },
  "BoyPee": { country: "Nigeria", code: "NG" },
  "Breeder LW": { country: "Kenya", code: "KE" },
  "Bridget Blue": { country: "Kenya", code: "KE" },
  "Bruce Africa": { country: "Tanzania", code: "TZ" },
  "Bruce africa": { country: "Tanzania", code: "TZ" },
  "Bruce Melodie": { country: "Rwanda", code: "RW" },
  "Bruni Star": { country: "Tanzania", code: "TZ" },
  "Bruno Mars": { country: "United States", code: "US" },
  "Burna Boy": { country: "Nigeria", code: "NG" },
  "BURUKLYN BOYZ": { country: "Kenya", code: "KE" },
  "Buruklyn Boyz": { country: "Kenya", code: "KE" },
  "Caiiro": { country: "South Africa", code: "ZA" },
  "Cardi B": { country: "United States", code: "US" },
  "Central Cee": { country: "United Kingdom", code: "GB" },
  "Chandler Moore": { country: "United States", code: "US" },
  "Charisma": { country: "Kenya", code: "KE" },
  "Chege": { country: "Tanzania", code: "TZ" },
  "Chike": { country: "Nigeria", code: "NG" },
  "Chris Brown": { country: "United States", code: "US" },
  "Christina Shusho": { country: "Tanzania", code: "TZ" },
  "CKay": { country: "Nigeria", code: "NG" },
  "Coldplay": { country: "United Kingdom", code: "GB" },
  "Coster Ojwang": { country: "Kenya", code: "KE" },
  "Crayon": { country: "Nigeria", code: "NG" },
  "D Voice": { country: "Tanzania", code: "TZ" },
  "Darassa": { country: "Tanzania", code: "TZ" },
  "Darkoo": { country: "United Kingdom", code: "GB" },
  "Dave": { country: "United Kingdom", code: "GB" },
  "Davido": { country: "Nigeria", code: "NG" },
  "Dayoo": { country: "Tanzania", code: "TZ" },
  "Debordo Leekunfa": { country: "Côte d'Ivoire", code: "CI" },
  "Diamond Platnumz": { country: "Tanzania", code: "TZ" },
  "DJ Lyta": { country: "Kenya", code: "KE" },
  "DJ WIZZY 254": { country: "Kenya", code: "KE" },
  "Dlala Thukzin": { country: "South Africa", code: "ZA" },
  "DOBA GENJE": { country: "Tanzania", code: "TZ" },
  "Doechii": { country: "United States", code: "US" },
  "Don Toliver": { country: "United States", code: "US" },
  "Drake": { country: "Canada", code: "CA" },
  "Dully Sykes": { country: "Tanzania", code: "TZ" },
  "Dunsin Oyekan": { country: "Nigeria", code: "NG" },
  "DYANA CODS": { country: "Kenya", code: "KE" },
  "Dyana Cods": { country: "Kenya", code: "KE" },
  "Ed Sheeran": { country: "United Kingdom", code: "GB" },
  "Eddy Kenzo": { country: "Uganda", code: "UG" },
  "Eminem": { country: "United States", code: "US" },
  "Emma Jalamo": { country: "Kenya", code: "KE" },
  "Eunice Njeri": { country: "Kenya", code: "KE" },
  "Excess Van": { country: "Kenya", code: "KE" },
  "Fally Ipupa": { country: "DR Congo", code: "CD" },
  "Fancy Fingers Refix - Fancy Fingers": { country: "Kenya", code: "KE" },
  "Fathermoh": { country: "Kenya", code: "KE" },
  "Felo Le Tee": { country: "South Africa", code: "ZA" },
  "Fido": { country: "Nigeria", code: "NG" },
  "Fireboy DML": { country: "Nigeria", code: "NG" },
  "Frank Ocean": { country: "United States", code: "US" },
  "From The Hood Music": { country: "Kenya", code: "KE" },
  "Future": { country: "United States", code: "US" },
  "Geniusjini x66": { country: "Kenya", code: "KE" },
  "GloRilla": { country: "United States", code: "US" },
  "Gody Tennor": { country: "Kenya", code: "KE" },
  "Govana": { country: "Jamaica", code: "JM" },
  "Guardian Angel": { country: "Kenya", code: "KE" },
  "Gunna": { country: "United States", code: "US" },
  "Gyptian": { country: "Jamaica", code: "JM" },
  "H_art the Band": { country: "Kenya", code: "KE" },
  "Hanumankind": { country: "India", code: "IN" },
  "Harmonize": { country: "Tanzania", code: "TZ" },
  "HOOD BOYZ": { country: "Kenya", code: "KE" },
  "Ibraah": { country: "Tanzania", code: "TZ" },
  "Isaiah Ndungu": { country: "Kenya", code: "KE" },
  "Israel Mbonyi": { country: "Rwanda", code: "RW" },
  "Iyanii": { country: "Kenya", code: "KE" },
  "J. Cole": { country: "United States", code: "US" },
  "Jabidii": { country: "Kenya", code: "KE" },
  "Jay Melody": { country: "Tanzania", code: "TZ" },
  "Jay melody": { country: "Tanzania", code: "TZ" },
  "Joeboy": { country: "Nigeria", code: "NG" },
  "Joefes": { country: "Nigeria", code: "NG" },
  "Joel Lwaga": { country: "Tanzania", code: "TZ" },
  "Johnny Drille": { country: "Nigeria", code: "NG" },
  "Jose Chameleone": { country: "Uganda", code: "UG" },
  "Joseph Kamaru": { country: "Kenya", code: "KE" },
  "Joshua Baraka": { country: "Uganda", code: "UG" },
  "JoÃ© DwÃ¨t FilÃ©": { country: "France", code: "FR" },
  "Joé Dwèt Filé": { country: "France", code: "FR" },
  "Juice WRLD": { country: "United States", code: "US" },
  "Justin Vibes": { country: "Kenya", code: "KE" },
  "Jux": { country: "Tanzania", code: "TZ" },
  "Juxx": { country: "Kenya", code: "KE" },
  "Kabza De Small": { country: "South Africa", code: "ZA" },
  "Kaka Talanta": { country: "Kenya", code: "KE" },
  "Kanye West": { country: "United States", code: "US" },
  "Keemlyf": { country: "Kenya", code: "KE" },
  "Kell Kay": { country: "Kenya", code: "KE" },
  "Ken Carson": { country: "United States", code: "US" },
  "Kendrick Lamar": { country: "United States", code: "US" },
  "Khalid": { country: "United States", code: "US" },
  "Khaligraph Jones": { country: "Kenya", code: "KE" },
  "Khalil Harrison": { country: "South Africa", code: "ZA" },
  "King Promise": { country: "Ghana", code: "GH" },
  "Kizz Daniel": { country: "Nigeria", code: "NG" },
  "KODONGKLAN": { country: "Kenya", code: "KE" },
  "Kahuti": { country: "Kenya", code: "KE" },
  "Kinoti": { country: "Kenya", code: "KE" },
  "Koffi Olomide": { country: "DR Congo", code: "CD" },
  "Koppa Gekon": { country: "Kenya", code: "KE" },
  "Kouz1": { country: "Kenya", code: "KE" },
  "Lady Gaga": { country: "United States", code: "US" },
  "Lavalava": { country: "Tanzania", code: "TZ" },
  "Lexsil": { country: "Kenya", code: "KE" },
  "Lil Maina": { country: "Kenya", code: "KE" },
  "Lil Tecca": { country: "United States", code: "US" },
  "Lil Uzi Vert": { country: "United States", code: "US" },
  "Lilmaina": { country: "Kenya", code: "KE" },
  "Lony Bway": { country: "Tanzania", code: "TZ" },
  "Loreen": { country: "Sweden", code: "SE" },
  "M.O.B": { country: "Kenya", code: "KE" },
  "Mad Clan": { country: "Kenya", code: "KE" },
  "Makhadzi": { country: "South Africa", code: "ZA" },
  "Marioo": { country: "Tanzania", code: "TZ" },
  "Master KG": { country: "South Africa", code: "ZA" },
  "Matata": { country: "Kenya", code: "KE" },
  "Maua Sama": { country: "Tanzania", code: "TZ" },
  "Maxi Priest": { country: "United Kingdom", code: "GB" },
  "Mbosso": { country: "Tanzania", code: "TZ" },
  "Mega": { country: "Kenya", code: "KE" },
  "Megan Thee Stallion": { country: "United States", code: "US" },
  "Mejja": { country: "Kenya", code: "KE" },
  "Mercy Chinwo": { country: "Nigeria", code: "NG" },
  "Metro Boomin": { country: "United States", code: "US" },
  "Minister Danybless": { country: "Tanzania", code: "TZ" },
  "Minister GUC": { country: "Nigeria", code: "NG" },
  "Mocco Genius": { country: "Tanzania", code: "TZ" },
  "MOLIY": { country: "Ghana", code: "GH" },
  "Molly Santana": { country: "United States", code: "US" },
  "Mr Pilato": { country: "Tanzania", code: "TZ" },
  "Mr Right": { country: "Kenya", code: "KE" },
  "Mr Seed": { country: "Kenya", code: "KE" },
  "Mr.Tee": { country: "Kenya", code: "KE" },
  "Mudra D Viral": { country: "Kenya", code: "KE" },
  "mudra d viral": { country: "Kenya", code: "KE" },
  "Mutoriah": { country: "Kenya", code: "KE" },
  "Nadia Mukami": { country: "Kenya", code: "KE" },
  "Najeeriii": { country: "Kenya", code: "KE" },
  "Nandipha808": { country: "South Africa", code: "ZA" },
  "Nandy": { country: "Tanzania", code: "TZ" },
  "Ndotz": { country: "Kenya", code: "KE" },
  "Neema Gospel Choir": { country: "Tanzania", code: "TZ" },
  "Nicki Minaj": { country: "United States", code: "US" },
  "Nikita Kering": { country: "Kenya", code: "KE" },
  "Nikita Keringâ€™": { country: "Kenya", code: "KE" },
  "Nikita Kering’": { country: "Kenya", code: "KE" },
  "Nines": { country: "United Kingdom", code: "GB" },
  "Njerae": { country: "Kenya", code: "KE" },
  "Nyashinski": { country: "Kenya", code: "KE" },
  "Obby Alpha": { country: "Kenya", code: "KE" },
  "Octopizzo": { country: "Kenya", code: "KE" },
  "Odongo Swagg": { country: "Kenya", code: "KE" },
  "OgaObinna": { country: "Kenya", code: "KE" },
  "Olivia Dean": { country: "United Kingdom", code: "GB" },
  "Olivia Rodrigo": { country: "United States", code: "US" },
  "Omah Lay": { country: "Nigeria", code: "NG" },
  "One Voice Children's Choir": { country: "United States", code: "US" },
  "OSKIDO": { country: "South Africa", code: "ZA" },
  "Othicho Jasuba": { country: "Kenya", code: "KE" },
  "Otile Brown": { country: "Kenya", code: "KE" },
  "Papi Clever & Dorcas": { country: "DR Congo", code: "CD" },
  "PARTYNEXTDOOR": { country: "Canada", code: "CA" },
  "Patoranking": { country: "Nigeria", code: "NG" },
  "Phina": { country: "Tanzania", code: "TZ" },
  "Phyllis Mbuthia": { country: "Kenya", code: "KE" },
  "Playboi Carti": { country: "United States", code: "US" },
  "Preston Pablo": { country: "Canada", code: "CA" },
  "Prince Indah": { country: "Kenya", code: "KE" },
  "prodbycpkshawn": { country: "Kenya", code: "KE" },
  "Qing Madi": { country: "Nigeria", code: "NG" },
  "Quavo": { country: "United States", code: "US" },
  "Rayvanny": { country: "Tanzania", code: "TZ" },
  "Rema": { country: "Nigeria", code: "NG" },
  "Rihanna": { country: "Barbados", code: "BB" },
  "Rod Wave": { country: "United States", code: "US" },
  "Roma Mkatoliki": { country: "Tanzania", code: "TZ" },
  "ROSÃ‰": { country: "South Korea", code: "KR" },
  "ROSÉ": { country: "South Korea", code: "KR" },
  "Ruger": { country: "Nigeria", code: "NG" },
  "Rvssian": { country: "Jamaica", code: "JM" },
  "Sabrina Carpenter": { country: "United States", code: "US" },
  "SahBabii": { country: "United States", code: "US" },
  "Salim Junior": { country: "Kenya", code: "KE" },
  "Sam Smith": { country: "United Kingdom", code: "GB" },
  "Sarkodie": { country: "Ghana", code: "GH" },
  "Sasha Alex Sloan": { country: "United States", code: "US" },
  "Sauti Sol": { country: "Kenya", code: "KE" },
  "Savara": { country: "Kenya", code: "KE" },
  "Scar Mkadinali": { country: "Kenya", code: "KE" },
  "SEAN MMG": { country: "Kenya", code: "KE" },
  "Sexyy Red": { country: "United States", code: "US" },
  "Seyi Vibez": { country: "Nigeria", code: "NG" },
  "Shad Mziki": { country: "Tanzania", code: "TZ" },
  "Shatta Wale": { country: "Ghana", code: "GH" },
  "Shenseea": { country: "Jamaica", code: "JM" },
  "Simi": { country: "Nigeria", code: "NG" },
  "Skillibeng": { country: "Jamaica", code: "JM" },
  "Sophia George": { country: "Jamaica", code: "JM" },
  "Sosa The Prodigy": { country: "Kenya", code: "KE" },
  "Soundkraft": { country: "Kenya", code: "KE" },
  "Spice Diana": { country: "Uganda", code: "UG" },
  "Spoiler": { country: "Kenya", code: "KE" },
  "Ssaru": { country: "Kenya", code: "KE" },
  "Stamina Shorwebwenzi": { country: "Tanzania", code: "TZ" },
  "Stanley & The Turbines": { country: "Kenya", code: "KE" },
  "Stella Mengele": { country: "Kenya", code: "KE" },
  "Stephen Kasolo": { country: "Kenya", code: "KE" },
  "Stonebwoy": { country: "Ghana", code: "GH" },
  "Summer Walker": { country: "United States", code: "US" },
  "SZA": { country: "United States", code: "US" },
  "Taylor Swift": { country: "United States", code: "US" },
  "Tems": { country: "Nigeria", code: "NG" },
  "The Ben": { country: "Rwanda", code: "RW" },
  "The Weeknd": { country: "Canada", code: "CA" },
  "TitoM": { country: "South Africa", code: "ZA" },
  "Toby Mr Romantic": { country: "Kenya", code: "KE" },
  "Tonny Young": { country: "Kenya", code: "KE" },
  "Toxic Lyrikali": { country: "Kenya", code: "KE" },
  "Travis Scott": { country: "United States", code: "US" },
  "Trio Mio": { country: "Kenya", code: "KE" },
  "Tyla": { country: "South Africa", code: "ZA" },
  "Tyler ICU": { country: "South Africa", code: "ZA" },
  "Tyler, The Creator": { country: "United States", code: "US" },
  "Tyler, The creator": { country: "United States", code: "US" },
  "Uncle Eddy": { country: "Kenya", code: "KE" },
  "Unspoken Salaton": { country: "Kenya", code: "KE" },
  "Vicky Brilliance": { country: "Kenya", code: "KE" },
  "Victony": { country: "Nigeria", code: "NG" },
  "Vinka": { country: "Uganda", code: "UG" },
  "Vybz Kartel": { country: "Jamaica", code: "JM" },
  "Wadagliz": { country: "Kenya", code: "KE" },
  "Wakadinali": { country: "Kenya", code: "KE" },
  "Wanavokali": { country: "Kenya", code: "KE" },
  "Watendawili": { country: "Kenya", code: "KE" },
  "Whozu": { country: "Tanzania", code: "TZ" },
  "Willy Paul": { country: "Kenya", code: "KE" },
  "Wizkid": { country: "Nigeria", code: "NG" },
  "YA LEVIS": { country: "DR Congo", code: "CD" },
  "Yammi": { country: "Tanzania", code: "TZ" },
  "YBW Smith": { country: "Kenya", code: "KE" },
  "Years & Years": { country: "United Kingdom", code: "GB" },
  "Yeat": { country: "United States", code: "US" },
  "Young Jonn": { country: "Nigeria", code: "NG" },
  "YoungBoy Never Broke Again": { country: "United States", code: "US" },
  "Zabron Singers": { country: "Tanzania", code: "TZ" },
  "Zerb": { country: "Kenya", code: "KE" },
  "ZIGGY MADUDU": { country: "Kenya", code: "KE" },
  "Zuchu": { country: "Tanzania", code: "TZ" },
  "Zzero Sufuri": { country: "Kenya", code: "KE" },
  "031choppa": { country: "South Africa", code: "ZA" },
  "2wentysixx": { country: "Tanzania", code: "TZ" },
  "A$AP Rocky": { country: "United States", code: "US" },
  "Abongo Jakabwana": { country: "Kenya", code: "KE" },
  "Addeh Prince": { country: "Kenya", code: "KE" },
  "Aidonia": { country: "Jamaica", code: "JM" },
  "Alex Warren": { country: "United States", code: "US" },
  "AUDREY NUNA": { country: "United States", code: "US" },
  "Ayetian": { country: "Jamaica", code: "JM" },
  "Babalwa M": { country: "South Africa", code: "ZA" },
  "Baby Keem": { country: "United States", code: "US" },
  "Bad Bunny": { country: "Puerto Rico", code: "PR" },
  "Barry Jhay": { country: "Nigeria", code: "NG" },
  "Bella Shmurda": { country: "Nigeria", code: "NG" },
  "Brandy Maina": { country: "Kenya", code: "KE" },
  "Brent Faiyaz": { country: "United States", code: "US" },
  "BTS": { country: "South Korea", code: "KR" },
  "Calad": { country: "Tanzania", code: "TZ" },
  "Chella": { country: "Nigeria", code: "NG" },
  "Ciara": { country: "United States", code: "US" },
  "Ciza": { country: "South Africa", code: "ZA" },
  "Clipse": { country: "United States", code: "US" },
  "Collo Blue": { country: "Kenya", code: "KE" },
  "Cris Mj": { country: "Chile", code: "CL" },
  "Countree Hype": { country: "Kenya", code: "KE" },
  "D-voice": { country: "Tanzania", code: "TZ" },
  "Daniel Caesar": { country: "Canada", code: "CA" },
  "Diameter Pallet": { country: "Kenya", code: "KE" },
  "Dj 4kerty": { country: "Nigeria", code: "NG" },
  "DJ CHEEM": { country: "United States", code: "US" },
  "DJ Maphorisa": { country: "South Africa", code: "ZA" },
  "DJ Smallz": { country: "South Africa", code: "ZA" },
  "Devrix Da Fubu": { country: "Kenya", code: "KE" },
  "Doja Cat": { country: "United States", code: "US" },
  "Dominic Fike": { country: "United States", code: "US" },
  "Dorcas": { country: "Rwanda", code: "RW" },
  "Dufla": { country: "Kenya", code: "KE" },
  "Eemoh": { country: "South Africa", code: "ZA" },
  "EJAE": { country: "United States", code: "US" },
  "Eddy G": { country: "Jamaica", code: "JM" },
  "Elevation Worship": { country: "United States", code: "US" },
  "ELISHA TOTO": { country: "Tanzania", code: "TZ" },
  "ELEMENT EleéeH": { country: "Rwanda", code: "RW" },
  "Enny Man Da Guitar": { country: "South Africa", code: "ZA" },
  "EsDeeKid": { country: "United Kingdom", code: "GB" },
  "FAVE": { country: "Nigeria", code: "NG" },
  "Fik Fameica": { country: "Uganda", code: "UG" },
  "FloyyMenor": { country: "Chile", code: "CL" },
  "FOLA": { country: "Nigeria", code: "NG" },
  "Gajendra Verma": { country: "India", code: "IN" },
  "GL_Ceejay": { country: "South Africa", code: "ZA" },
  "Goon Flavour": { country: "South Africa", code: "ZA" },
  "Gradine Toto": { country: "Kenya", code: "KE" },
  "HUNTR/X": { country: "South Korea", code: "KR" },
  "Harry Styles": { country: "United Kingdom", code: "GB" },
  "Intence": { country: "Jamaica", code: "JM" },
  "Isaiah Rashad": { country: "United States", code: "US" },
  "Ivanny": { country: "Tanzania", code: "TZ" },
  "JACKBOYS": { country: "United States", code: "US" },
  "JAE5": { country: "United Kingdom", code: "GB" },
  "Jahvillani": { country: "Jamaica", code: "JM" },
  "Jazzworx": { country: "South Africa", code: "ZA" },
  "JAZZWRLD": { country: "South Africa", code: "ZA" },
  "JELEEL!": { country: "United States", code: "US" },
  "JETTI": { country: "United States", code: "US" },
  "Kehlani": { country: "United States", code: "US" },
  "Kondela": { country: "Kenya", code: "KE" },
  "KPop Demon Hunters Cast": { country: "South Korea", code: "KR" },
  "KunaTino Music": { country: "Zimbabwe", code: "ZW" },
  "Kunmie": { country: "Nigeria", code: "NG" },
  "Kusslove": { country: "Tanzania", code: "TZ" },
  "Lady Maureen": { country: "Kenya", code: "KE" },
  "Lava Lava": { country: "Tanzania", code: "TZ" },
  "Leehleza": { country: "South Africa", code: "ZA" },
  "Licky Tones": { country: "Kenya", code: "KE" },
  "Lil Baby": { country: "United States", code: "US" },
  "Maandy": { country: "Kenya", code: "KE" },
  "MAD G": { country: "Kenya", code: "KE" },
  "MaWhoo": { country: "South Africa", code: "ZA" },
  "Malice": { country: "United States", code: "US" },
  "Mariah the Scientist": { country: "United States", code: "US" },
  "Michael Jackson": { country: "United States", code: "US" },
  "Minister James": { country: "Tanzania", code: "TZ" },
  "Myztro": { country: "South Africa", code: "ZA" },
  "Mugs.Roze": { country: "Jamaica", code: "JM" },
  "Nasty C": { country: "South Africa", code: "ZA" },
  "Nameless": { country: "Kenya", code: "KE" },
  "Neha Kakkar": { country: "India", code: "IN" },
  "Nathaniel Bassey": { country: "Nigeria", code: "NG" },
  "Nigy Boy": { country: "Jamaica", code: "JM" },
  "Nine Vicious": { country: "United States", code: "US" },
  "nk_njoroge": { country: "Kenya", code: "KE" },
  "ODUMODUBLVCK": { country: "Nigeria", code: "NG" },
  "Offset": { country: "United States", code: "US" },
  "Okello Max": { country: "Kenya", code: "KE" },
  "Olamide": { country: "Nigeria", code: "NG" },
  "Popcaan": { country: "Jamaica", code: "JM" },
  "Pusha T": { country: "United States", code: "US" },
  "RAYE": { country: "United Kingdom", code: "GB" },
  "REI AMI": { country: "United States", code: "US" },
  "Rymey": { country: "Jamaica", code: "JM" },
  "Saja Boys": { country: "South Korea", code: "KR" },
  "Sarz": { country: "Nigeria", code: "NG" },
  "Scotts Maphuma": { country: "South Africa", code: "ZA" },
  "Silent Addy": { country: "Ghana", code: "GH" },
  "Skeng": { country: "Jamaica", code: "JM" },
  "SUNS3T": { country: "South Africa", code: "ZA" },
  "Soul Touch Brand": { country: "Kenya", code: "KE" },
  "Sun-El Musician": { country: "South Africa", code: "ZA" },
  "T.I Blaze": { country: "Nigeria", code: "NG" },
  "The Second Voice": { country: "Kenya", code: "KE" },
  "Thukuthela": { country: "South Africa", code: "ZA" },
  "Teebone": { country: "Jamaica", code: "JM" },
  "Tommy Lee": { country: "Jamaica", code: "JM" },
  "Tml Vibez": { country: "Nigeria", code: "NG" },
  "Vestine": { country: "Rwanda", code: "RW" },
  "Vic West": { country: "Kenya", code: "KE" },
  "Udede": { country: "Kenya", code: "KE" },
  "Unjaps": { country: "South Africa", code: "ZA" },
  "Urban Chords": { country: "Nigeria", code: "NG" },
  "Wapendwa Muziki": { country: "Kenya", code: "KE" },
  "X.O": { country: "South Africa", code: "ZA" },
  "Xania Monet": { country: "United States", code: "US" },
  "Xduppy": { country: "South Africa", code: "ZA" },
  "Young Thug": { country: "United States", code: "US" },
  "Ywaya Tajiri": { country: "Kenya", code: "KE" },
  "Zaituni": { country: "Tanzania", code: "TZ" },
  "ZinedinexSguche": { country: "South Africa", code: "ZA" },
  "mikeeysmind": { country: "Germany", code: "DE" },
};

function normalizeArtistName(name) {
  return String(name || "")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase();
}

function findArtistCountryFallback(name) {
  const cleanName = String(name || "").trim();

  if (!cleanName) return null;

  if (ARTIST_COUNTRY_FALLBACK[cleanName]) {
    return ARTIST_COUNTRY_FALLBACK[cleanName];
  }

  const normalizedName = normalizeArtistName(cleanName);

  const exactMatchKey = Object.keys(ARTIST_COUNTRY_FALLBACK).find(
    (key) => normalizeArtistName(key) === normalizedName
  );

  if (exactMatchKey) {
    return ARTIST_COUNTRY_FALLBACK[exactMatchKey];
  }

  const primaryArtist = cleanName
    .split(/,|&| x | X | feat\.|ft\.|featuring/i)[0]
    ?.trim();

  if (primaryArtist && primaryArtist !== cleanName) {
    return findArtistCountryFallback(primaryArtist);
  }

  return null;
}

function useRealMobile(isMobileFromParent) {
  const getIsMobile = () => {
    if (typeof window === "undefined") return Boolean(isMobileFromParent);

    const widthCandidates = [
      window.innerWidth,
      window.visualViewport?.width,
      window.screen?.width,
      document.documentElement?.clientWidth,
    ].filter(Boolean);

    const smallestWidth = Math.min(...widthCandidates);

    const isSmallScreen = smallestWidth <= 768;

    const isTouchPhone =
      typeof navigator !== "undefined" &&
      /Android|iPhone|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);

    return isSmallScreen || isTouchPhone || Boolean(isMobileFromParent);
  };

  const [realMobile, setRealMobile] = useState(getIsMobile);

  useEffect(() => {
    function checkMobile() {
      setRealMobile(getIsMobile());
    }

    checkMobile();

    window.addEventListener("resize", checkMobile);
    window.addEventListener("orientationchange", checkMobile);

    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", checkMobile);
      window.visualViewport.addEventListener("scroll", checkMobile);
    }

    return () => {
      window.removeEventListener("resize", checkMobile);
      window.removeEventListener("orientationchange", checkMobile);

      if (window.visualViewport) {
        window.visualViewport.removeEventListener("resize", checkMobile);
        window.visualViewport.removeEventListener("scroll", checkMobile);
      }
    };
  }, [isMobileFromParent]);

  return realMobile;
}

export function countryCodeToFlag(countryCode) {
  const code = String(countryCode || "").trim().toUpperCase();

  if (code.length !== 2 || !/^[A-Z]{2}$/.test(code)) {
    return String.fromCodePoint(0x1f30d);
  }

  return code
    .split("")
    .map((letter) => String.fromCodePoint(127397 + letter.charCodeAt(0)))
    .join("");
}

export function getArtistCountry(item) {
  const directCode = String(item.artist_country_code || item.country_code || "").trim().toUpperCase();
  const publicData = typeof window !== "undefined" ? (window.__NGOMA_PUBLIC_DATA__ || {}) : {};
  const publicCountry = (code) => (publicData.countries || []).find(
    (country) => String(country.code || "").trim().toUpperCase() === String(code || "").trim().toUpperCase()
  );

  if (directCode) {
    const managedCountry = publicCountry(directCode);
    return {
      flag: managedCountry?.flag || countryCodeToFlag(directCode),
      country: managedCountry?.name || item.artist_country || item.country || "",
      code: directCode,
    };
  }

  const requestedArtist = String(item.primary_artist || item.artist || item.artist_name || "").trim().toLowerCase();
  const managedArtist = (publicData.artists || []).find((artist) => {
    const names = [artist.name, artist.display_name, artist.public_name, ...(artist.aliases || [])]
      .map((name) => String(name || "").trim().toLowerCase());
    return names.includes(requestedArtist);
  });
  if (managedArtist?.country_code) {
    const managedCountry = publicCountry(managedArtist.country_code);
    return {
      flag: managedCountry?.flag || countryCodeToFlag(managedArtist.country_code),
      country: managedCountry?.name || managedArtist.country || "",
      code: managedArtist.country_code,
    };
  }

  const fallback =
    findArtistCountryFallback(item.primary_artist) ||
    findArtistCountryFallback(item.artist) ||
    findArtistCountryFallback(item.artist_name) ||
    null;

  if (fallback) {
    return {
      flag: countryCodeToFlag(fallback.code),
      country: fallback.country,
      code: fallback.code,
    };
  }

  return {
    flag: "",
    country: "",
    code: "",
  };
}

export default function PremiumChartsPage({
  isMobile,
  loaded,
  F,
  GOLD,
  MEDALS,
  MONTHS,
  VO,
  PC,
  PLAT_LABEL,
  ct,
  setCt,
  month,
  setMonth,
  plat,
  setPlat,
  platList,
  vc,
  setVc,
  data,
  display,
  top,
  tp,
  isSingles,
  artists,
  setSelA,
  setSelR,
  onOpenArtist,
  onOpenRelease,
  getCombined,
  liveChartLoading,
  liveChartMeta,
  liveStatus,
  pageMax = "1240px",
  certificationForEntry = () => null,
  CertificationTag = () => null,
  isDark = false,
}) {
  const mobile = useRealMobile(isMobile);
  const safeGutter = mobile ? "clamp(20px, 5vw, 28px)" : "28px";
  const [expandedRowKey, setExpandedRowKey] = useState(null);
  const [detectedDarkMode, setDetectedDarkMode] = useState(() => {
    if (typeof window === "undefined" || typeof document === "undefined") return false;
    return (
      document.documentElement?.dataset?.ngomaTheme === "dark" ||
      document.body?.dataset?.ngomaTheme === "dark" ||
      window.localStorage?.getItem("ngoma-theme") === "dark"
    );
  });

  useEffect(() => {
    if (typeof window === "undefined" || typeof document === "undefined") return undefined;

    const syncDarkMode = () => {
      setDetectedDarkMode(
        document.documentElement?.dataset?.ngomaTheme === "dark" ||
          document.body?.dataset?.ngomaTheme === "dark" ||
          window.localStorage?.getItem("ngoma-theme") === "dark"
      );
    };

    syncDarkMode();

    const observer = new MutationObserver(syncDarkMode);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-ngoma-theme"] });
    if (document.body) {
      observer.observe(document.body, { attributes: true, attributeFilter: ["data-ngoma-theme"] });
    }
    window.addEventListener("storage", syncDarkMode);

    return () => {
      observer.disconnect();
      window.removeEventListener("storage", syncDarkMode);
    };
  }, []);

  const darkMode = Boolean(isDark || detectedDarkMode);
  const isArtistsChart = ct === "artists";

  const chartTitle = "NGOMA TOP 50";
  const chartRegion = "(KENYA)";
  const chartDisplayTitle = `${chartTitle} ${chartRegion}`;
  const chartLabel = isArtistsChart ? "Artists" : (isSingles ? "Singles" : "Albums");
  const platformLabel =
    liveChartMeta?.platform || (plat === "Combined" ? "Combined" : PLAT_LABEL[plat] || plat);
  const chartAccent = plat === "Combined" ? GOLD : PC[plat] || GOLD;
  const chartAccentInk = plat === "BOOMPLAY" ? "#007C7C" : chartAccent;

  function movement(item) {
    const movementType = String(item.movement || item.movement_type || "").toLowerCase();
    const isReEntry =
      item.reentry ||
      movementType === "reentry" ||
      movementType === "re-entry" ||
      movementType === "re" ||
      movementType === "r.e";

    if (isReEntry) return { type: "reentry", label: "RE" };

    if (item.is_new || movementType === "new") {
      return { type: "new", label: "NEW" };
    }

    if (item.prev === null || item.prev === undefined || item.prev === "") {
      return { type: "new", label: "NEW" };
    }

    const diff = Number(item.prev) - Number(item.rank);

    if (diff > 0) return { type: "up", label: `▲ ${diff}` };
    if (diff < 0) return { type: "down", label: `▼ ${Math.abs(diff)}` };

    return { type: "same", label: "—" };
  }

  function movementStyle(item) {
    const m = movement(item);

    if (m.type === "up") {
      return {
        color: "#2DB04A",
        background: "rgba(45,176,74,0.12)",
      };
    }

    if (m.type === "down") {
      return {
        color: "#E53935",
        background: "rgba(229,57,53,0.12)",
      };
    }

    if (m.type === "new") {
      return {
        color: GOLD,
        background: "rgba(184,134,11,0.14)",
      };
    }

    if (m.type === "reentry") {
      return {
        color: "#1565C0",
        background: "rgba(21,101,192,0.12)",
      };
    }

    return {
      color: "#777777",
      background: "#f2f2f2",
    };
  }

  function getReleaseProfile(item) {
    const lastMonth =
      item.last_month !== undefined && item.last_month !== null && item.last_month !== ""
        ? item.last_month
        : item.prev ?? "—";

    const peak =
      item.peak_rank !== undefined && item.peak_rank !== null && item.peak_rank !== ""
        ? item.peak_rank
        : calculateStaticPeak(item);

    return {
      lastMonth,
      peak,
    };
  }

  function calculateStaticPeak(item) {
    if (isArtistsChart || item?.is_artist_entry) return item.peak_rank || item.rank || "—";
    let peak = item.rank || "—";

    MONTHS.forEach((m) => {
      const found = getCombined(ct, m).find(
        (entry) => entry.title === item.title &&
          (entry.primary_artist || entry.artist) === (item.primary_artist || item.artist)
      );

      if (found && typeof found.rank === "number" && found.rank < peak) {
        peak = found.rank;
      }
    });

    return peak;
  }

  function openArtist(name) {
    if (onOpenArtist) {
      onOpenArtist(name);
      return;
    }
    const artist = artists.find((item) => item.n === name);
    if (artist) setSelA(artist);
  }

  function openRelease(item) {
    if (isArtistsChart || item?.is_artist_entry) {
      openArtist(item?.title || item?.primary_artist || item?.artist);
      return;
    }
    if (onOpenRelease) {
      onOpenRelease(item, isSingles ? "single" : "album");
      return;
    }
    setSelR({
      ...item,
      type: isSingles ? "single" : "album",
    });
  }

  function splitArtistTokens(artistText) {
    const source = normalizeDetailValue(artistText, "");
    if (!source) return [];

    const separatorPattern = /(\s*(?:,|&|\+|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b|\band\b|\bwith\b|\bx\b)\s*)/gi;
    const pieces = source.split(separatorPattern).filter((piece) => piece !== "");

    return pieces
      .map((piece) => {
        separatorPattern.lastIndex = 0;
        const isSeparator = separatorPattern.test(piece);
        separatorPattern.lastIndex = 0;
        return isSeparator
          ? { type: "separator", value: piece }
          : { type: "artist", value: piece.trim() };
      })
      .filter((piece) => piece.value);
  }

  function ArtistLinks({ item }) {
    const tokens = splitArtistTokens(item?.artist_credit || item?.artist || item?.primary_artist || item?.artist_name);
    if (!tokens.length) return null;

    return (
      <span style={styles.artistLinksWrap}>
        {tokens.map((token, tokenIndex) => {
          if (token.type === "separator") {
            return (
              <span
                key={`${token.value}-${tokenIndex}`}
                style={{ ...styles.artistSeparator, ...(darkMode ? styles.artistSeparatorDark : null) }}
              >
                {token.value}
              </span>
            );
          }

          return (
            <button
              key={`${token.value}-${tokenIndex}`}
              onClick={(event) => {
                event.stopPropagation();
                openArtist(token.value);
              }}
              className="ngoma-artist-link"
              style={{ ...styles.artistButton, ...(darkMode ? styles.artistButtonDark : null) }}
              title={`Open ${token.value}`}
            >
              {token.value}
            </button>
          );
        })}
      </span>
    );
  }

  function normalizeDetailValue(value, fallback = "—") {
    if (value === null || value === undefined || value === "") return fallback;
    if (Array.isArray(value)) {
      const joined = value
        .map((entry) => normalizeDetailValue(entry, ""))
        .filter(Boolean)
        .join(", ");
      return joined || fallback;
    }
    if (typeof value === "object") {
      return value.name || value.title || value.label || fallback;
    }
    return String(value).trim() || fallback;
  }

  function firstDetailValue(item, keys, fallback = "—") {
    for (const key of keys) {
      const value = item?.[key];
      const normalized = normalizeDetailValue(value, "");
      if (normalized) return normalized;
    }
    return fallback;
  }

  function getArtworkUrl(item) {
    const value = firstDetailValue(
      item,
      [
        "artwork",
        "artwork_url",
        "artworkUrl",
        "cover",
        "cover_url",
        "coverUrl",
        "cover_art",
        "album_art",
        "image",
        "image_url",
        "thumbnail",
        "thumbnail_url",
      ],
      ""
    );
    return value && value !== "—" ? value : "";
  }

  function getArtworkLabel(item) {
    const source = normalizeDetailValue(item?.title || item?.artist, "NG");
    return source
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0])
      .join("")
      .toUpperCase() || "NG";
  }

  function getReleaseYear(item) {
    const direct = firstDetailValue(
      item,
      ["year_of_release", "release_year", "year", "released", "releaseDate", "release_date", "date"],
      ""
    );
    const match = String(direct || "").match(/(?:19|20)\d{2}/);
    return match ? match[0] : "—";
  }

  function getPlatformDetails(item) {
    if (!isCombinedChart) return platformLabel || "—";
    return firstDetailValue(
      item,
      ["platforms", "platform_names", "platform_list", "plat", "platform_count"],
      item?.plat || "—"
    );
  }

  function getProducerDetails(item) {
    return firstDetailValue(
      item,
      ["producers", "producer", "produced_by", "production", "producer_names"],
      "—"
    );
  }

  function getSongwriterDetails(item) {
    return firstDetailValue(
      item,
      ["songwriters", "songwriter", "writers", "writer", "written_by", "composers", "composer"],
      "—"
    );
  }

  function ReleaseArtwork({ item, size = 50 }) {
    const artworkUrl = getArtworkUrl(item);
    const label = getArtworkLabel(item);

    return (
      <div
        style={{
          ...styles.releaseArtwork,
          width: size,
          height: size,
          minWidth: size,
          borderRadius: size <= 44 ? "13px" : "15px",
          background: `linear-gradient(135deg, ${chartAccent} 0%, #111111 100%)`,
        }}
        title={`${item.title || "Release"} artwork`}
      >
        {artworkUrl ? (
          <img
            src={artworkUrl}
            alt=""
            style={styles.releaseArtworkImage}
            loading="lazy"
          />
        ) : (
          <span style={styles.releaseArtworkFallback}>{label}</span>
        )}
      </div>
    );
  }

  function DetailCard({ label, value, wide = false, accent }) {
    return (
      <div
        style={{
          ...styles.detailCard,
          ...(darkMode ? styles.detailCardDark : null),
          ...(darkMode && label === "Platforms" ? styles.platformDetailCardDark : null),
          ...(wide ? styles.detailCardWide : null),
        }}
      >
        <span style={{ ...styles.detailCardLabel, ...(darkMode ? styles.detailCardLabelDark : null) }}>
          {label}
        </span>
        <span
          style={{
            ...styles.detailCardValue,
            ...(darkMode ? styles.detailCardValueDark : null),
            ...(accent && !darkMode ? { color: accent } : null),
          }}
        >
          {value || "—"}
        </span>
      </div>
    );
  }

  function managedArtistForItem(item) {
    if (item?.artist_profile) return item.artist_profile;
    const publicData = typeof window !== "undefined" ? (window.__NGOMA_PUBLIC_DATA__ || {}) : {};
    const requestedName = String(item?.title || item?.primary_artist || item?.artist || "").trim().toLowerCase();
    return (publicData.artists || []).find((artist) =>
      [artist.name, artist.display_name, artist.public_name, ...(artist.aliases || [])]
        .some((name) => String(name || "").trim().toLowerCase() === requestedName)
    ) || {};
  }

  function DetailLinks({ links = {} }) {
    const entries = [
      ["Spotify", links.spotify || links.spotify_url],
      ["Apple Music", links.apple_music || links.apple_music_url],
      ["YouTube", links.youtube || links.youtube_url],
      ["Boomplay", links.boomplay || links.boomplay_url],
      ["Audiomack", links.audiomack || links.audiomack_url],
      ["TikTok", links.tiktok || links.tiktok_url],
      ["Shazam", links.shazam || links.shazam_url],
      ["Instagram", links.instagram || links.instagram_url],
      ["X", links.x || links.x_url],
      ["Facebook", links.facebook || links.facebook_url],
      ["Website", links.website || links.website_url],
    ].filter(([, url]) => Boolean(url));
    if (!entries.length) return null;
    return (
      <div style={{ display: "flex", flexWrap: "wrap", gap: "7px" }}>
        {entries.map(([label, url]) => (
          <a key={`${label}-${url}`} href={url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()} style={{ color: chartAccent, fontWeight: 850, textDecoration: "none" }}>
            {label} ↗
          </a>
        ))}
      </div>
    );
  }

  function DetailPanel({ item, profile, artistCountry, badge, compact = false }) {
    const hasCountry = Boolean(artistCountry.country || artistCountry.code);
    const countryLabel = artistCountry.country
      ? `${artistCountry.country}${artistCountry.code ? ` (${artistCountry.code})` : ""}`
      : artistCountry.code || "";
    const gridStyle = compact ? styles.mobileDetailsGrid : styles.desktopDetailsGrid;

    if (isArtistsChart || item?.is_artist_entry) {
      const artistProfile = managedArtistForItem(item);
      const aliases = normalizeDetailValue(artistProfile.aliases || item.aliases, "");
      const artistLinks = artistProfile.social_links || item.social_links || {};
      const hasArtistLinks = Object.values(artistLinks).some(Boolean);
      return (
        <div style={gridStyle}>
          {compact && <DetailCard label="L.M" value={profile.lastMonth} />}
          {compact && <DetailCard label="Peak" value={profile.peak} />}
          {hasCountry && <DetailCard label="Country" value={countryLabel} accent={badge.accent} />}
          {isCombinedChart && <DetailCard label="Platforms" value={getPlatformDetails(item)} />}
          {isCombinedChart && <DetailCard label="Points" value={Number(item.pts || 0).toLocaleString()} />}
          {isCombinedChart && <DetailCard label="Entries" value={item.entries_count || "—"} />}
          <DetailCard label="Months" value={item.months_on_chart || "—"} />
          {(artistProfile.city_region || item.city_region) && <DetailCard label="City / Region" value={artistProfile.city_region || item.city_region} />}
          {(artistProfile.genre || item.genre) && <DetailCard label="Genre" value={artistProfile.genre || item.genre} />}
          {(artistProfile.artist_type || item.artist_type) && <DetailCard label="Artist type" value={artistProfile.artist_type || item.artist_type} />}
          {(artistProfile.verified || item.verified) && <DetailCard label="Verification" value="Verified artist" accent={badge.accent} />}
          {aliases && <DetailCard label="Aliases" value={aliases} wide />}
          {(artistProfile.biography || item.biography) && <DetailCard label="Biography" value={artistProfile.biography || item.biography} wide />}
          {hasArtistLinks && <DetailCard label="Artist links" value={<DetailLinks links={artistLinks} />} wide />}
        </div>
      );
    }

    const primaryCredit = firstDetailValue(item, ["primary_artist_credit"], "");
    const featuredCredit = firstDetailValue(item, ["featured_artist_credit"], "");
    const releaseLinks = {
      spotify_url: item.spotify_url,
      apple_music_url: item.apple_music_url,
      youtube_url: item.youtube_url,
      boomplay_url: item.boomplay_url,
      audiomack_url: item.audiomack_url,
      tiktok_url: item.tiktok_url,
      shazam_url: item.shazam_url,
    };
    const hasReleaseLinks = Object.values(releaseLinks).some(Boolean);
    return (
      <div style={gridStyle}>
        {compact && <DetailCard label="L.M" value={profile.lastMonth} />}
        {compact && <DetailCard label="Peak" value={profile.peak} />}
        {hasCountry && <DetailCard label="Country" value={countryLabel} accent={badge.accent} />}
        <DetailCard label="Platforms" value={getPlatformDetails(item)} />
        <DetailCard label="Year" value={getReleaseYear(item)} />
        {primaryCredit && <DetailCard label="Main artist(s)" value={primaryCredit} wide />}
        {featuredCredit && <DetailCard label="Featuring" value={featuredCredit} wide />}
        {item.credited_artists && <DetailCard label="Other credits" value={item.credited_artists} wide />}
        {item.release_date && <DetailCard label="Release date" value={item.release_date} />}
        {item.genre && <DetailCard label="Genre" value={item.genre} />}
        {item.label && <DetailCard label="Label" value={item.label} />}
        {item.distributor && <DetailCard label="Distributor" value={item.distributor} />}
        {item.number_of_tracks && <DetailCard label="Tracks" value={item.number_of_tracks} />}
        {item.isrc && <DetailCard label="ISRC" value={item.isrc} />}
        {item.upc && <DetailCard label="UPC" value={item.upc} />}
        {item.confidence && <DetailCard label="Confidence" value={item.confidence} />}
        {getProducerDetails(item) !== "—" && <DetailCard label="Producer(s)" value={getProducerDetails(item)} wide />}
        {getSongwriterDetails(item) !== "—" && <DetailCard label="Songwriter(s)" value={getSongwriterDetails(item)} wide />}
        {item.radio_info && <DetailCard label="Radio information" value={item.radio_info} wide />}
        {hasReleaseLinks && <DetailCard label="Listen / View" value={<DetailLinks links={releaseLinks} />} wide />}
      </div>
    );
  }

  // ----- Sortable columns -------------------------------------------------
  // Default ("rank"/"asc") preserves the chart's natural order.
  const [sort, setSort] = useState({ key: "rank", dir: "asc" });

  function sortValue(item, key) {
    const profile = getReleaseProfile(item);
    const num = (v) => {
      const n = Number(v);
      return Number.isFinite(n) ? n : Number.POSITIVE_INFINITY;
    };
    switch (key) {
      case "rank":
        return num(item.rank);
      case "lastMonth":
        return num(profile.lastMonth);
      case "peak":
        return num(profile.peak);
      case "platforms": {
        const m = String(item.plat || "").match(/^(\d+)/);
        return m ? Number(m[1]) : -1;
      }
      default:
        return num(item.rank);
    }
  }

  const sortedData = useMemo(() => {
    const copy = [...data];
    copy.sort((a, b) => {
      const av = sortValue(a, sort.key);
      const bv = sortValue(b, sort.key);
      if (av === bv) return Number(a.rank) - Number(b.rank); // stable tie-break
      return sort.dir === "asc" ? av - bv : bv - av;
    });
    return copy;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, sort, ct, month]);

  const shown = sortedData.slice(0, vc);

  function handleSort(key) {
    setSort((current) => {
      if (current.key !== key) {
        // Coverage reads most-first; rank history reads best-first.
        const firstDir = key === "platforms" ? "desc" : "asc";
        return { key, dir: firstDir };
      }
      return { key, dir: current.dir === "asc" ? "desc" : "asc" };
    });
  }

  function sortArrow(key) {
    if (sort.key !== key) return "";
    return sort.dir === "asc" ? " ▲" : " ▼";
  }

  function getRowKey(item, index) {
    return `${ct}-${month}-${plat}-${item.title}-${item.primary_artist || item.artist}-${item.rank}-${index}`;
  }

  function toggleRow(rowKey) {
    setExpandedRowKey((current) => (current === rowKey ? null : rowKey));
  }

  useEffect(() => {
    setExpandedRowKey(null);
  }, [ct, month, plat, vc]);

  function ChartToggle() {
    return (
      <div style={styles.toggleWrap}>
        {["singles", "albums", "artists"].map((item) => {
          const active = ct === item;

          return (
            <button
              key={item}
              onClick={() => {
                setCt(item);
                setPlat("Combined");
              }}
              style={{
                ...styles.toggleButton,
                background: active ? chartAccent : "#ffffff",
                color: active ? "#090909" : "#111111",
                borderColor: active ? chartAccent : "rgba(0,0,0,0.14)",
                flex: mobile ? 1 : "initial",
              }}
            >
              {item}
            </button>
          );
        })}
      </div>
    );
  }

  function MobileStat({ label, value }) {
    return (
      <div
        className={label === "Plat." ? "ngoma-platform-cell" : undefined}
        style={{
          ...styles.mobileMiniStat,
          ...(darkMode ? styles.mobileMiniStatDark : null),
        }}
      >
        <span style={{ ...styles.mobileMiniStatLabel, ...(darkMode ? styles.mobileMiniStatLabelDark : null) }}>
          {label}
        </span>
        <span style={{ ...styles.mobileMiniStatValue, ...(darkMode ? styles.mobileMiniStatValueDark : null) }}>
          {value}
        </span>
      </div>
    );
  }

  const sourceLabel = new Date().toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  const isCombinedChart = plat === "Combined";
  const crossPlatformHitsCount = data.filter((item) => {
    const count = Number(String(item.plat || item.platform_count || "").split("/")[0]);
    return count >= tp;
  }).length;
  const newEntriesCount = data.filter((item) => movement(item).type === "new").length;

  return (
    <>
      <style>{`
        .ngoma-premium-charts-dark .ngoma-title-link,
        .ngoma-premium-charts-dark .ngoma-title-link:visited,
        .ngoma-premium-charts-dark .ngoma-title-link:hover,
        .ngoma-app-shell[data-theme="dark"] .ngoma-premium-charts .ngoma-title-link,
        .ngoma-app-shell[data-theme="dark"] .ngoma-premium-charts .ngoma-title-link:visited,
        .ngoma-app-shell[data-theme="dark"] .ngoma-premium-charts .ngoma-title-link:hover {
          color: #FFFFFF !important;
          -webkit-text-fill-color: #FFFFFF !important;
        }
      `}</style>
      <div className={`ngoma-premium-charts ${darkMode ? "ngoma-premium-charts-dark" : ""}`} style={{...styles.page, padding: mobile ? `0 ${safeGutter} 28px` : "0 28px 34px", boxSizing: "border-box"}}>
      <section
        style={{
          ...styles.hero,
          maxWidth: pageMax,
          margin: "0 auto",
          boxSizing: "border-box",
          padding: mobile ? "28px 0 24px" : "42px 0 38px",
          opacity: loaded ? 1 : 0,
          transform: loaded ? "none" : "translateY(8px)",
        }}
      >
        <div style={{...styles.heroGlow,background:`linear-gradient(120deg, ${chartAccent}12 0%, transparent 54%, ${chartAccent}08 100%)`}} />

        <div
          style={{
            ...styles.eyebrowRow,
            fontSize: mobile ? "10px" : "11px",
            marginBottom: 0,
          }}
        >
          <span style={{ opacity: 0.65, letterSpacing: "0.5px" }}>{sourceLabel}</span>
          <span style={styles.eyebrowDivider}>/</span>
          <span>{platformLabel}</span>
          {liveChartLoading && (
            <>
              <span style={styles.eyebrowDivider}>/</span>
              <span>Loading</span>
            </>
          )}
        </div>

        <div
          style={{
            ...styles.heroMain,
            gridTemplateColumns: "1fr",
            gap: 0,
          }}
        >
          <div
            style={{
              ...styles.heroLeft,
              paddingTop: 0,
              paddingBottom: 0,
              transform: "none",
            }}
          >
            <h1
              aria-label={chartDisplayTitle}
              style={{
                ...styles.heroTitle,
                fontSize: mobile ? "30px" : "72px",
                letterSpacing: mobile ? "-0.45px" : "-2.6px",
                lineHeight: mobile ? 0.96 : 0.9,
                margin: mobile ? "28px 0 28px" : "38px 0 38px",
              }}
            >
              <span style={{ display: "block", whiteSpace: "nowrap" }}>{chartTitle}</span>
              <span
                style={{
                  display: "block",
                  marginTop: mobile ? "7px" : "10px",
                  fontFamily: "Inter, Arial, sans-serif",
                  fontSize: mobile ? "14px" : "24px",
                  fontWeight: 900,
                  lineHeight: 1,
                  letterSpacing: mobile ? "2.4px" : "4px",
                  color: chartAccentInk,
                  whiteSpace: "nowrap",
                }}
              >
                {chartRegion}
              </span>
            </h1>

            <div
              style={{
                ...styles.heroMeta,
                alignItems: "baseline",
              }}
            >
              <span
                style={{
                  fontSize: mobile ? "20px" : "24px",
                  fontWeight: 850,
                  letterSpacing: "-0.5px",
                  color: "#050505",
                }}
              >
                {month}
              </span>
            </div>
          </div>
        </div>
      </section>

      <section
        style={{
          ...styles.statsBand,
          maxWidth: pageMax,
          margin: "0 auto",
          boxSizing: "border-box",
          gridTemplateColumns: mobile ? "repeat(2, minmax(0, 1fr))" : `repeat(${isCombinedChart ? 4 : 3}, minmax(0, 1fr))`,
        }}
      >
        {[
          {
            label: "Entries",
            value: 50,
            sub: isArtistsChart ? "artists" : (isSingles ? "songs" : "albums"),
          },
          ...(isCombinedChart ? [{
            label: isArtistsChart ? "Cross-Platform Artists" : "Cross-Platform Hits",
            value: crossPlatformHitsCount,
            sub: `on all ${tp} platforms`,
          }] : []),
          {
            label: "New Entries",
            value: newEntriesCount,
            sub: "this month",
          },
          {
            label: "Chart Leader",
            value: top?.title || "—",
            sub: top ? top.artist : "",
            compact: true,
          },
        ].map((item, index) => (
          <div
            key={item.label}
            style={{
              ...styles.statItem,
              padding: mobile ? "15px 16px" : "18px 24px",
            }}
          >
            <div style={styles.statLabel}>{item.label}</div>
            <div
              style={{
                ...styles.statValue,
                fontSize: item.compact ? (mobile ? "15px" : "18px") : mobile ? "25px" : "30px",
                color: item.label === "Chart Leader" ? chartAccentInk : "#050505",
              }}
            >
              {item.value}
            </div>
            <div style={styles.statSub}>{item.sub}</div>
          </div>
        ))}
      </section>

      <section
        style={{
          ...styles.controls,
          maxWidth: pageMax,
          margin: "0 auto",
          boxSizing: "border-box",
          flexDirection: mobile ? "column" : "row",
          alignItems: mobile ? "stretch" : "center",
          padding: mobile ? "16px 18px" : "16px 28px",
        }}
      >
        <ChartToggle />

        <select
          value={month}
          onChange={(event) => setMonth(event.target.value)}
          style={{
            ...styles.select,
            width: mobile ? "100%" : "auto",
          }}
        >
          {MONTHS.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>

        <div style={mobile ? { position: "relative", width: "100%", minWidth: 0 } : { display: "contents" }}>
          <div
            style={{
              ...styles.platforms,
              gap: mobile ? "9px" : "6px",
              flexWrap: mobile ? "nowrap" : "wrap",
              overflowX: mobile ? "auto" : "visible",
              paddingBottom: mobile ? "6px" : 0,
              paddingRight: mobile ? "30px" : 0,
            }}
          >
            {platList.map((item) => {
              const active = plat === item;
              const color = item === "Combined" ? GOLD : PC[item] || GOLD;
              const ink = item === "BOOMPLAY" ? "#007C7C" : color;
              const label = item === "Combined" ? item : PLAT_LABEL[item] || item;

              return (
                <button
                  key={item}
                  onClick={() => setPlat(item)}
                  style={{
                    ...styles.platformButton,
                    padding: mobile ? "9px 15px" : "8px 12px",
                    borderColor: active ? color : "rgba(0,0,0,0.12)",
                    background: active ? `${color}18` : "#ffffff",
                    color: active ? ink : "#6b7280",
                    flexShrink: 0,
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>
          {mobile && <div style={styles.pillFade} />}
        </div>

        <div
          style={{
            ...styles.viewOptions,
            marginLeft: mobile ? 0 : "auto",
            width: mobile ? "100%" : "auto",
          }}
        >
          {VO.map((item) => {
            const active = vc === item.c;
            const disabled = item.c > data.length;

            return (
              <button
                key={item.c}
                onClick={() => !disabled && setVc(item.c)}
                disabled={disabled}
                style={{
                  ...styles.viewButton,
                  padding: mobile ? "11px 12px" : "8px 12px",
                  background: active ? "#ffffff" : "#f6f6f3",
                  color: active ? chartAccentInk : "#4b5563",
                  border: active ? `2px solid ${chartAccent}` : "1px solid #e5e7eb",
                  fontWeight: active ? 900 : 800,
                  opacity: disabled ? 0.4 : 1,
                  flex: mobile ? 1 : "initial",
                }}
              >
                {item.l}
              </button>
            );
          })}
        </div>
      </section>

      <section
        style={{
          ...styles.tableShell,
          borderTop:`3px solid ${chartAccent}`,
          maxWidth: pageMax,
          width: "100%",
          margin: mobile ? "16px auto 28px" : "24px auto 34px",
          boxSizing: "border-box",
          borderRadius: mobile ? "20px" : "26px",
        }}
      >
        <div
          style={{
            ...styles.tableTop,
            flexDirection: mobile ? "column" : "row",
            alignItems: mobile ? "flex-start" : "center",
            padding: mobile ? "20px 18px" : "24px 26px",
          }}
        >
          <div>
            <div
              style={{
                ...styles.tableTitle,
                fontSize: mobile ? "21px" : "24px",
              }}
            >
              {chartDisplayTitle}
            </div>
            <div style={styles.tableSub}>
              {chartLabel} · {platformLabel} · {month}
            </div>
          </div>

          <div style={styles.tableTopActions}>
            <div style={{...styles.tableRange,background:`${chartAccent}18`,color:chartAccentInk}}>Top {Math.min(vc, data.length)}</div>
          </div>
        </div>

        {!mobile && (
          <div style={styles.tableHeader}>
            <span
              style={{ ...styles.headerCell, cursor: "pointer" }}
              onClick={() => handleSort("rank")}
              title="Sort by position"
            >
              #{sortArrow("rank")}
            </span>
            <span style={styles.headerCell}>Move</span>
            <span style={styles.headerEntryCell}>{isArtistsChart ? "Artist" : (isSingles ? "Song" : "Album")}</span>
            <span
              style={{ ...styles.headerCell, cursor: "pointer" }}
              onClick={() => handleSort("lastMonth")}
              title="Sort by last month"
            >
              Last Month{sortArrow("lastMonth")}
            </span>
            <span
              style={{ ...styles.headerCell, cursor: "pointer" }}
              onClick={() => handleSort("peak")}
              title="Sort by peak position"
            >
              Peak{sortArrow("peak")}
            </span>
            <span style={styles.headerCell}>Details</span>
          </div>
        )}

        <div style={styles.rows}>
          {shown.map((item, index) => {
            const profile = getReleaseProfile(item);
            const move = movement(item);
            const moveStyle = movementStyle(item);
            const medalColor = item.rank <= 3 ? MEDALS[item.rank - 1] : "#050505";
            const artistCountry = getArtistCountry(item);
            const badge = regionBadge(artistCountry.code);
            const certification = isArtistsChart ? null : certificationForEntry(item, isSingles ? "single" : "album");
            const rowKey = getRowKey(item, index);
            const expanded = expandedRowKey === rowKey;

            if (mobile) {

              return (
                <div
                  key={rowKey}
                  style={{
                    ...styles.mobileRow,
                    animationDelay: `${Math.min(index * 20, 400)}ms`,
                    maxWidth: "100%",
                    boxSizing: "border-box",
                  }}
                  onMouseEnter={(event) => {
                    event.currentTarget.style.background = `${chartAccent}0B`;
                    event.currentTarget.style.boxShadow = `inset 4px 0 0 ${chartAccent}`;
                  }}
                  onMouseLeave={(event) => {
                    event.currentTarget.style.background = darkMode ? "#0d0f0d" : "#ffffff";
                    event.currentTarget.style.boxShadow = "none";
                  }}
                >
                  <div
                    style={{ ...styles.mobileCompactRow, cursor: "pointer" }}
                    onClick={() => toggleRow(rowKey)}
                    role="button"
                    aria-expanded={expanded}
                  >
                    <div style={{ ...styles.mobileRank, color: medalColor }}>{item.rank}</div>
                    <ReleaseArtwork item={item} size={42} />

                    <div style={styles.mobileEntryMain}>
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          openRelease(item);
                        }}
                        className="ngoma-title-link"
                        style={{ ...styles.titleButton, ...(darkMode ? styles.titleButtonDark : null), color: darkMode ? "#FFFFFF" : "#050505" }}
                      >
                        {item.title}
                      </button>

                      {isArtistsChart ? (
                        item.artist ? (
                          <div style={{...styles.artistLinksWrap, ...(darkMode ? styles.artistButtonDark : null), cursor:"default"}}>
                            {item.artist}
                          </div>
                        ) : null
                      ) : <ArtistLinks item={item} />}

                      {certification && (
                        <CertificationTag cert={certification} compact style={{ marginTop: "6px" }} />
                      )}
                    </div>

                    <div style={styles.mobileMovementWrap}>
                      <div
                        style={{
                          ...styles.moveBadge,
                          color: moveStyle.color,
                          background: moveStyle.background,
                          minWidth: "46px",
                        }}
                      >
                        {move.label || "—"}
                      </div>

                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          toggleRow(rowKey);
                        }}
                        style={{ ...styles.mobileDetailsToggle, ...(darkMode ? styles.mobileDetailsToggleDark : null) }}
                        aria-label={expanded ? "Hide chart details" : "Show chart details"}
                        aria-expanded={expanded}
                      >
                        {expanded ? "▴" : "▾"}
                      </button>
                    </div>
                  </div>

                  {expanded && (
                    <div style={{ ...styles.mobileExpandedDetails, ...(darkMode ? styles.mobileExpandedDetailsDark : null) }}>
                      <DetailPanel
                        item={item}
                        profile={profile}
                        artistCountry={artistCountry}
                        badge={badge}
                        compact
                      />
                    </div>
                  )}
                </div>
              );
            }

            return (
              <div key={rowKey} style={styles.desktopRowWrap}>
                <div
                  style={{
                    ...styles.row,
                    background: darkMode ? "#0d0f0d" : "#ffffff",
                    color: darkMode ? "#fffdf7" : "#050505",
                    animationDelay: `${Math.min(index * 20, 400)}ms`,
                  }}
                  onMouseEnter={(event) => {
                    event.currentTarget.style.background = `${chartAccent}0B`;
                    event.currentTarget.style.boxShadow = `inset 4px 0 0 ${chartAccent}`;
                  }}
                  onMouseLeave={(event) => {
                    event.currentTarget.style.background = darkMode ? "#0d0f0d" : "#ffffff";
                    event.currentTarget.style.boxShadow = "none";
                  }}
                >
                  <div
                    style={{
                      ...styles.rank,
                      color: medalColor,
                      justifySelf: "center",
                      textAlign: "center",
                    }}
                  >
                    {item.rank}
                  </div>

                  <div
                    style={{
                      ...styles.moveBadge,
                      color: moveStyle.color,
                      background: moveStyle.background,
                      justifySelf: "center",
                    }}
                  >
                    {move.label || "—"}
                  </div>

                  <div style={styles.entryCell}>
                    <ReleaseArtwork item={item} size={50} />

                    <div style={styles.entryText}>
                      <button
                        onClick={() => openRelease(item)}
                        className="ngoma-title-link"
                        style={{ ...styles.titleButton, ...(darkMode ? styles.titleButtonDark : null), color: darkMode ? "#FFFFFF" : "#050505" }}
                      >
                        {item.title}
                      </button>

                      {isArtistsChart ? (
                        item.artist ? (
                          <div style={{...styles.artistLinksWrap, ...(darkMode ? styles.artistButtonDark : null), cursor:"default"}}>
                            {item.artist}
                          </div>
                        ) : null
                      ) : <ArtistLinks item={item} />}

                      {certification && (
                        <CertificationTag cert={certification} compact style={{ marginTop: "6px" }} />
                      )}
                    </div>
                  </div>

                  <div style={{ ...styles.metaNumber, ...(darkMode ? styles.metaNumberDark : null) }}>{profile.lastMonth}</div>
                  <div style={{ ...styles.metaNumber, ...(darkMode ? styles.metaNumberDark : null) }}>{profile.peak}</div>
                  <button
                    type="button"
                    onClick={() => toggleRow(rowKey)}
                    style={{ ...styles.desktopDetailsToggle, ...(darkMode ? styles.desktopDetailsToggleDark : null) }}
                    aria-label={expanded ? "Hide chart details" : "Show chart details"}
                    aria-expanded={expanded}
                  >
                    {expanded ? "▴" : "▾"}
                  </button>
                </div>

                {expanded && (
                  <div style={{ ...styles.desktopExpandedDetails, ...(darkMode ? styles.desktopExpandedDetailsDark : null) }}>
                    <DetailPanel
                      item={item}
                      profile={profile}
                      artistCountry={artistCountry}
                      badge={badge}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div style={styles.tableFooter}>
          Showing {shown.length} of {data.length} · {month} · {platformLabel}
        </div>
      </section>

      </div>
    </>
  );
}

function MiniBars({ GOLD }) {
  return (
    <svg width="38" height="42" viewBox="0 0 22 24" style={{ flexShrink: 0 }}>
      <rect x="0" y="15" width="3.5" height="9" fill="#050505" rx="0.5" />
      <rect x="5.5" y="10" width="3.5" height="14" fill="#050505" rx="0.5" />
      <rect x="11" y="5" width="3.5" height="19" fill={GOLD} rx="0.5" />
      <rect x="16.5" y="0" width="3.5" height="24" fill="#050505" rx="0.5" />
    </svg>
  );
}

const styles = {
  page: {
    background: "#ffffff",
    color: "#050505",
    minHeight: "60vh",
    width: "100%",
    maxWidth: "100%",
    overflowX: "hidden",
  },

  hero: {
    position: "relative",
    overflow: "hidden",
    background: "#ffffff",
    borderBottom: "1px solid rgba(0,0,0,0.08)",
    transition: "all 0.5s ease-out",
    width: "100%",
    maxWidth: "100%",
  },

  heroGlow: {
    position: "absolute",
    inset: 0,
    background: "transparent",
    pointerEvents: "none",
  },

  eyebrowRow: {
    position: "relative",
    display: "flex",
    alignItems: "center",
    gap: "10px",
    flexWrap: "wrap",
    fontWeight: 800,
    letterSpacing: "2.6px",
    textTransform: "uppercase",
    color: "#555555",
  },

  eyebrowDivider: {
    color: "#c89116",
  },

  heroMain: {
    position: "relative",
    display: "grid",
    alignItems: "end",
    width: "100%",
    maxWidth: "100%",
  },

  heroLeft: {
    minWidth: 0,
    maxWidth: "100%",
  },

  logoRow: {
    display: "flex",
    gap: "16px",
    alignItems: "center",
  },

  logoText: {
    fontWeight: 900,
    color: "#050505",
  },

  logoSub: {
    marginTop: "4px",
    fontSize: "11px",
    letterSpacing: "2px",
    textTransform: "uppercase",
    color: "#777777",
  },

  heroTitle: {
    margin: 0,
    lineHeight: 0.92,
    fontWeight: 950,
    textTransform: "uppercase",
    color: "#050505",
    maxWidth: "100%",
    overflowWrap: "break-word",
  },

  heroMeta: {
    display: "flex",
    flexWrap: "wrap",
    color: "#777777",
  },

  heroMetaSmall: {
    fontSize: "12px",
    color: "#777777",
    letterSpacing: "1.5px",
    textTransform: "uppercase",
  },

  numberOneCard: {
    background: "#ffffff",
    border: "1px solid rgba(0,0,0,0.08)",
    boxShadow: "0 14px 40px rgba(0,0,0,0.08)",
    maxWidth: "100%",
  },

  numberOneLabel: {
    fontSize: "11px",
    fontWeight: 900,
    letterSpacing: "2.5px",
    textTransform: "uppercase",
    color: "#777777",
  },

  numberOneRank: {
    marginTop: "12px",
    lineHeight: 0.85,
    fontWeight: 950,
    color: "#c89116",
  },

  numberOneTitle: {
    display: "block",
    border: "none",
    background: "transparent",
    padding: 0,
    marginTop: "18px",
    textAlign: "left",
    color: "#050505",
    fontWeight: 900,
    lineHeight: 1.05,
    cursor: "pointer",
    maxWidth: "100%",
    overflowWrap: "break-word",
  },

  numberOneArtist: {
    border: "none",
    background: "transparent",
    padding: 0,
    marginTop: "8px",
    color: "#777777",
    fontSize: "15px",
    fontWeight: 700,
    cursor: "pointer",
  },

  coveragePill: {
    display: "inline-flex",
    marginTop: "18px",
    padding: "8px 13px",
    borderRadius: "999px",
    background: "rgba(200,145,22,0.14)",
    color: "#c89116",
    fontSize: "12px",
    fontWeight: 900,
  },

  statsBand: {
    display: "grid",
    background: "#ffffff",
    borderTop: "1px solid rgba(0,0,0,0.08)",
    borderBottom: "1px solid rgba(0,0,0,0.08)",
    width: "100%",
    maxWidth: "100%",
  },

  statItem: {
    borderRight: "1px solid rgba(0,0,0,0.08)",
    minWidth: 0,
  },

  statLabel: {
    fontSize: "10.5px",
    letterSpacing: "1.6px",
    textTransform: "uppercase",
    color: "#555555",
    fontWeight: 900,
  },

  statValue: {
    marginTop: "8px",
    fontWeight: 950,
    lineHeight: 1,
    whiteSpace: "normal",
    overflow: "visible",
    textOverflow: "clip",
    color: "#050505",
  },

  statSub: {
    marginTop: "6px",
    fontSize: "12px",
    color: "#777777",
  },

  controls: {
    display: "flex",
    gap: "10px",
    flexWrap: "wrap",
    background: "#ffffff",
    color: "#111111",
    borderBottom: "1px solid #EAEAE6",
    width: "100%",
    maxWidth: "100%",
    overflow: "hidden",
  },

  toggleWrap: {
    display: "flex",
    gap: "6px",
    padding: "4px",
    borderRadius: "999px",
    background: "#f2f2f2",
    border: "1px solid rgba(0,0,0,0.08)",
    width: "100%",
    maxWidth: "100%",
  },

  toggleButton: {
    border: "1px solid",
    borderRadius: "999px",
    padding: "8px 14px",
    fontSize: "11px",
    fontWeight: 900,
    letterSpacing: "1.5px",
    textTransform: "uppercase",
    cursor: "pointer",
  },

  select: {
    padding: "9px 12px",
    borderRadius: "12px",
    border: "1px solid #d1d5db",
    background: "#ffffff",
    color: "#050505",
    fontSize: "13px",
    fontWeight: 700,
    outline: "none",
  },

  platforms: {
    display: "flex",
    gap: "6px",
    scrollbarWidth: "thin",
    maxWidth: "100%",
  },

  platformButton: {
    border: "1.5px solid",
    borderRadius: "999px",
    background: "#ffffff",
    padding: "8px 12px",
    fontSize: "12px",
    fontWeight: 800,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },

  viewOptions: {
    display: "flex",
    gap: "6px",
  },

  viewButton: {
    border: "1px solid #e5e7eb",
    borderRadius: "10px",
    padding: "8px 12px",
    fontSize: "12px",
    fontWeight: 800,
    cursor: "pointer",
  },

  tableShell: {
    background: "#ffffff",
    color: "#050505",
    border: "1px solid rgba(0,0,0,0.08)",
    overflow: "hidden",
    boxShadow: "0 14px 40px rgba(0,0,0,0.08)",
    maxWidth: "100%",
  },

  tableTop: {
    display: "flex",
    justifyContent: "space-between",
    gap: "20px",
    borderBottom: "1px solid rgba(0,0,0,0.08)",
    background: "#ffffff",
    color: "#050505",
  },

  tableTitle: {
    fontWeight: 950,
    letterSpacing: "-0.5px",
    color: "#050505",
  },

  tableSub: {
    marginTop: "6px",
    fontSize: "12px",
    color: "#555555",
    fontWeight: 800,
    letterSpacing: "1.2px",
    textTransform: "uppercase",
  },

  tableRange: {
    padding: "10px 14px",
    borderRadius: "999px",
    background: "rgba(200,145,22,0.14)",
    color: "#c89116",
    fontSize: "13px",
    fontWeight: 900,
    letterSpacing: "1px",
    textTransform: "uppercase",
  },

  tableHeader: {
    display: "grid",
    gridTemplateColumns: "54px 84px minmax(0, 1fr) 84px 60px 58px",
    gap: "14px",
    alignItems: "center",
    justifyItems: "center",
    padding: "14px 24px",
    background: "#f4f3ef",
    color: "#555555",
    fontSize: "10.5px",
    fontWeight: 900,
    letterSpacing: "1.6px",
    textTransform: "uppercase",
    borderBottom: "1px solid rgba(0,0,0,0.08)",
  },

  headerCell: {
    width: "100%",
    textAlign: "center",
    justifySelf: "center",
  },

  headerEntryCell: {
    width: "100%",
    textAlign: "left",
    justifySelf: "start",
    paddingLeft: "62px",
  },

  desktopRowWrap: {
    background: "#ffffff",
    borderBottom: "1px solid rgba(0,0,0,0.08)",
  },

  rows: {
    display: "flex",
    flexDirection: "column",
    background: "#ffffff",
  },

  row: {
    display: "grid",
    gridTemplateColumns: "54px 84px minmax(0, 1fr) 84px 60px 58px",
    gap: "14px",
    alignItems: "center",
    padding: "16px 24px",
    borderBottom: "1px solid rgba(0,0,0,0.08)",
    background: "#ffffff",
    color: "#050505",
    animation: "fadeUp 0.35s ease both",
    transition: "background 180ms ease, box-shadow 180ms ease",
  },

  mobileRow: {
    padding: "16px 18px",
    borderBottom: "1px solid rgba(0,0,0,0.08)",
    background: "#ffffff",
    color: "#050505",
    animation: "fadeUp 0.35s ease both",
    transition: "background 180ms ease, box-shadow 180ms ease",
  },

  mobileRowTop: {
    display: "grid",
    gridTemplateColumns: "42px minmax(0, 1fr) 54px",
    gap: "10px",
    alignItems: "center",
  },

  mobileCompactRow: {
    display: "grid",
    gridTemplateColumns: "34px 42px minmax(0, 1fr) max-content",
    gap: "10px",
    alignItems: "center",
    minWidth: 0,
    maxWidth: "100%",
  },

  mobileMovementWrap: {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    gap: "6px",
    minWidth: 0,
    maxWidth: "100%",
  },

  mobileDetailsToggle: {
    width: "38px",
    height: "34px",
    border: "1px solid rgba(0,0,0,0.08)",
    borderRadius: "14px",
    background: "#fbfaf7",
    color: "#555555",
    fontSize: "18px",
    fontWeight: 900,
    lineHeight: 1,
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "0 0 2px",
    boxShadow: "0 2px 8px rgba(0,0,0,0.04)",
    transition: "background 160ms ease, transform 160ms ease, box-shadow 160ms ease",
  },

  mobileDetailsToggleDark: {
    border: "1px solid rgba(255,255,255,0.12)",
    background: "#151815",
    color: "#fffdf7",
    boxShadow: "0 2px 10px rgba(0,0,0,0.22)",
  },

  mobileExpandedDetails: {
    marginTop: "14px",
    padding: "14px 16px 12px",
    border: "1px solid rgba(0,0,0,0.06)",
    borderRadius: "16px",
    background: "#fbfaf7",
  },

  mobileExpandedDetailsDark: {
    border: "1px solid rgba(255,255,255,0.10)",
    background: "#0f120f",
    color: "#fffdf7",
    boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.02)",
  },

  mobileCountryRow: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    marginBottom: "11px",
    minWidth: 0,
  },

  mobileDetailLabel: {
    fontSize: "9px",
    color: "#777777",
    fontWeight: 900,
    letterSpacing: "1px",
    textTransform: "uppercase",
  },

  mobileDetailValue: {
    marginTop: "3px",
    fontSize: "12px",
    color: "#050505",
    fontWeight: 900,
    overflowWrap: "anywhere",
  },

  mobileRank: {
    fontSize: "28px",
    fontWeight: 950,
    lineHeight: 1,
  },

  mobileEntryMain: {
    minWidth: 0,
    maxWidth: "100%",
  },

  mobileStatsRow: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: "8px",
    marginTop: "12px",
  },

  mobileMiniStat: {
    background: "#f7f7f7",
    border: "1px solid rgba(0,0,0,0.06)",
    borderRadius: "12px",
    padding: "8px 6px",
    minWidth: 0,
    maxWidth: "100%",
    boxSizing: "border-box",
  },

  mobileMiniStatDark: {
    background: "#151815",
    border: "1px solid rgba(255,255,255,0.10)",
    color: "#fffdf7",
  },

  mobileMiniStatLabel: {
    display: "block",
    fontSize: "9px",
    color: "#777777",
    fontWeight: 900,
    letterSpacing: "1px",
    textTransform: "uppercase",
    textAlign: "center",
  },

  mobileMiniStatLabelDark: {
    color: "#c8d0c8",
  },

  mobileMiniStatValue: {
    display: "block",
    marginTop: "4px",
    color: "#050505",
    fontSize: "12px",
    fontWeight: 900,
    textAlign: "center",
    whiteSpace: "normal",
    overflow: "visible",
    textOverflow: "clip",
  },


  mobileMiniStatValueDark: {
    color: "#fffdf7",
  },

  releaseArtwork: {
    position: "relative",
    flexShrink: 0,
    overflow: "hidden",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    border: "1px solid rgba(0,0,0,0.08)",
    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.28), 0 6px 18px rgba(0,0,0,0.10)",
  },

  releaseArtworkImage: {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    display: "block",
  },

  releaseArtworkFallback: {
    color: "#ffffff",
    fontSize: "13px",
    fontWeight: 950,
    letterSpacing: "1px",
    lineHeight: 1,
    textShadow: "0 1px 6px rgba(0,0,0,0.35)",
  },

  desktopDetailsToggle: {
    justifySelf: "center",
    width: "40px",
    height: "36px",
    border: "1px solid rgba(0,0,0,0.08)",
    borderRadius: "14px",
    background: "#fbfaf7",
    color: "#555555",
    fontSize: "18px",
    fontWeight: 900,
    lineHeight: 1,
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "0 0 2px",
    boxShadow: "0 2px 8px rgba(0,0,0,0.04)",
  },

  desktopDetailsToggleDark: {
    border: "1px solid rgba(255,255,255,0.12)",
    background: "#151815",
    color: "#fffdf7",
    boxShadow: "0 2px 10px rgba(0,0,0,0.22)",
  },

  desktopExpandedDetails: {
    margin: "0 24px 16px 176px",
    padding: "14px 16px",
    border: "1px solid rgba(0,0,0,0.06)",
    borderRadius: "16px",
    background: "#fbfaf7",
  },

  desktopExpandedDetailsDark: {
    border: "1px solid rgba(255,255,255,0.10)",
    background: "#0f120f",
    color: "#fffdf7",
    boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.02)",
  },

  desktopDetailsGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
    gap: "10px",
  },

  mobileDetailsGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: "8px",
  },

  detailCard: {
    background: "#f7f7f7",
    border: "1px solid rgba(0,0,0,0.06)",
    borderRadius: "12px",
    padding: "9px 10px",
    minWidth: 0,
    boxSizing: "border-box",
  },

  detailCardDark: {
    background: "#151815",
    border: "1px solid rgba(255,255,255,0.10)",
    color: "#fffdf7",
  },

  platformDetailCardDark: {
    background: "#101310",
    border: "1px solid rgba(255,255,255,0.16)",
    color: "#fffdf7",
  },

  detailCardWide: {
    gridColumn: "1 / -1",
  },

  detailCardLabel: {
    display: "block",
    fontSize: "9px",
    color: "#777777",
    fontWeight: 900,
    letterSpacing: "1px",
    textTransform: "uppercase",
  },

  detailCardLabelDark: {
    color: "#c8d0c8",
  },

  detailCardValue: {
    display: "block",
    marginTop: "4px",
    color: "#050505",
    fontSize: "12px",
    fontWeight: 900,
    lineHeight: 1.28,
    overflowWrap: "anywhere",
  },

  detailCardValueDark: {
    color: "#fffdf7",
  },

  rank: {
    fontSize: "34px",
    fontWeight: 950,
    lineHeight: 1,
    color: "#050505",
  },

  moveBadge: {
    justifySelf: "start",
    minWidth: "52px",
    textAlign: "center",
    borderRadius: "999px",
    padding: "6px 9px",
    fontSize: "12px",
    fontWeight: 950,
  },

  entryCell: {
    display: "flex",
    gap: "12px",
    alignItems: "center",
    minWidth: 0,
  },

  flagBox: {
    width: "50px",
    height: "50px",
    borderRadius: "14px",
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "linear-gradient(135deg, #d4af37 0%, #b88914 100%)",
    border: "1px solid rgba(0,0,0,0.08)",
    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.35), 0 6px 18px rgba(0,0,0,0.12)",
  },

  flagText: {
    color: "#111111",
    fontSize: "13px",
    fontWeight: 900,
    letterSpacing: "1.2px",
    textTransform: "uppercase",
    lineHeight: 1,
  },

  entryText: {
    minWidth: 0,
  },

  artistLinksWrap: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "baseline",
    gap: "0 0",
    minWidth: 0,
    maxWidth: "100%",
    marginTop: "5px",
    lineHeight: 1.25,
  },

  artistSeparator: {
    color: "#777777",
    fontSize: "13px",
    fontWeight: 700,
    margin: "0 4px",
    lineHeight: 1.25,
  },

  artistSeparatorDark: {
    color: "#c8d0c8",
  },

  titleButton: {
    display: "block",
    maxWidth: "100%",
    border: "none",
    background: "transparent",
    color: "#050505",
    padding: 0,
    textAlign: "left",
    fontSize: "16px",
    fontWeight: 950,
    lineHeight: 1.15,
    cursor: "pointer",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },

  titleButtonDark: {
    color: "#FFFFFF",
    WebkitTextFillColor: "#FFFFFF",
  },

  artistButton: {
    display: "inline",
    maxWidth: "100%",
    border: "none",
    background: "transparent",
    color: "#777777",
    padding: 0,
    marginTop: 0,
    textAlign: "left",
    fontSize: "13px",
    fontWeight: 700,
    cursor: "pointer",
    whiteSpace: "normal",
    overflow: "visible",
    textOverflow: "clip",
  },

  artistButtonDark: {
    color: "#c8d0c8",
  },

  metaNumber: {
    color: "#050505",
    fontSize: "15px",
    fontWeight: 900,
    textAlign: "center",
  },

  metaNumberDark: {
    color: "#fffdf7",
  },

  platformCell: {
    justifySelf: "center",
    padding: "6px 9px",
    borderRadius: "999px",
    background: "#f2f2f2",
    color: "#050505",
    fontSize: "12px",
    fontWeight: 900,
  },

  tableFooter: {
    padding: "16px 22px",
    textAlign: "center",
    color: "#777777",
    fontSize: "12px",
    fontWeight: 700,
    background: "#ffffff",
  },


  tableTopActions: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    flexShrink: 0,
    flexWrap: "wrap",
  },

  pillFade: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: "6px",
    width: "30px",
    pointerEvents: "none",
    background: "linear-gradient(90deg, rgba(255,255,255,0) 0%, #ffffff 80%)",
  },

};
