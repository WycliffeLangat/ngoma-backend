import { useState, useEffect, useMemo, useRef } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  LineChart,
  Line,
  Legend,
  PieChart,
  Pie,
  CartesianGrid,
} from "recharts";
import { FULL, MONTHS } from "./data/liveChartData";
import PremiumChartsPage, { getArtistCountry } from "./components/PremiumChartsPage";

import AboutPage from "./pages/AboutPage";
import NewsDetailPage from "./pages/NewsDetailPage";
import NewsPage from "./pages/NewsPage";
import CertificationsPage from "./pages/CertificationsPage";
import YearEndPage from "./pages/YearEndPage";
import RecordsPage from "./pages/RecordsPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import ChartsPage from "./pages/ChartsPage";
import ArtistDetailPage from "./pages/ArtistDetailPage";
import ReleaseDetailPage from "./pages/ReleaseDetailPage";

const PUBLIC_DATA = typeof window !== "undefined" ? (window.__NGOMA_PUBLIC_DATA__ || {}) : {};
const PUBLIC_RELEASES_BY_ID = new Map((PUBLIC_DATA.releases || []).map((release) => [Number(release.id), release]));
const PUBLIC_ARTISTS_BY_NAME = new Map();
(PUBLIC_DATA.artists || []).forEach((artist) => {
  [artist.name, artist.display_name, artist.public_name, ...(artist.aliases || [])].forEach((name) => {
    const key = String(name || "").trim().toLowerCase();
    if (key && !PUBLIC_ARTISTS_BY_NAME.has(key)) PUBLIC_ARTISTS_BY_NAME.set(key, artist);
  });
});
const publicArtistForName = (name = "") => PUBLIC_ARTISTS_BY_NAME.get(String(name || "").trim().toLowerCase()) || null;
const SITE_SETTINGS = PUBLIC_DATA.settings || {};
const settingValue = (key, fallback = {}) => SITE_SETTINGS[key] ?? fallback;
const siteNameSetting = settingValue("site_name", {});
const SITE_NAME = typeof siteNameSetting === "string" ? siteNameSetting : (siteNameSetting.name || "Ngoma Charts");
const THEME_SETTING = settingValue("theme", {});
const SOCIAL_LINKS = settingValue("social_links", {});
const FOOTER_SETTING = settingValue("footer", {});
const DEFAULT_CHART_SETTING = settingValue("default_chart", {});
const MAINTENANCE_SETTING = settingValue("maintenance_mode", {});
const PUBLIC_METHODOLOGY = (PUBLIC_DATA.methodology || [])[0] || null;

// ===== FULL Top-50 dataset across all months and platforms =====
const CURRENT_MONTH = MONTHS[MONTHS.length - 1];
const DATA_PERIOD = `${MONTHS[0]} – ${CURRENT_MONTH}`;
const PUBLIC_PLATFORMS = PUBLIC_DATA.platforms || [];
const platformKeys = (predicate) => PUBLIC_PLATFORMS.filter(predicate).map((item) => item.name.toUpperCase());
const S_PLATS = ["Combined", ...(PUBLIC_PLATFORMS.length ? platformKeys((item) => item.supports_singles) : ["APPLE MUSIC","AUDIOMACK","BOOMPLAY","SPOTIFY","YOUTUBE","SHAZAM"])];
const A_PLATS = ["Combined", ...(PUBLIC_PLATFORMS.length ? platformKeys((item) => item.supports_albums) : ["APPLE MUSIC","AUDIOMACK"])];
const PLAT_LABEL = PUBLIC_PLATFORMS.reduce((result, item) => ({...result, [item.name.toUpperCase()]: item.name}), {"APPLE MUSIC":"Apple Music","AUDIOMACK":"Audiomack","BOOMPLAY":"Boomplay","SPOTIFY":"Spotify","YOUTUBE":"YouTube","SHAZAM":"Shazam"});
const PC = PUBLIC_PLATFORMS.reduce((result, item) => ({...result, [item.name]: item.brand_color || item.color, [item.name.toUpperCase()]: item.brand_color || item.color}), {"Apple Music":"#FC3C44","APPLE MUSIC":"#FC3C44","Audiomack":"#F68B1F","AUDIOMACK":"#F68B1F","Boomplay":"#00FFFF","BOOMPLAY":"#00FFFF","Spotify":"#1DB954","SPOTIFY":"#1DB954","YouTube":"#FF0000","YOUTUBE":"#FF0000","Shazam":"#0088FF","SHAZAM":"#0088FF"});
const GOLD=THEME_SETTING.primary || "#B8860B"; const SILVER="#8C8C8C"; const BRONZE="#CD7F32";
const MEDALS=[GOLD,SILVER,BRONZE];
const F = "'Instrument Sans',Helvetica,sans-serif";
const SF = "'Source Serif 4',Georgia,serif";
const CC = [GOLD,"#E53935","#2DB04A","#1565C0","#7B1FA2","#E65100","#00897B","#37474F","#AD1457","#558B2F"];
const VO = [{l:"Top 10",c:10},{l:"Top 20",c:20},{l:"Top 50",c:50}];
const certificationThresholds = Object.fromEntries((PUBLIC_DATA.certification_rules || []).map((item) => [item.level, Number(item.threshold)]));
const CERTIFICATION_LEVELS = [
  { level: "diamond", label: "Diamond", icon: "💎", pts: certificationThresholds.diamond || 600, color: "#7B1FA2" },
  { level: "platinum", label: "Platinum", icon: "🪙", pts: certificationThresholds.platinum || 400, color: SILVER },
  { level: "gold", label: "Gold", icon: "🥇", pts: certificationThresholds.gold || 200, color: GOLD },
];
const getCertificationLevel = (totalPts = 0) => {
  const points = Number(totalPts) || 0;
  return CERTIFICATION_LEVELS.find((item) => points >= item.pts)?.level || null;
};

const buildCertifications = (items = []) => items
  .map((item) => ({
    t: item.t,
    a: item.a,
    totalPts: Number(item.totalPts) || 0,
    level: getCertificationLevel(item.totalPts),
  }))
  .filter((item) => item.level);
const releaseTitle = (item = {}) => item.t || item.title || item.release_title || item.name || "";
const releaseArtist = (item = {}) => item.artist_credit || item.a || item.artist || item.artist_name || item.primary_artist || "";
const formatCreditMembers = (members = []) => {
  const unique = [...new Map(members
    .map((member) => String(member || "").trim())
    .filter(Boolean)
    .map((member) => [member.toLowerCase(), member])).values()];
  if (unique.length <= 1) return unique[0] || "";
  if (unique.length === 2) return unique.join(" & ");
  return `${unique.slice(0, -1).join(", ")} & ${unique[unique.length - 1]}`;
};
const profileNames = (profiles = []) => profiles
  .map((artist) => artist?.public_name || artist?.display_name || artist?.name || artist)
  .map((name) => String(name || "").trim())
  .filter(Boolean);
const splitCreditNames = (value = "") => String(value || "")
  .split(/\s*,\s*|\s*&\s*|\s+ft\.?\s+|\s+feat\.?\s+|\s+featuring\s+/i)
  .map((name) => name.trim())
  .filter(Boolean);
const artistCreditMembers = (item = {}) => {
  const structuredPrimary = profileNames(item.primary_artists);
  const structuredFeatured = profileNames(item.featured_artist_profiles);
  const primaryArtist = String(item.primary_artist_credit || item.primary_artist || item.pa || "").trim();
  const featuredArtists = String(item.featured_artist_credit || item.featured_artists || item.fa || "").trim();
  const source = structuredPrimary.length || structuredFeatured.length
    ? [...structuredPrimary, ...structuredFeatured]
    : primaryArtist
      ? [...splitCreditNames(primaryArtist), ...splitCreditNames(featuredArtists)]
      : splitCreditNames(item.artist_credit || item.artist || item.a || "");
  return [...new Map(source
    .map((member) => String(member || "").trim())
    .filter(Boolean)
    .map((member) => [member.toLowerCase(), member])).values()];
};
const formatArtistCredit = (primaryArtist = "", featuredArtists = "", primaryArtists = [], featuredProfiles = []) => {
  const primaryNames = profileNames(primaryArtists).length ? profileNames(primaryArtists) : splitCreditNames(primaryArtist);
  const featuredNames = profileNames(featuredProfiles).length ? profileNames(featuredProfiles) : splitCreditNames(featuredArtists);
  const primaryCredit = formatCreditMembers(primaryNames);
  const featuredCredit = formatCreditMembers(featuredNames.filter((name) => !primaryNames.some((primary) => primary.toLowerCase() === name.toLowerCase())));
  return featuredCredit ? `${primaryCredit} ft. ${featuredCredit}` : primaryCredit;
};
const firstFiniteNumber = (...values) => {
  for (const value of values) {
    if (value === undefined || value === null || value === "") continue;
    const parsed = Number(String(value).replace(/,/g, ""));
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
};
const certificationKey = (title = "", artist = "") =>
  `${String(title).trim().toLowerCase()}|||${String(artist).trim().toLowerCase()}`;
const certificationMetaForLevel = (level) => CERTIFICATION_LEVELS.find((item) => item.level === level) || null;
const COUNTRY_ACCENTS = {
  BB:"#00267F",CA:"#D80621",CD:"#007FFF",CI:"#F77F00",CL:"#D52B1E",DE:"#FFCE00",FR:"#0055A4",GB:"#012169",
  GH:"#CE1126",IN:"#FF9933",JM:"#009B3A",KE:"#006600",KR:"#CD2E3A",NG:"#008751",
  NO:"#BA0C2F",PR:"#ED0000",RW:"#00A1DE",SE:"#006AA7",TZ:"#1EB53A",UG:"#D90000",US:"#3C3B6E",ZA:"#007749",ZW:"#319208",
};
const CountryBadge = ({ artist, item, compact = false, style = {} }) => {
  const country = getArtistCountry(item || { artist });
  const accent = COUNTRY_ACCENTS[country.code] || "#69716B";
  return (
    <span
      title={`${country.country}${country.code ? ` (${country.code})` : ""}`}
      style={{
        display:"inline-flex",alignItems:"center",justifyContent:"center",gap:"6px",
        minWidth:compact?"28px":"36px",height:compact?"28px":"30px",padding:"0 7px",
        borderRadius:compact?"9px":"999px",background:`${accent}12`,border:`1px solid ${accent}45`,
        color:accent,fontFamily:F,fontSize:compact?"9px":"10px",fontWeight:850,whiteSpace:"nowrap",...style,
      }}
    >
      <span style={{fontSize:compact?"9px":"10px",letterSpacing:"0.8px",lineHeight:1}}>{country.code || "—"}</span>
    </span>
  );
};
const MONTH_NUMBER = {
  "January": 1,
  "February": 2,
  "March": 3,
  "April": 4,
  "May": 5,
  "June": 6,
  "July": 7,
  "August": 8,
  "September": 9,
  "October": 10,
  "November": 11,
  "December": 12,
};

function getMonthYearParts(label) {
  const [monthName, year] = label.split(" ");
  return {
    monthNumber: MONTH_NUMBER[monthName],
    year,
  };
}

function platformToSlug(platform) {
  if (!platform || platform === "Combined") return "combined";

  return platform
    .toLowerCase()
    .replace(/\s+/g, "-");
}

// Helpers — return entries from FULL with proper month-to-month chart history
const entryKey = e => `${String(e.t || e.title || "").trim().toLowerCase()}|||${String(e.primary_artist || e.a || e.artist || "").trim().toLowerCase()}`;
const sameRelease = (left, right) => entryKey(left) === entryKey(right);
const monthIndex = m => MONTHS.indexOf(m);

const rawCombined = (ct, m) => FULL[ct].combined[m] || [];
const rawPlatform = (ct, pl, m) => ((FULL[ct].platforms[pl] || {})[m] || []);
const combinedEntryCache = new Map();
const platformEntryCache = new Map();
const rawPlatformIndexCache = new Map();

const getRawPlatformIndex = (ct, pl, m) => {
  const cacheKey = `${ct}|${pl}|${m}`;
  if (!rawPlatformIndexCache.has(cacheKey)) {
    const index = new Map();
    rawPlatform(ct, pl, m).forEach((entry) => {
      const key = entryKey(entry);
      if (!index.has(key)) index.set(key, entry);
    });
    rawPlatformIndexCache.set(cacheKey, index);
  }
  return rawPlatformIndexCache.get(cacheKey);
};

function enrichChartEntries(entries, getRawEntries, currentMonth, totalPlatforms) {
  const currentIndex = monthIndex(currentMonth);
  const historyMonths = currentIndex >= 0 ? MONTHS.slice(0, currentIndex + 1) : [];
  const historyByMonth = historyMonths.map((monthLabel) =>
    getRawEntries(monthLabel).filter((item) => Number(item.r) <= 50).slice(0, 50)
  );
  const previousEntries = currentIndex > 0 ? historyByMonth[currentIndex - 1] : [];
  const previousByKey = new Map();
  previousEntries.forEach((item) => {
    const key = entryKey(item);
    if (!previousByKey.has(key)) previousByKey.set(key, item);
  });
  const earlierKeys = new Set();
  const historyStats = new Map();

  historyByMonth.forEach((monthEntries, monthOffset) => {
    const seenThisMonth = new Set();
    monthEntries.forEach((item) => {
      const key = entryKey(item);
      if (monthOffset < currentIndex) earlierKeys.add(key);

      const rank = Number(item.r);
      const stats = historyStats.get(key) || { peakRank: Number.POSITIVE_INFINITY, months: 0 };
      if (Number.isFinite(rank)) stats.peakRank = Math.min(stats.peakRank, rank);
      if (!seenThisMonth.has(key)) {
        stats.months += 1;
        seenThisMonth.add(key);
      }
      historyStats.set(key, stats);
    });
  });

  return entries.map((e) => {
    const key = entryKey(e);
    const previousEntry = previousByKey.get(key);
    const appearedBefore = earlierKeys.has(key);
    const stats = historyStats.get(key) || {};
    const peakRank = stats.peakRank;
    const monthsOnChart = stats.months || 0;

    const platformCount = e.pl
      ? Number(String(e.pl).split("/")[0]) || undefined
      : undefined;

    const releaseDetails = PUBLIC_RELEASES_BY_ID.get(Number(e.release_id)) || {};
    const primaryArtists = e.primary_artists || releaseDetails.primary_artists || [];
    const featuredProfiles = e.featured_artist_profiles || releaseDetails.featured_artist_profiles || [];
    const primaryArtist = String(e.pa || e.a || "").trim();
    const featuredArtists = String(e.fa || "").trim();
    const artistCredit = e.artist_credit || releaseDetails.artist_credit || formatArtistCredit(
      primaryArtist, featuredArtists, primaryArtists, featuredProfiles
    );

    return {
      ...releaseDetails,
      ...e,
      rank: e.r,
      title: e.t,
      artist: artistCredit,
      artist_credit: artistCredit,
      primary_artist: e.primary_artist_credit || releaseDetails.primary_artist_credit || primaryArtist,
      featured_artists: featuredArtists,
      primary_artists: primaryArtists,
      featured_artist_profiles: featuredProfiles,
      pts: e.p,
      rawPts: e.rp ?? null,
      plat: e.pl || (platformCount ? `${platformCount}/${totalPlatforms}` : ""),
      prev: previousEntry ? previousEntry.r : null,
      last_month: previousEntry ? previousEntry.r : "—",
      first: false,
      is_new: !appearedBefore,
      reentry: !previousEntry && appearedBefore,
      movement: previousEntry ? undefined : appearedBefore ? "reentry" : "new",
      peak_rank: peakRank === 999 ? e.r : peakRank,
      weeks_on_chart: e.w ?? "—",
      months_on_chart: monthsOnChart || "—",
      platform_count: platformCount,
      platform_max: e.pl ? Number(String(e.pl).split("/")[1]) || totalPlatforms : totalPlatforms,
      release_year: e.y ?? null,
      confidence: e.c || "",
      country: e.co || "",
      country_code: e.cc || "",
      artist_country: e.co || "",
      artist_country_code: e.cc || "",
    };
  });
}

const getCombined = (ct, m) => {
  const cacheKey = `${ct}|${m}`;
  if (!combinedEntryCache.has(cacheKey)) {
    combinedEntryCache.set(
      cacheKey,
      enrichChartEntries(rawCombined(ct, m), (monthLabel) => rawCombined(ct, monthLabel), m, ct === "albums" ? 2 : 6)
    );
  }
  return combinedEntryCache.get(cacheKey);
};

const getPlatform = (ct, pl, m) => {
  const cacheKey = `${ct}|${pl}|${m}`;
  if (!platformEntryCache.has(cacheKey)) {
    platformEntryCache.set(
      cacheKey,
      enrichChartEntries(rawPlatform(ct, pl, m), (monthLabel) => rawPlatform(ct, pl, monthLabel), m, 1)
    );
  }
  return platformEntryCache.get(cacheKey);
};

const top50Only = (rows = []) => rows.filter((entry) => Number(entry.rank ?? entry.r) <= 50).slice(0, 50);
const artistTop50Points = (entry = {}) => {
  const rank = Number(entry.rank ?? entry.r);
  return Number.isFinite(rank) && rank >= 1 && rank <= 50 ? 51 - rank : 0;
};

const getArtistSourceCombined = (chartType, monthLabel) => {
  if (chartType === "artists") {
    return getArtistPlatformSource("Combined", monthLabel);
  }
  return getCombined(chartType, monthLabel);
};

const defaultComparisonKey = (chartType, index) => {
  const entry = getCombined(chartType, CURRENT_MONTH)[index];
  return entry ? `${entry.title} — ${entry.artist}` : "";
};

const comparisonDefaultKeys = (chartType, throughMonth = CURRENT_MONTH) => {
  const cutoffIndex = Math.max(0, monthIndex(throughMonth));
  const includedMonths = MONTHS.slice(0, cutoffIndex + 1);
  const groups = new Map();

  includedMonths.forEach((monthLabel) => {
    getArtistSourceCombined(chartType, monthLabel).forEach((entry) => {
      const key = `${entry.title} — ${entry.artist}`;
      const current = groups.get(key) || {
        key,
        title: entry.title,
        artist: entry.artist,
        months: new Set(),
        totalPts: 0,
        peak: Number.POSITIVE_INFINITY,
      };
      current.months.add(monthLabel);
      current.totalPts += chartType === "artists" ? artistTop50Points(entry) : Number(entry.pts) || 0;
      current.peak = Math.min(current.peak, Number(entry.rank) || Number.POSITIVE_INFINITY);
      groups.set(key, current);
    });
  });

  return [...groups.values()]
    .sort((a, b) => b.months.size - a.months.size || b.totalPts - a.totalPts || a.peak - b.peak || a.title.localeCompare(b.title))
    .map((entry) => entry.key);
};

const buildCombinedYearEnd = (chartType) => {
  const releases = new Map();

  MONTHS.forEach((monthLabel) => {
    getArtistSourceCombined(chartType, monthLabel).forEach((entry) => {
      const key = entryKey(entry);
      const current = releases.get(key) || {
        t: entry.title,
        a: entry.artist,
        primary_artist: entry.primary_artist,
        featured_artists: entry.featured_artists,
        release_year: entry.release_year,
        confidence: entry.confidence,
        country_code: entry.country_code,
        totalPts: 0,
        months: 0,
        best: Number.POSITIVE_INFINITY,
      };

      current.totalPts += chartType === "artists" ? artistTop50Points(entry) : Number(entry.pts) || 0;
      current.months += 1;
      current.best = Math.min(current.best, Number(entry.rank) || Number.POSITIVE_INFINITY);
      releases.set(key, current);
    });
  });

  return [...releases.values()].sort((a, b) =>
    b.totalPts - a.totalPts || a.best - b.best || a.t.localeCompare(b.t)
  );
};

const combinedArtistsCache = new Map();
const buildCombinedArtists = (chartType, throughMonth = CURRENT_MONTH) => {
  const cacheKey = `${chartType}|${throughMonth}`;
  if (combinedArtistsCache.has(cacheKey)) return combinedArtistsCache.get(cacheKey);

  const cutoffIndex = Math.max(0, monthIndex(throughMonth));
  const includedMonths = MONTHS.slice(0, cutoffIndex + 1);
  const artistMap = new Map();
  const cumulativeTotals = new Map();
  const previousRanks = new Map();

  includedMonths.forEach((monthLabel, monthOffset) => {
    getArtistSourceCombined(chartType, monthLabel).forEach((entry) => {
      artistCreditMembers(entry).forEach((artistName) => {
        const key = artistName.toLowerCase();
        const current = artistMap.get(key) || {
          n: artistName,
          p: 0,
          m: 0,
          t: 0,
          rank: Number.POSITIVE_INFINITY,
          prevRank: null,
          pk: Number.POSITIVE_INFINITY,
          mp: {},
          rh: {},
          months: new Set(),
          titles: new Set(),
        };

        const points = chartType === "artists" ? artistTop50Points(entry) : Number(entry.pts) || 0;
        current.p += points;
        current.mp[monthLabel] = (current.mp[monthLabel] || 0) + points;
        current.months.add(monthLabel);
        current.titles.add(`${entry.sourceChartType || chartType}|${entryKey(entry)}`);
        artistMap.set(key, current);
        cumulativeTotals.set(key, (cumulativeTotals.get(key) || 0) + points);
      });
    });

    [...cumulativeTotals.entries()]
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
      .forEach(([key], index) => {
        const artist = artistMap.get(key);
        if (!artist) return;
        const rank = index + 1;
        artist.rh[monthLabel] = rank;
        artist.pk = Math.min(artist.pk, rank);
        if (monthOffset === includedMonths.length - 2) previousRanks.set(key, rank);
        if (monthOffset === includedMonths.length - 1) artist.rank = rank;
      });
  });

  const result = [...artistMap.entries()]
    .map(([key, { months, titles, ...artist }]) => ({
      ...artist,
      m: months.size,
      t: titles.size,
      prevRank: previousRanks.get(key) || null,
      pk: Number.isFinite(artist.pk) ? artist.pk : "—",
    }))
    .sort((a, b) => a.rank - b.rank || b.p - a.p || a.n.localeCompare(b.n));
  combinedArtistsCache.set(cacheKey, result);
  return result;
};


const ARTIST_PLATS = S_PLATS.filter((platform) => platform !== "Combined");
const artistPlatformSourceCache = new Map();
const artistChartCache = new Map();

const getArtistPlatformSource = (platform = "Combined", monthLabel = CURRENT_MONTH) => {
  const cacheKey = `${platform}|${monthLabel}`;
  if (artistPlatformSourceCache.has(cacheKey)) return artistPlatformSourceCache.get(cacheKey);

  const rows = [];
  const addPlatformTop50 = (chartType, sourcePlatform, releaseType) => {
    top50Only(getPlatform(chartType, sourcePlatform, monthLabel)).forEach((entry) => {
      rows.push({
        ...entry,
        sourceChartType: chartType,
        sourcePlatform,
        type: releaseType,
      });
    });
  };

  if (platform === "Combined") {
    ARTIST_PLATS.forEach((sourcePlatform) => {
      addPlatformTop50("singles", sourcePlatform, "single");
      if (A_PLATS.includes(sourcePlatform)) {
        addPlatformTop50("albums", sourcePlatform, "album");
      }
    });
  } else {
    addPlatformTop50("singles", platform, "single");
    if (A_PLATS.includes(platform)) {
      addPlatformTop50("albums", platform, "album");
    }
  }

  artistPlatformSourceCache.set(cacheKey, rows);
  return rows;
};

const getArtistPlatformHits = (artistName = "", monthLabel = CURRENT_MONTH) => {
  const normalized = String(artistName || "").trim().toLowerCase();
  if (!normalized) return [];
  return ARTIST_PLATS.filter((platform) =>
    getArtistPlatformSource(platform, monthLabel).some((entry) =>
      artistCreditMembers(entry).some((member) => member.toLowerCase() === normalized)
    )
  );
};

const aggregateArtistsForMonth = (monthLabel = CURRENT_MONTH, platform = "Combined") => {
  const artistMap = new Map();

  getArtistPlatformSource(platform, monthLabel).forEach((entry) => {
    artistCreditMembers(entry).forEach((artistName) => {
      const key = artistName.toLowerCase();
      const current = artistMap.get(key) || {
        n: artistName,
        p: 0,
        entries: new Set(),
        releases: [],
        country: getArtistCountry({ artist: artistName }),
      };
      const releaseKey = `${entry.sourceChartType || entry.type || "release"}|${entryKey(entry)}`;
      current.p += artistTop50Points(entry);
      current.entries.add(releaseKey);
      current.releases.push(entry);
      artistMap.set(key, current);
    });
  });

  return [...artistMap.entries()]
    .map(([key, artist]) => ({
      key,
      ...artist,
      entryCount: artist.entries.size,
    }))
    .sort((a, b) => b.p - a.p || b.entryCount - a.entryCount || a.n.localeCompare(b.n));
};

const buildArtistChart = (monthLabel = CURRENT_MONTH, platform = "Combined") => {
  const cacheKey = `${platform}|${monthLabel}`;
  if (artistChartCache.has(cacheKey)) return artistChartCache.get(cacheKey);

  const currentIndex = monthIndex(monthLabel);
  const historyMonths = currentIndex >= 0 ? MONTHS.slice(0, currentIndex + 1) : [];
  const currentRows = aggregateArtistsForMonth(monthLabel, platform);
  const previousMonth = currentIndex > 0 ? MONTHS[currentIndex - 1] : null;
  const previousRows = previousMonth ? aggregateArtistsForMonth(previousMonth, platform) : [];
  const previousRankByKey = new Map(previousRows.map((artist, index) => [artist.key, index + 1]));

  const history = new Map();
  historyMonths.forEach((historyMonth) => {
    aggregateArtistsForMonth(historyMonth, platform).forEach((artist, index) => {
      const stats = history.get(artist.key) || {
        peak: Number.POSITIVE_INFINITY,
        months: 0,
        points: 0,
        name: artist.n,
      };
      stats.peak = Math.min(stats.peak, index + 1);
      stats.months += 1;
      stats.points += Number(artist.p) || 0;
      history.set(artist.key, stats);
    });
  });

  const earlierKeys = new Set();
  historyMonths.slice(0, -1).forEach((historyMonth) => {
    aggregateArtistsForMonth(historyMonth, platform).forEach((artist) => earlierKeys.add(artist.key));
  });

  const result = currentRows.slice(0, 50).map((artist, index) => {
    const rank = index + 1;
    const previousRank = previousRankByKey.get(artist.key) || null;
    const appearedBefore = earlierKeys.has(artist.key);
    const stats = history.get(artist.key) || {};
    const platformHits = platform === "Combined" ? getArtistPlatformHits(artist.n, monthLabel) : [platform];
    const country = artist.country || getArtistCountry({ artist: artist.n });
    const artistProfile = publicArtistForName(artist.n) || {};
    return {
      rank,
      title: artist.n,
      artist: "",
      primary_artist: artist.n,
      featured_artists: "",
      pts: artist.p,
      rawPts: null,
      points_source: "Top 50 platform Singles + Albums",
      plat: platform === "Combined" ? `${platformHits.length}/${ARTIST_PLATS.length}` : "",
      prev: previousRank,
      last_month: previousRank || "—",
      is_new: !appearedBefore,
      reentry: !previousRank && appearedBefore,
      movement: previousRank ? undefined : appearedBefore ? "reentry" : "new",
      peak_rank: Number.isFinite(stats.peak) ? stats.peak : rank,
      weeks_on_chart: "—",
      months_on_chart: stats.months || 1,
      platform_count: platform === "Combined" ? platformHits.length : null,
      platform_max: platform === "Combined" ? ARTIST_PLATS.length : null,
      release_year: null,
      confidence: "",
      country: country.country || "",
      country_code: country.code || "",
      artist_country: country.country || "",
      artist_country_code: country.code || "",
      entries_count: platform === "Combined" ? artist.entryCount : null,
      releases: artist.releases,
      is_artist_entry: true,
      type: "artist",
      artist_profile: artistProfile,
      image: artistProfile.image || "",
      aliases: artistProfile.aliases || [],
      city_region: artistProfile.city_region || "",
      genre: artistProfile.genre || "",
      biography: artistProfile.biography || "",
      artist_type: artistProfile.artist_type || "",
      verified: Boolean(artistProfile.verified),
      social_links: artistProfile.social_links || {},
    };
  });

  artistChartCache.set(cacheKey, result);
  return result;
};

const buildArtistYearEndRows = () => buildCombinedArtists("artists", CURRENT_MONTH).slice(0, 50).map((artist) => {
  const country = getArtistCountry({ artist: artist.n });
  return {
    t: artist.n,
    a: "",
    primary_artist: artist.n,
    totalPts: Number(artist.p) || 0,
    months: artist.m,
    entries: artist.t,
    best: artist.pk,
    country_code: country.code || "",
    country: country.country || "",
    type: "artist",
    is_artist_entry: true,
  };
});

const buildCombinedTrending = (chartType) => {
  const latestMonth = MONTHS[MONTHS.length - 1];
  const previousMonth = MONTHS[MONTHS.length - 2];
  const earlierMonths = MONTHS.slice(0, -2);
  const latestRows = getCombined(chartType, latestMonth);
  const previousRows = getCombined(chartType, previousMonth);
  const previousMap = new Map(previousRows.map((entry) => [entryKey(entry), entry]));
  const earlierMaps = earlierMonths.map((monthLabel) =>
    new Map(getCombined(chartType, monthLabel).map((entry) => [entryKey(entry), entry]))
  );

  const rising = latestRows
    .map((entry) => {
      const key = entryKey(entry);
      const previous = previousMap.get(key);
      if (!previous || Number(previous.rank) <= Number(entry.rank)) return null;

      const earlierRanks = earlierMaps.map((map) => map.get(key)?.rank ?? null);
      const rankTrend = [...earlierRanks, previous.rank, entry.rank];
      const chartedRanks = rankTrend.filter((rank) => Number.isFinite(Number(rank))).map(Number);
      const consecutive = chartedRanks.length >= 3 && chartedRanks.every((rank, index) => index === 0 || rank < chartedRanks[index - 1]);

      return {
        t: entry.title,
        a: entry.artist,
        fromRank: Number(previous.rank),
        decRank: Number(entry.rank),
        places: Number(previous.rank) - Number(entry.rank),
        trend: rankTrend,
        consecutive,
      };
    })
    .filter(Boolean)
    .sort((a, b) => b.places - a.places || Number(b.consecutive) - Number(a.consecutive) || a.decRank - b.decRank)
    .slice(0, 8);

  const previousKeys = new Set([
    ...previousRows.map(entryKey),
    ...earlierMaps.flatMap((map) => [...map.keys()]),
  ]);
  const debuts = latestRows
    .filter((entry) => !previousKeys.has(entryKey(entry)) && Number(entry.rank) <= 15)
    .map((entry) => ({
      t: entry.title,
      a: entry.artist,
      decRank: Number(entry.rank),
      trend: [...earlierMonths.map(() => null), null, Number(entry.rank)],
    }));

  return { rising, debuts };
};

const COMBINED_YEAR_END = {
  singles: buildCombinedYearEnd("singles"),
  albums: buildCombinedYearEnd("albums"),
};
const COMBINED_ARTISTS = {
  singles: buildCombinedArtists("singles"),
  albums: buildCombinedArtists("albums"),
  artists: buildCombinedArtists("artists"),
};
const COMBINED_TRENDING = {
  singles: buildCombinedTrending("singles"),
  albums: buildCombinedTrending("albums"),
};

function AnalyticsDeepSection({ label, isMobile, children }) {
  const [isOpen, setIsOpen] = useState(false);

  if (!isMobile) return <>{children}</>;

  return (
    <details
      className="ngoma-mobile-collapsible"
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
    >
      <summary>{label}<span>View</span></summary>
      {isOpen && <div className="ngoma-mobile-collapsible-body">{children}</div>}
    </details>
  );
}

// Movement badge
const mv = e => {
  const movementType = String(e.movement || e.movement_type || "").toLowerCase();
  if(e.reentry || movementType === "reentry" || movementType === "re-entry" || movementType === "re" || movementType === "r.e") return {t:"reentry"};
  if(e.is_new || movementType === "new") return {t:"new"};
  if(e.prev===null||e.prev===undefined||e.prev==="") return {t:"new"};
  const d=e.prev-e.rank;
  if(d>0) return {t:"up",v:d};
  if(d<0) return {t:"down",v:Math.abs(d)};
  return {t:"same"};
};


const MvBadge=({e})=>{
  const m=mv(e);
  if(m.t==="new")return <span style={{background:"#1A1A1A",color:"#FFF",padding:"1.5px 4px",borderRadius:"2px",fontSize:"7px",letterSpacing:"1px",fontWeight:800}}>NEW</span>;
  if(m.t==="reentry")return <span style={{background:"#1565C0",color:"#FFF",padding:"1.5px 4px",borderRadius:"2px",fontSize:"7px",letterSpacing:"1px",fontWeight:800}}>RE</span>;
  if(m.t==="up")return <span style={{color:"#2DB04A",fontSize:"9px",fontWeight:700}}>{"▲"+m.v}</span>;
  if(m.t==="down")return <span style={{color:"#E53935",fontSize:"9px",fontWeight:700}}>{"▼"+m.v}</span>;
  return <span style={{color:"#DEDEDE",fontSize:"9px"}}>{"—"}</span>;
};

const RecordIcon = ({ label = "", size = 30, muted = false }) => {
  const key = String(label).toLowerCase();
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.8",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    style: { color: muted ? "rgba(184,134,11,0.13)" : GOLD, display: "block" },
  };

  if (key.includes("#1") || key.includes("months at")) {
    return (
      <svg {...common}>
        <path d="M4 18h16" />
        <path d="M5 16 4 7l5 3 3-6 3 6 5-3-1 9H5Z" />
      </svg>
    );
  }

  if (key.includes("score")) {
    return (
      <svg {...common}>
        <path d="M4 19V5" />
        <path d="M4 19h16" />
        <path d="m7 15 3-4 3 2 5-7" />
      </svg>
    );
  }

  if (key.includes("climb")) {
    return (
      <svg {...common}>
        <path d="M4 17 17 4" />
        <path d="M9 4h8v8" />
        <path d="M4 17l4 3 2-5" />
      </svg>
    );
  }

  if (key.includes("coverage")) {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="8" />
        <path d="M4 12h16" />
        <path d="M12 4c2.2 2.3 3.2 5 3.2 8s-1 5.7-3.2 8" />
        <path d="M12 4c-2.2 2.3-3.2 5-3.2 8s1 5.7 3.2 8" />
      </svg>
    );
  }

  if (key.includes("longevity")) {
    return (
      <svg {...common}>
        <path d="M7 4h10" />
        <path d="M7 20h10" />
        <path d="M8 4c0 4 3.2 5.4 4 8-0.8 2.6-4 4-4 8" />
        <path d="M16 4c0 4-3.2 5.4-4 8 0.8 2.6 4 4 4 8" />
      </svg>
    );
  }

  return (
    <svg {...common}>
      <path d="M10 18V6l8-2v10" />
      <circle cx="7" cy="18" r="3" />
      <circle cx="15" cy="14" r="3" />
    </svg>
  );
};

const NEWS=[
  {id:1,date:"June 15, 2026",cat:"CHART NEWS",emoji:"",title:"Finale Leads May After Collaboration Credits Are Unified",excerpt:"Bien & Alikiba's Finale ranks #1 with appearances on five of six tracked singles platforms.",body:"Equivalent Bien, Bien ft. Alikiba and Bien & Alikiba credits are treated as one release. Finale leads Apple Music, Spotify and YouTube for May."},
  {id:2,date:"June 14, 2026",cat:"CHART NEWS",emoji:"",title:"Finale Completes Back-to-Back Months at #1",excerpt:"Bien & Alikiba also lead the recalculated April Combined singles chart.",body:"The collaboration finishes ahead of Siaka and Pawa in April, then retains the summit in May."},
  {id:3,date:"June 13, 2026",cat:"ANALYTICS",emoji:"",title:"Pawa Remains the Period's Highest-Scoring Single",excerpt:"Mbosso's Pawa totals 436 display points across all nine tracked months.",body:"Pawa appeared in every monthly Combined chart and finished #1 in November and December 2025."},
  {id:4,date:"June 12, 2026",cat:"ARTIST SPOTLIGHT",emoji:"",title:`${COMBINED_ARTISTS.singles[0].n} Leads the Singles Artist Ranking`,excerpt:`Top 50 platform entries produce ${COMBINED_ARTISTS.singles[0].p.toLocaleString()} cumulative artist points through May 2026.`,body:"The artist ranking gives points to every named primary and featured artist from Top 50 platform Singles and Albums entries."},
  {id:5,date:"June 11, 2026",cat:"ANALYTICS",emoji:"",title:"Natafuta Doo Makes May's Biggest Singles Jump",excerpt:"ELISHA TOTO climbs twenty-three positions from #40 to #17.",body:"The 23-place gain is the largest positive move among returning singles in May's normalized Combined chart."},
  {id:6,date:"June 10, 2026",cat:"CHART NEWS",emoji:"",title:"Zuchu's I Love You Climbs Eighteen Places",excerpt:"I Love You moves from #36 in April to #18 in May.",body:"The release also leads Boomplay's May chart, giving Zuchu both a strong platform result and a Top 20 Combined finish."},
  {id:7,date:"June 9, 2026",cat:"CHART NEWS",emoji:"",title:"Chai ya saa kumi Surges to #2",excerpt:"Ywaya Tajiri gains seventeen places from April to May.",body:"Chai ya saa kumi rises from #19 to #2 and appears on five of the six tracked singles platforms."},
  {id:8,date:"June 8, 2026",cat:"ANALYTICS",emoji:"",title:"May's Top Five Reflect Broad Platform Reach",excerpt:"Four of the first five singles chart on five platforms, while LAST DANCE reaches four.",body:"Finale, Chai ya saa kumi, AYAYAAH and Siaka each post 5/6 coverage in the latest Combined Top 50."},
  {id:9,date:"June 7, 2026",cat:"PLATFORM WATCH",emoji:"",title:"Finale Leads Three May Platform Charts",excerpt:"Bien & Alikiba finish #1 on Apple Music, Spotify and YouTube.",body:"Audiomack is led by Alikiba & Mbosso's Bhuju, Boomplay by Zuchu's I Love You, and Shazam by Deejay MJ's Well Done."},
  {id:10,date:"June 6, 2026",cat:"ANALYTICS",emoji:"",title:"No May Single Reaches 6/6 Coverage",excerpt:"The latest singles chart peaks at five tracked platforms per release.",body:"The result highlights how differently audiences behave across Apple Music, Audiomack, Boomplay, Spotify, YouTube and Shazam."},
  {id:11,date:"June 5, 2026",cat:"ALBUMS",emoji:"",title:"Asake's M$NEY Debuts at #1",excerpt:"M$NEY leads the May Combined albums chart with full 2/2 coverage.",body:"The album appears on both Apple Music and Audiomack and arrives ahead of Cardi B's AM I THE DRAMA? (Ultimate Edition)."},
  {id:12,date:"June 4, 2026",cat:"ALBUMS",emoji:"",title:"Kehlani Makes May's Biggest Album Leap",excerpt:"Kehlani rises forty-five places from #50 to #5.",body:"No returning song or album makes a larger month-to-month move in the latest Combined rankings."},
  {id:13,date:"June 3, 2026",cat:"ALBUMS",emoji:"",title:"Fally Ipupa's XX Rockets to #4",excerpt:"XX gains thirty-one positions from its April rank of #35.",body:"The climb places Fally Ipupa immediately behind May's Top 3 albums and gives XX full Apple Music and Audiomack coverage."},
  {id:14,date:"June 2, 2026",cat:"ALBUMS",emoji:"",title:"GOLD Climbs Sixteen Places",excerpt:"GOLD moves from #31 in April to #15 in May.",body:"The album records one of May's strongest gains and returns to the upper half of the Combined Top 50."},
  {id:15,date:"June 1, 2026",cat:"ARTIST SPOTLIGHT",emoji:"",title:`${COMBINED_ARTISTS.albums[0].n} Tops the Albums Artist Ranking`,excerpt:`Top 50 album entries total ${COMBINED_ARTISTS.albums[0].p.toLocaleString()} cumulative artist points.`,body:"The albums artist ranking uses primary and featured credits from tracked Top 50 entries."},
  {id:16,date:"May 31, 2026",cat:"ALBUMS",emoji:"",title:"The Last Wun Leads the Nine-Month Albums Ranking",excerpt:"Gunna's album totals 414 display points across all nine months.",body:"The Last Wun finishes ahead of Bien's Alusa Why Are You Topless? and PARTYNEXTDOOR's $ome $exy $ongs 4 U."},
  {id:17,date:"May 30, 2026",cat:"ALBUMS",emoji:"",title:"Sixteen May Top 20 Albums Reach Both Platforms",excerpt:"Most of May's leading albums appear on both Apple Music and Audiomack.",body:"M$NEY, RNB, XX, Kehlani and twelve other Top 20 albums record full 2/2 platform coverage."},
  {id:18,date:"May 29, 2026",cat:"ANALYTICS",emoji:"",title:"Wrong Places Secures Platinum Status",excerpt:"Joshua Baraka & JAE5 total 408 points across nine months.",body:"Wrong Places appears in every tracked month and exceeds the new 400-point Platinum certification threshold."},
];

const NEWS_CATEGORY_LABELS = {
  chart_news:"CHART NEWS",milestones:"MILESTONES",new_releases:"NEW RELEASES",
  industry_news:"INDUSTRY NEWS",artist_news:"ARTIST NEWS",awards:"AWARDS",
  certifications:"CERTIFICATIONS",records:"RECORDS",interviews:"INTERVIEWS",
  editorials:"EDITORIALS",artist_spotlight:"ARTIST SPOTLIGHT",albums:"ALBUMS",
  analytics:"ANALYTICS",announcement:"ANNOUNCEMENT",
};
const mapPublicNews = (items = []) => items.map((n) => ({
  ...n,
  id: n.id,
  date: n.published_at ? new Date(n.published_at).toLocaleDateString("en-US",{year:"numeric",month:"long",day:"numeric"}) : "",
  cat: NEWS_CATEGORY_LABELS[n.category] || (n.category||"").toUpperCase().replace(/_/g," "),
  emoji: n.emoji || "",
  title: n.title || "",
  excerpt: n.excerpt || "",
  body: n.body || "",
}));
const mapPublicCertifications = (items = []) => items.map((c) => ({
  ...c,
  t: c.title || "",
  a: c.artist || "",
  totalPts: Number(c.total_points) || 0,
  level: c.level || getCertificationLevel(c.total_points),
  country_code: c.country_code || "",
  chart_type: c.chart_type || "singles",
})).filter((c) => c.level);

export default function NgomaCharts(){
  const [page,setPage]=useState("charts");
  const [theme,setTheme]=useState(()=>{
    if(typeof window==="undefined") return "light";
    try {
      return window.localStorage.getItem("ngoma-theme")==="dark" ? "dark" : "light";
    } catch {
      return "light";
    }
  });
  const [ct,setCt]=useState(["singles","albums"].includes(DEFAULT_CHART_SETTING.chart_type) ? DEFAULT_CHART_SETTING.chart_type : "singles");
  const [month,setMonth]=useState(MONTHS.includes(DEFAULT_CHART_SETTING.month) ? DEFAULT_CHART_SETTING.month : CURRENT_MONTH);
  const [plat,setPlat]=useState("Combined");
  const [vc,setVc]=useState(10);
  const [hr,setHr]=useState(null);
  const [srch,setSrch]=useState("");
  const [sOpen,setSOpen]=useState(false);
  const [mNav,setMNav]=useState(false);
  const [moreOpen,setMoreOpen]=useState(false);
  const [selA,setSelA]=useState(null);
  const [selR,setSelR]=useState(null);
  const [selNews,setSelNews]=useState(null);
  const [cmpA1,setCmpA1]=useState("");
  const [cmpA2,setCmpA2]=useState("");
  const [cmpS1,setCmpS1]=useState(() => comparisonDefaultKeys("singles", CURRENT_MONTH)[0] || defaultComparisonKey("singles", 0));
  const [cmpS2,setCmpS2]=useState(() => comparisonDefaultKeys("singles", CURRENT_MONTH)[1] || defaultComparisonKey("singles", 1));
  const [anMonth,setAnMonth]=useState(CURRENT_MONTH);
  const [artistMonth,setArtistMonth]=useState(CURRENT_MONTH);
  const [rankJourneyView,setRankJourneyView]=useState("table");
  const [viewModes,setViewModes]=useState({});
  const [loaded,setLd]=useState(false);
  // Live backend (optional) — falls back to baked-in data if unreachable
  const API_BASE = (import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_BASE || "/api/v1").replace(/\/$/, "");
  const [liveStatus, setLiveStatus] = useState("static"); // "static" | "live" | "checking"
  const [liveChartEntries, setLiveChartEntries] = useState([]);
  const [liveChartMeta, setLiveChartMeta] = useState(null);
  const [liveChartLoading, setLiveChartLoading] = useState(false);
  const [liveNews, setLiveNews] = useState(() => PUBLIC_DATA.news?.length ? mapPublicNews(PUBLIC_DATA.news) : null);
  const [liveCerts, setLiveCerts] = useState(() => PUBLIC_DATA.certifications?.length ? mapPublicCertifications(PUBLIC_DATA.certifications) : null);
  const [openRecord, setOpenRecord] = useState(null);
  const [expandedYearEndRows, setExpandedYearEndRows] = useState({});
  const [expandedArtistRows, setExpandedArtistRows] = useState({});
  const [expandedTrendingRows, setExpandedTrendingRows] = useState({});
  const detailOpenRef = useRef(false);
  const detailReturnScrollRef = useRef(0);
  const isDark = theme === "dark";
  const themeColors = isDark
    ? {
        page: "#050505",
        surface: "#0F1110",
        elevated: "#151815",
        text: "#F6F3EA",
        muted: "#B8BDB8",
        border: "#2B302B",
        active: "rgba(184,134,11,0.22)",
        hover: "#1A1F1A",
      }
    : {
        page: THEME_SETTING.background || "#FFFFFF",
        surface: THEME_SETTING.cards || "#FFFFFF",
        elevated: THEME_SETTING.cards || "#FFFFFF",
        text: "#1A1A1A",
        muted: "#6B6B6B",
        border: "#E5E0D4",
        active: "#F1E3BF",
        hover: "#FAF5EA",
      };

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.title = SITE_NAME;
    document.documentElement.dataset.ngomaTheme = theme;
    document.body.dataset.ngomaTheme = theme;
    try {
      if (typeof window !== "undefined") window.localStorage.setItem("ngoma-theme", theme);
    } catch {
      // Theme still works for the current session if storage is unavailable.
    }
  }, [theme]);

  const toggleYearEndRow = (rowKey) => {
    setExpandedYearEndRows((current) => ({
      ...current,
      [rowKey]: !current[rowKey],
    }));
  };

  const toggleArtistRow = (rowKey) => {
    setExpandedArtistRows((current) => (current[rowKey] ? {} : { [rowKey]: true }));
  };

  const toggleTrendingRow = (rowKey) => {
    setExpandedTrendingRows((current) => ({
      ...current,
      [rowKey]: !current[rowKey],
    }));
  };

  const isArtists = ct === "artists";
  const isSingles = ct === "singles";
  const isAlbums = ct === "albums";
  const releaseCt = isAlbums ? "albums" : "singles";
  const platList = isArtists ? S_PLATS : (isSingles ? S_PLATS : A_PLATS);
  const tp = isArtists ? ARTIST_PLATS.length : (isSingles ? 6 : 2);

  useEffect(() => {
    if (!API_BASE) return;

    setLiveStatus("checking");

    fetch(API_BASE + "/charts/latest/?chart_type=singles&platform=combined")
      .then((response) => (response.ok ? response.json() : Promise.reject()))
      .then(() => setLiveStatus("live"))
      .catch(() => setLiveStatus("static"));
  }, [API_BASE]);

  useEffect(() => {
    if (!API_BASE) return;
    fetch(API_BASE + "/news/?page_size=100", { cache:"no-store" })
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((data) => {
        const items = Array.isArray(data) ? data : (data.results || []);
        setLiveNews(mapPublicNews(items));
      })
      .catch(() => setLiveNews(null));
  }, [API_BASE]);

  useEffect(() => {
    if (!API_BASE) return;
    fetch(API_BASE + "/certifications/?page_size=200", { cache:"no-store" })
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((data) => {
        const items = Array.isArray(data) ? data : (data.results || []);
        setLiveCerts(mapPublicCertifications(items));
      })
      .catch(() => setLiveCerts(null));
  }, [API_BASE]);

  useEffect(() => {
    setLiveChartEntries([]);
    setLiveChartMeta(null);

    if (isArtists) return;
    if (!API_BASE) return;

    const { monthNumber, year } = getMonthYearParts(month);

    if (!monthNumber || !year) return;

    const controller = new AbortController();

    const params = new URLSearchParams();
    params.set("type", releaseCt);
    params.set("month", String(monthNumber));
    params.set("year", String(year));
    params.set("platform", platformToSlug(plat));

    setLiveChartLoading(true);

    fetch(`${API_BASE}/export/chart-image-data/?${params.toString()}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("Live chart unavailable");
        return response.json();
      })
      .then((chartData) => {
        const entries = (chartData.entries || []).map((entry) => {
          const movementType = String(entry.movement || "").toLowerCase();

          const displayPoints = entry.total_points || 0;

          return {
            ...entry,
            rank: entry.rank,
            title: entry.title,
            artist: entry.artist_credit || formatArtistCredit(entry.primary_artist || entry.artist, entry.featured_artists, entry.primary_artists, entry.featured_artist_profiles),
            artist_credit: entry.artist_credit || formatArtistCredit(entry.primary_artist || entry.artist, entry.featured_artists, entry.primary_artists, entry.featured_artist_profiles),
            primary_artist: entry.primary_artist_credit || entry.primary_artist || entry.artist,
            featured_artists: entry.featured_artists || "",
            pts: displayPoints,
            rawPts: null,
            plat: entry.platform_count ? `${entry.platform_count}/${entry.platform_max || tp}` : "",
            prev: entry.prev_rank,
            first: false,
            is_new: movementType === "new",
            reentry: movementType === "reentry" || movementType === "re-entry" || movementType === "re",
            movement: entry.movement,
            last_month:
              entry.last_month !== null && entry.last_month !== undefined && entry.last_month !== ""
                ? entry.last_month
                : entry.prev_rank ?? "—",
            peak_rank: entry.peak_rank,
            weeks_on_chart: entry.weeks_on_chart,
            platform_count: entry.platform_count,
            platform_max: entry.platform_max,
            release_year: entry.release_year,
            confidence: entry.confidence,
            country: entry.artist_country || entry.country || "",
            country_code: entry.artist_country_code || entry.country_code || "",
            artist_country: entry.artist_country || entry.country || "",
            artist_country_code: entry.artist_country_code || entry.country_code || "",
          };
        });

        setLiveChartEntries(entries);
        setLiveChartMeta(chartData);
        setLiveStatus("live");
      })
      .catch((error) => {
        if (error.name === "AbortError") return;
        setLiveChartEntries([]);
        setLiveChartMeta(null);
        setLiveStatus("static");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLiveChartLoading(false);
      });

    return () => controller.abort();
  }, [API_BASE, releaseCt, month, plat, tp, isArtists]);
  useEffect(()=>{setTimeout(()=>setLd(true),100);},[]);

  const [vw,setVw]=useState(typeof window!=="undefined"?window.innerWidth:1200);
  useEffect(()=>{const h=()=>setVw(window.innerWidth);window.addEventListener("resize",h);return()=>window.removeEventListener("resize",h);},[]);
  const isMobile=vw<640;
  const PAD=isMobile?"clamp(20px, 5vw, 28px)":"28px";
  const PAGE_MAX="1240px";
  const pageFrame=(extra={})=>({maxWidth:PAGE_MAX,width:"100%",margin:"0 auto",boxSizing:"border-box",minWidth:0,...extra});
  const responsiveStack=(desktop="row")=>({flexDirection:isMobile?"column":desktop,alignItems:isMobile?"stretch":"center"});
  useEffect(()=>{const h=e=>{if(e.key==="Escape"){setSOpen(false);setSrch("");}};window.addEventListener("keydown",h);return()=>window.removeEventListener("keydown",h);},[]);
  useEffect(() => {
    detailOpenRef.current = Boolean(selA || selR);
  }, [selA, selR]);
  useEffect(() => {
    const handlePopState = () => {
      if (!detailOpenRef.current) return;
      detailOpenRef.current = false;
      setSelA(null);
      setSelR(null);
      requestAnimationFrame(() => window.scrollTo({ top: detailReturnScrollRef.current, behavior: "auto" }));
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

const getData = () => {
  if (isArtists) return buildArtistChart(month, plat);
  return plat === "Combined" ? getCombined(releaseCt, month) : getPlatform(releaseCt, plat, month);
};

const staticData = getData();

const sourceData = liveChartEntries.length ? liveChartEntries : staticData;
const data = sourceData.filter((entry) => Number(entry.rank) <= 50).slice(0, 50);

const display = data.slice(0, Math.min(vc, data.length));

const top = data[0];

  const themeToggle = (extra={}) => {
    const { hideDot = false, ...extraStyle } = extra;
    return (
    <button
      type="button"
      onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
      aria-label={`Switch to ${isDark ? "light" : "dark"} mode`}
      title={`Switch to ${isDark ? "light" : "dark"} mode`}
      className="ngoma-theme-toggle"
      style={{
        display:"inline-flex",
        alignItems:"center",
        justifyContent:"center",
        gap:"7px",
        minHeight:isMobile?"38px":"30px",
        padding:isMobile?"0 12px":"6px 11px",
        border:`1px solid ${themeColors.border}`,
        borderRadius:"999px",
        background:themeColors.elevated,
        color:themeColors.text,
        fontFamily:F,
        fontSize:isMobile?"10px":"10px",
        fontWeight:850,
        letterSpacing:"1px",
        textTransform:"uppercase",
        cursor:"pointer",
        whiteSpace:"nowrap",
        boxShadow:isDark?"0 0 0 1px rgba(255,255,255,0.02)":"0 4px 14px rgba(0,0,0,0.035)",
        ...extraStyle,
      }}
    >
      {!hideDot && <span
        aria-hidden="true"
        style={{
          width:"8px",
          height:"8px",
          borderRadius:"50%",
          background:isDark?"#F6F3EA":"#1A1A1A",
          boxShadow:`0 0 0 3px ${isDark?"rgba(246,243,234,0.10)":"rgba(26,26,26,0.08)"}`,
          flexShrink:0,
        }}
      />}
      {isDark ? "Light" : "Dark"}
    </button>
    );
  };

  // ALL data flattened for search
  const allEntries=useMemo(()=>{
    const out=[];
    MONTHS.forEach(m=>{
      getCombined("singles",m).forEach(e=>out.push({...e,type:"single",month:m}));
      getCombined("albums",m).forEach(e=>out.push({...e,type:"album",month:m}));
    });
    return out;
  },[]);
  const sRes=srch.length>1?[...new Map(allEntries.filter(e=>
    e.title.toLowerCase().includes(srch.toLowerCase())||e.artist.toLowerCase().includes(srch.toLowerCase())
  ).map(e=>[e.type+e.title+e.artist+e.month,e])).values()].slice(0,16):[];

  // Every credited artist receives the release's full chart contribution from Top 50 source rows.
  const artistCutoffMonth = page === "analytics" ? anMonth : artistMonth;
  const artists = buildCombinedArtists(ct, artistCutoffMonth);
  useEffect(() => {
    if (!artists.length) return;
    const defaults = [...artists].sort((a, b) => b.m - a.m || b.p - a.p || a.rank - b.rank || a.n.localeCompare(b.n));
    const first = artists.some((item) => item.n === cmpA1) ? cmpA1 : defaults[0]?.n;
    const second = artists.some((item) => item.n === cmpA2) && cmpA2 !== first ? cmpA2 : (defaults.find((item) => item.n !== first) || defaults[0])?.n;
    if (first && first !== cmpA1) setCmpA1(first);
    if (second && second !== cmpA2) setCmpA2(second);
  }, [ct, artistCutoffMonth, artists, cmpA1, cmpA2]);
  const prepareDetailNavigation = () => {
    if (!detailOpenRef.current) {
      detailReturnScrollRef.current = window.scrollY || 0;
      window.history.pushState({ ...(window.history.state || {}), ngomaDetail: true }, "");
      detailOpenRef.current = true;
    }
    requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "auto" }));
  };
  const closeDetails = () => {
    if (window.history.state?.ngomaDetail) {
      window.history.back();
      return;
    }
    detailOpenRef.current = false;
    setSelA(null);
    setSelR(null);
    requestAnimationFrame(() => window.scrollTo({ top: detailReturnScrollRef.current, behavior: "auto" }));
  };
  const openArtistDetails = (name) => {
    const requestedName = String(name || "").trim();
    const allCurrentArtists = [...COMBINED_ARTISTS.singles, ...COMBINED_ARTISTS.albums];
    const resolvedName = allCurrentArtists.find((item) => item.n.toLowerCase() === requestedName.toLowerCase())?.n
      || artistCreditMembers({ artist: requestedName })[0]
      || requestedName;
    const singleProfile = buildCombinedArtists("singles", CURRENT_MONTH).find((item) => item.n === resolvedName);
    const albumProfile = buildCombinedArtists("albums", CURRENT_MONTH).find((item) => item.n === resolvedName);
    const profile = (isSingles ? singleProfile : albumProfile) || singleProfile || albumProfile;
    if (!profile) return;
    setCt(singleProfile === profile ? "singles" : "albums");
    setPlat("Combined");
    setSelR(null);
    setSelA(profile);
    prepareDetailNavigation();
  };
  const openReleaseDetails = (entry = {}, type = isSingles ? "single" : "album") => {
    if (entry?.is_artist_entry || String(type || entry.type || "").toLowerCase().includes("artist")) {
      openArtistDetails(entry.title || entry.primary_artist || entry.artist || entry.n);
      return;
    }
    const normalizedType = String(type || entry.type || "single").toLowerCase().includes("album") ? "album" : "single";
    const displayArtist = releaseArtist(entry);
    const primaryArtist = entry.primary_artist || entry.pa || artistCreditMembers({ artist: displayArtist })[0] || displayArtist;
    setCt(normalizedType === "album" ? "albums" : "singles");
    setPlat("Combined");
    setSelA(null);
    setSelR({
      ...entry,
      title: releaseTitle(entry),
      artist: displayArtist,
      primary_artist: primaryArtist,
      type: normalizedType,
    });
    prepareDetailNavigation();
  };
  const artistTrendFor=(artist={})=>{
    if(!artist.prevRank) return {symbol:"NEW",color:"#1565C0",label:"New",shortLabel:"New"};
    const delta=Number(artist.prevRank)-Number(artist.rank);
    if(delta>0) return {symbol:"↑",color:"#2DB04A",label:`Up ${delta}`,shortLabel:"Up"};
    if(delta<0) return {symbol:"↓",color:"#C0392B",label:`Down ${Math.abs(delta)}`,shortLabel:"Down"};
    return {symbol:"–",color:"#9AA19A",label:"No change",shortLabel:"No change"};
  };

  const chartTypeLabel = isArtists ? "Artists" : (isSingles ? "Singles" : "Albums");
  const releaseLabel = isArtists ? "Artists" : (isSingles ? "Songs" : "Albums");
  const releaseLabelLower = isArtists ? "artists" : (isSingles ? "songs" : "albums");
  const releaseSingularLower = isArtists ? "artist" : (isSingles ? "song" : "album");
  const platformKeysFor = (chartType = releaseCt) => chartType === "artists" ? ARTIST_PLATS : (chartType === "singles" ? S_PLATS : A_PLATS).filter((platform) => platform !== "Combined");
  const currentPlatformKeys = platformKeysFor(ct);
  const analyticsRowsFor = (targetMonth, targetPlatform = "Combined") => isArtists
    ? buildArtistChart(targetMonth, targetPlatform)
    : (targetPlatform === "Combined" ? getCombined(releaseCt, targetMonth) : getPlatform(releaseCt, targetPlatform, targetMonth));
  const analyticsActive = page === "analytics";
  const analysisMonths = analyticsActive ? MONTHS.slice(0, Math.max(0, monthIndex(anMonth)) + 1) : MONTHS;
  const recordsActive = page === "records";
  const recordsCoverageTargetFor = (chartType = releaseCt) => chartType === "artists" ? ARTIST_PLATS.length : (chartType === "albums" ? 2 : platformKeysFor(chartType).length);
  const currentRecordsCoverageTarget = recordsCoverageTargetFor(ct);

  const platformHitsFor = (chartType, targetMonth, title, artist) => {
    if (chartType === "artists") {
      const artistName = title || artist;
      return platformKeysFor("artists").filter((platform) =>
        buildArtistChart(targetMonth, platform).some((entry) => String(entry.title || "").toLowerCase() === String(artistName || "").toLowerCase())
      );
    }
    return platformKeysFor(chartType).filter((platform) =>
      getRawPlatformIndex(chartType, platform, targetMonth).has(entryKey({ title, artist }))
    );
  };

  const crossPlatformRows = analyticsActive ? analyticsRowsFor(anMonth)
    .map((entry) => {
      const hits = platformHitsFor(ct, anMonth, entry.title, entry.primary_artist || entry.artist);
      const fallbackCount = Number(String(entry.plat || "").split("/")[0]) || 0;
      const fallbackHits = hits.length ? hits : currentPlatformKeys.slice(0, fallbackCount);
      const count = fallbackHits.length || fallbackCount;
      return {
        ...entry,
        t: entry.title,
        a: entry.artist,
        plats: fallbackHits,
        count,
      };
    })
    .filter((entry) => entry.count > 0)
    .sort((a, b) => b.count - a.count || Number(b.pts || 0) - Number(a.pts || 0)) : [];

  const coverageBucket = crossPlatformRows.reduce((acc, entry) => {
    acc[entry.count] = (acc[entry.count] || 0) + 1;
    return acc;
  }, {});

  const coverageData = Object.entries(coverageBucket)
    .map(([count, value]) => ({ name: `${count} platform${Number(count) === 1 ? "" : "s"}`, value, count: Number(count) }))
    .sort((a, b) => b.count - a.count);

  const platOnes = analyticsActive ? currentPlatformKeys
    .map((platform) => {
      if (isArtists) {
        const entry = buildArtistChart(anMonth, platform)[0];
        return entry ? [platform, { t: entry.title, a: entry.artist, primary_artist: entry.primary_artist, featured_artists: "", p: entry.pts, is_artist_entry: true, type: "artist" }] : null;
      }
      const entry = rawPlatform(releaseCt, platform, anMonth)[0];
      return entry ? [platform, { t: entry.t, a: entry.artist_credit || formatArtistCredit(entry.a, entry.fa, entry.primary_artists, entry.featured_artist_profiles), primary_artist: entry.primary_artist_credit || entry.a, featured_artists: entry.fa || "", p: entry.p }] : null;
    })
    .filter(Boolean) : [];

  const platTotalsData = analyticsActive ? currentPlatformKeys
    .map((platform) => {
      const entries = isArtists
        ? buildArtistChart(anMonth, platform).length
        : (() => {
            const platformIndex = getRawPlatformIndex(releaseCt, platform, anMonth);
            return getCombined(releaseCt, anMonth).filter((entry) => platformIndex.has(entryKey(entry))).length;
          })();
      return {
        platform: PLAT_LABEL[platform] || platform,
        entries,
        color: PC[platform] || "#888",
      };
    })
    .filter((entry) => entry.entries > 0) : [];

  const uniquePlatformData = analyticsActive ? (() => {
    const top50RowsByPlatform = new Map(
      currentPlatformKeys.map((platform) => [
        platform,
        isArtists
          ? buildArtistChart(anMonth, platform).slice(0, 50).map((entry) => ({ ...entry, t: entry.title, a: entry.primary_artist || entry.title, p: entry.pts, r: entry.rank }))
          : rawPlatform(releaseCt, platform, anMonth)
              .filter((entry) => Number(entry.r) <= 50)
              .slice(0, 50),
      ])
    );
    const top50IndexesByPlatform = new Map(
      currentPlatformKeys.map((platform) => {
        const index = new Map();
        (top50RowsByPlatform.get(platform) || []).forEach((entry) => {
          const key = entryKey(entry);
          if (!index.has(key)) index.set(key, entry);
        });
        return [platform, index];
      })
    );

    return currentPlatformKeys.map((platform) => {
      const otherIndexes = currentPlatformKeys
        .filter((item) => item !== platform)
        .map((item) => top50IndexesByPlatform.get(item));
      const uniqueEntries = (top50RowsByPlatform.get(platform) || [])
        .filter((entry) => !otherIndexes.some((index) => index?.has(entryKey(entry))))
        .map((entry) => ({
          title: entry.t || entry.title,
          artist: isArtists ? (entry.artist || "") : (entry.artist_credit || formatArtistCredit(entry.a, entry.fa, entry.primary_artists, entry.featured_artist_profiles)),
          primary_artist: entry.a || entry.primary_artist || entry.t || entry.title,
          featured_artists: entry.fa || entry.featured_artists || "",
          rank: entry.r || entry.rank,
          pts: entry.p || entry.pts,
        }));
      return {
        platform,
        label: PLAT_LABEL[platform] || platform,
        count: uniqueEntries.length,
        color: PC[platform] || "#888",
        entries: uniqueEntries.slice(0, 6),
      };
    });
  })() : [];

  const topCountryData = analyticsActive ? (() => {
    const countryMap = new Map();
    analyticsRowsFor(anMonth).forEach((entry) => {
      const country = getArtistCountry(entry);
      const code = country.code || "—";
      const current = countryMap.get(code) || {
        code,
        country: country.country || code,
        entries: 0,
        points: 0,
        color: COUNTRY_ACCENTS[code] || GOLD,
      };
      current.entries += 1;
      current.points += Number(entry.pts) || 0;
      countryMap.set(code, current);
    });
    return [...countryMap.values()]
      .sort((a, b) => b.entries - a.entries || b.points - a.points || a.code.localeCompare(b.code))
      .slice(0, 5);
  })() : [];

  const featureAnalytics = analyticsActive ? (() => {
    const releaseMap = new Map();
    const artistMap = new Map();
    const monthly = analysisMonths.map((monthLabel) => {
      let entries = 0;
      let points = 0;
      analyticsRowsFor(monthLabel).forEach((entry) => {
        const featuredArtists = isArtists ? [] : String(entry.featured_artists || entry.fa || "").split(/\s*,\s*|\s*&\s*/).map((item) => item.trim()).filter(Boolean);
        if (!featuredArtists.length) return;
        entries += 1;
        points += Number(entry.pts) || 0;
        const key = entryKey(entry);
        const release = releaseMap.get(key) || {
          title: entry.title,
          artist: entry.artist,
          primary_artist: entry.primary_artist,
          featured_artists: entry.featured_artists,
          entries: 0,
          points: 0,
          peak: Number.POSITIVE_INFINITY,
          months: new Set(),
        };
        release.entries += 1;
        release.points += Number(entry.pts) || 0;
        release.peak = Math.min(release.peak, Number(entry.rank) || Number.POSITIVE_INFINITY);
        release.months.add(monthLabel);
        releaseMap.set(key, release);
        featuredArtists.forEach((artistName) => {
          const artistKey = artistName.toLowerCase();
          const artist = artistMap.get(artistKey) || { name: artistName, points: 0, credits: 0, releases: new Set() };
          artist.points += Number(entry.pts) || 0;
          artist.credits += 1;
          artist.releases.add(key);
          artistMap.set(artistKey, artist);
        });
      });
      return { month: monthLabel.split(" ")[0].slice(0, 3), entries, points };
    });
    return {
      monthly,
      releases: [...releaseMap.values()]
        .map((item) => ({ ...item, months: item.months.size, peak: Number.isFinite(item.peak) ? item.peak : null }))
        .sort((a, b) => b.points - a.points || a.peak - b.peak)
        .slice(0, 8),
      artists: [...artistMap.values()]
        .map((item) => ({ ...item, releases: item.releases.size }))
        .sort((a, b) => b.points - a.points || b.credits - a.credits || a.name.localeCompare(b.name))
        .slice(0, 8),
    };
  })() : { monthly: [], releases: [], artists: [] };

  const buildMovementData = (chartType, targetMonth) => {
    const currentIndex = monthIndex(targetMonth);
    const currentRows = chartType === "artists" ? buildArtistChart(targetMonth, "Combined") : getCombined(chartType, targetMonth);
    const previousMonth = currentIndex > 0 ? MONTHS[currentIndex - 1] : null;
    const previousRows = previousMonth ? (chartType === "artists" ? buildArtistChart(previousMonth, "Combined") : getCombined(chartType, previousMonth)) : [];

    const moves = currentRows
      .map((entry) => {
        const previous = previousRows.find((item) => entryKey(item) === entryKey(entry));
        if (!previous) return null;
        const from = Number(previous.rank);
        const to = Number(entry.rank);
        if (!Number.isFinite(from) || !Number.isFinite(to) || from === to) return null;
        return { t: entry.title, a: entry.artist, from, to, delta: from - to };
      })
      .filter(Boolean);

    return {
      new: currentRows.filter((entry) => entry.is_new).length,
      ret: currentRows.filter((entry) => entry.reentry).length,
      debut: currentRows.filter((entry) => entry.is_new).length,
      risers: moves.filter((entry) => entry.delta > 0).sort((a, b) => b.delta - a.delta).slice(0, 5),
      fallers: moves.filter((entry) => entry.delta < 0).sort((a, b) => a.delta - b.delta).slice(0, 5),
    };
  };

  // Movement data for the current analytics month and selected chart type
  const mvData = analyticsActive
    ? buildMovementData(ct, anMonth)
    : { new: 0, ret: 0, debut: 0, risers: [], fallers: [] };

  const num = (value) => {
    const parsed = Number(String(value ?? 0).replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : 0;
  };

  const trackedPeriodLabel = "across all tracked months";
  const monthCountLabel = `${MONTHS.length} ${MONTHS.length === 1 ? "month" : "months"}`;

  const releaseGroupsFor = (chartType) => {
    const groups = new Map();
    MONTHS.forEach((m) => {
      (chartType === "artists" ? buildArtistChart(m, "Combined") : getCombined(chartType, m)).forEach((entry) => {
        const key = entryKey(entry);
        if (!groups.has(key)) {
          groups.set(key, {
            key,
            title: entry.title,
            artist: entry.artist,
            totalPoints: 0,
            months: new Set(),
            numberOneMonths: new Set(),
            rows: [],
            fullCoverageMonths: new Set(),
          });
        }

        const group = groups.get(key);
        const points = num(entry.pts);
        const rank = num(entry.rank);
        const hits = platformHitsFor(chartType, m, entry.title, entry.primary_artist || entry.artist);
        const fallbackCount = num(entry.platform_count) || num(String(entry.plat || "").split("/")[0]);
        const platformCount = Math.max(hits.length, fallbackCount);

        group.totalPoints += points;
        group.months.add(m);
        group.rows.push({ ...entry, month: m, points, rank, platformCount });
        if (rank === 1) group.numberOneMonths.add(m);
        if (platformCount >= recordsCoverageTargetFor(chartType)) group.fullCoverageMonths.add(m);
      });
    });
    return [...groups.values()];
  };

  const biggestClimbFor = (chartType) => {
    let best = null;
    MONTHS.forEach((m, index) => {
      if (index === 0) return;
      const previousMonth = MONTHS[index - 1];
      const previousRows = getCombined(chartType, previousMonth);
      getCombined(chartType, m).forEach((entry) => {
        const previous = previousRows.find((item) => entryKey(item) === entryKey(entry));
        if (!previous) return;
        const from = num(previous.rank);
        const to = num(entry.rank);
        const delta = from - to;
        if (delta > 0 && (!best || delta > best.delta)) {
          best = { ...entry, from, to, delta, month: m };
        }
      });
    });
    return best;
  };

  const currentRecords = recordsActive ? (() => {
    if (isArtists) {
      const highestPoints = artists[0];
      const mostMonths = [...artists].sort((a, b) => (b.m || 0) - (a.m || 0) || (b.p || 0) - (a.p || 0))[0];
      const mostEntries = [...artists].sort((a, b) => (b.t || 0) - (a.t || 0) || (b.p || 0) - (a.p || 0))[0];
      const bestPeak = [...artists].sort((a, b) => Number(a.pk || 999) - Number(b.pk || 999) || (b.p || 0) - (a.p || 0))[0];
      const biggestClimb = [...artists]
        .map((artist) => ({ ...artist, delta: artist.prevRank ? Number(artist.prevRank) - Number(artist.rank) : 0 }))
        .filter((artist) => artist.delta > 0)
        .sort((a, b) => b.delta - a.delta || (b.p || 0) - (a.p || 0))[0];
      return [
        { label: "Highest Artist Points", displayLabel: "Highest Artist Points", value: highestPoints?.n || "—", displaySub: highestPoints ? `${Number(highestPoints.p || 0).toLocaleString()} pts · #${highestPoints.rank}` : "No artist data found" },
        { label: "Most Months Active", displayLabel: "Most Months Active", value: mostMonths?.n || "—", displaySub: mostMonths ? `${mostMonths.m} ${mostMonths.m === 1 ? "month" : "months"} active` : "No artist data found" },
        { label: "Most Chart Entries", displayLabel: "Most Chart Entries", value: mostEntries?.n || "—", displaySub: mostEntries ? `${mostEntries.t} ${mostEntries.t === 1 ? "entry" : "entries"}` : "No artist data found" },
        { label: "Best Artist Rank", displayLabel: "Best Artist Rank", value: bestPeak?.n || "—", displaySub: bestPeak ? `Peak artist rank #${bestPeak.pk}` : "No artist data found" },
        { label: "Biggest Artist Climb", displayLabel: "Biggest Artist Climb", value: biggestClimb?.n || "—", displaySub: biggestClimb ? `Up ${biggestClimb.delta} places to #${biggestClimb.rank}` : "No monthly climb found", climbDelta: biggestClimb?.delta || null },
        { label: "Total Charted Artists", displayLabel: "Total Charted Artists", value: artists.length, displaySub: `artists through ${artistCutoffMonth}` },
      ];
    }
    const groups = releaseGroupsFor(releaseCt);
    const highestPoints = [...groups]
      .sort((a, b) => b.totalPoints - a.totalPoints || a.title.localeCompare(b.title))[0];
    const biggestClimb = biggestClimbFor(releaseCt);
    const mostNumberOnes = [...groups]
      .filter((group) => group.numberOneMonths.size > 0)
      .sort((a, b) => b.numberOneMonths.size - a.numberOneMonths.size || b.totalPoints - a.totalPoints)[0];
    const longestRun = [...groups]
      .sort((a, b) => b.months.size - a.months.size || b.totalPoints - a.totalPoints)[0];
    const fullCoverageCount = groups.filter((group) => group.fullCoverageMonths.size > 0).length;

    return [
      {
        label: "Most Months at #1",
        displayLabel: "Most Months at #1",
        value: mostNumberOnes?.title || "—",
        displaySub: mostNumberOnes
          ? `${mostNumberOnes.artist} · No. 1 for ${mostNumberOnes.numberOneMonths.size} ${mostNumberOnes.numberOneMonths.size === 1 ? "month" : "months"} ${trackedPeriodLabel}`
          : `No #1 ${releaseLabelLower} found`,
        certificationEntry: mostNumberOnes ? { title: mostNumberOnes.title, artist: mostNumberOnes.artist } : null,
      },
      {
        label: "Highest Points Score",
        displayLabel: "Highest Points Score",
        value: highestPoints?.title || "—",
        displaySub: highestPoints
          ? `${highestPoints.artist} · ${highestPoints.totalPoints.toLocaleString()} pts`
          : `No ${releaseLabelLower} found`,
        certificationEntry: highestPoints ? { title: highestPoints.title, artist: highestPoints.artist } : null,
      },
      {
        label: "Biggest Monthly Climb",
        displayLabel: "Biggest Monthly Climb",
        value: biggestClimb?.title || "—",
        displaySub: biggestClimb
          ? `${biggestClimb.artist} · #${biggestClimb.from} → #${biggestClimb.to}`
          : `No monthly climb found`,
        climbDelta: biggestClimb?.delta || null,
        certificationEntry: biggestClimb,
      },
      {
        label: "Perfect Coverage Club",
        displayLabel: "Perfect Coverage Club",
        value: `${fullCoverageCount} ${releaseLabelLower}`,
        displaySub: `${currentRecordsCoverageTarget}/${currentRecordsCoverageTarget} platform coverage`,
        isCoverage: true,
      },
      {
        label: "Chart Longevity",
        displayLabel: "Chart Longevity",
        value: longestRun?.title || "—",
        displaySub: longestRun
          ? `${longestRun.artist} · ${longestRun.months.size === MONTHS.length ? `Charted all ${monthCountLabel}` : `Charted ${longestRun.months.size} ${longestRun.months.size === 1 ? "month" : "months"}`}`
          : `No ${releaseLabelLower} found`,
        certificationEntry: longestRun ? { title: longestRun.title, artist: longestRun.artist } : null,
      },
      {
        label: `Total Charted ${releaseLabel}`,
        displayLabel: `Total Charted ${releaseLabel}`,
        value: groups.length,
        displaySub: `charted ${trackedPeriodLabel}`,
      },
    ];
  })() : [];

  const fullCoverageClub = useMemo(() => {
    if (!recordsActive) return [];
    const seen = new Map();
    MONTHS.forEach((m) => {
      analyticsRowsFor(m).forEach((entry) => {
        const hits = platformHitsFor(releaseCt, m, entry.title, entry.primary_artist || entry.artist);
        const fallbackCount = num(entry.platform_count) || num(String(entry.plat || "").split("/")[0]);
        const count = Math.max(hits.length, fallbackCount);
        if (count >= currentRecordsCoverageTarget) {
          const key = entryKey(entry);
          if (!seen.has(key)) seen.set(key, { title: entry.title, artist: entry.artist, month: m, pts: entry.pts });
        }
      });
    });
    return [...seen.values()].sort((a, b) => num(b.pts) - num(a.pts));
  }, [releaseCt, currentRecordsCoverageTarget, recordsActive, isArtists]);

  const navTo=p=>{setPage(p);setSelA(null);setSelR(null);setSelNews(null);setMNav(false);setMoreOpen(false);};
  const navItems=["charts","analytics","records","year-end","certifications","news","about"];
  const primaryNavItems=["charts","analytics","records","year-end","certifications"];
  const moreNavItems=navItems.filter((item)=>!primaryNavItems.includes(item));
  const navLabel=t=>t==="year-end"?"Year End":t;
  const card=(extra={})=>({background:"#FFF",borderRadius:"14px",border:"1px solid #EFEDE7",padding:isMobile?"18px":"22px",boxSizing:"border-box",maxWidth:"100%",boxShadow:"0 1px 3px rgba(0,0,0,0.02),0 8px 24px rgba(0,0,0,0.02)",...extra});
  const TXT = {
    kicker: isMobile ? "9px" : "10.5px",
    pageTitle: isMobile ? "24px" : "24px",
    lead: isMobile ? "12px" : "11px",
    section: isMobile ? "10.5px" : "10px",
    rowTitle: isMobile ? "15px" : "15px",
    rowMeta: isMobile ? "12px" : "12px",
    cardTitle: isMobile ? "15px" : "15px",
    cardMeta: isMobile ? "12px" : "12px",
    metric: isMobile ? "16px" : "16px",
    micro: "10px",
    note: isMobile ? "11px" : "11px",
    body: isMobile ? "13px" : "12px",
  };
  const secLbl=(c=GOLD)=>({fontFamily:F,fontSize:TXT.section,fontWeight:800,letterSpacing:isMobile?"2px":"2.4px",textTransform:"uppercase",color:c,marginBottom:"14px",display:"flex",alignItems:"center",gap:"7px",lineHeight:1.35});
  const SecMark=({c=GOLD})=><span style={{display:"inline-block",width:"14px",height:"2px",background:c,borderRadius:"1px"}}/>;


  const latestMonth = MONTHS[MONTHS.length - 1] || month;
  const latestMonthName = latestMonth.split(" ")[0] || "Latest";
  const latestMonthShort = latestMonthName.slice(0, 3);
  const latestTrendMonths = MONTHS.slice(-3);
  const trendMonthShort = (label = "") => String(label).split(" ")[0].slice(0, 3);
  const trendLabelText = latestTrendMonths.map(trendMonthShort).join(" / ");
  const currentTrending = isArtists ? { rising: [], debuts: [] } : (isSingles ? COMBINED_TRENDING.singles : COMBINED_TRENDING.albums);
  const formulaLabel = "Movement compares each release's Combined chart rank with the previous month";
  const getTrendPoints = (trend = []) => {
    const rawValues = Array.isArray(trend)
      ? trend.map((value) => Number.isFinite(Number(value)) ? Number(value) : null)
      : [];
    const lastValues = rawValues.slice(-latestTrendMonths.length);

    while (lastValues.length < latestTrendMonths.length) lastValues.unshift(null);

    return latestTrendMonths.map((trendMonth, index) => ({
      month: trendMonth,
      label: trendMonthShort(trendMonth),
      rank: lastValues[index],
    }));
  };
  const uniqueByMomentumIdentity = (rows = []) => [
    ...new Map(
      rows.map((row, index) => [
        `${String(row.t || "").trim().toLowerCase()}|${String(row.a || "").trim().toLowerCase()}|${row.decRank ?? index}`,
        row,
      ])
    ).values(),
  ];
  const openMomentumRelease = (row) => openReleaseDetails(row, isSingles ? "single" : "album");
  const TrendBars = ({ trend = [], height = 58, compact = false }) => {
    const bars = getTrendPoints(trend);

    return (
      <div style={{display:"flex",alignItems:"flex-end",gap:compact?"3px":"6px",height,justifyContent:compact?"flex-end":"center"}}>
        {bars.map((bar, index) => (
          <div key={`${bar.month}-${index}`} title={`${bar.month}: ${bar.rank ? `#${bar.rank}` : "not charted"}`} style={{display:"flex",flexDirection:"column",alignItems:"center",gap:compact?"2px":"4px"}}>
            <div
              style={{
                width:compact?"7px":"28px",
                height:bar.rank ? Math.max(compact?3:4, ((51 - bar.rank) / 50) * (compact ? 24 : 54)) + "px" : compact?"3px":"4px",
                background:bar.rank ? (index === bars.length - 1 ? "#2DB04A" : "#CDE8D2") : "#E7EAE7",
                borderRadius:compact?"1px":"3px",
                transition:"height 0.5s",
              }}
            />
            {!compact && <span style={{fontFamily:F,fontSize:"8px",color:"#7C8A80"}}>{bar.label}</span>}
          </div>
        ))}
      </div>
    );
  };

  const Tog=({sm})=>(
    <div
      style={{
        display:"flex",
        gap:sm?"5px":"6px",
        padding:sm?"3px":"4px",
        borderRadius:"999px",
        background:"#F2F2F2",
        border:"1px solid rgba(0,0,0,0.10)",
        boxSizing:"border-box",
        overflow:"hidden",
        maxWidth:"100%",
      }}
    >
      {["singles","albums","artists"].map(t=><button
        key={t}
        onClick={()=>{setCt(t);setPlat("Combined");}}
        style={{
          padding:sm?"7px 14px":"8px 18px",
          background:ct===t?GOLD:"#FFF",
          border:"1px solid "+(ct===t?GOLD:"rgba(0,0,0,0.14)"),
          borderRadius:"999px",
          color:"#111",
          cursor:"pointer",
          fontSize:sm?"10px":"11px",
          fontWeight:900,
          letterSpacing:"1.5px",
          textTransform:"uppercase",
          fontFamily:F,
          lineHeight:1,
          boxShadow:ct===t?"0 2px 8px rgba(184,134,11,0.20)":"none",
          transition:"all .16s ease",
        }}
      >{t}</button>)}
    </div>
  );

  const setViewMode = (key, value) => setViewModes((current) => ({ ...current, [key]: value }));
  const viewMode = (key, fallback = "graph") => viewModes[key] || fallback;
  const ViewToggle = ({ id, value = viewMode(id), onChange = (next) => setViewMode(id, next) }) => (
    <div style={{display:"flex",padding:"3px",borderRadius:"999px",background:isDark?"#181C18":"#F2F2EE",border:"1px solid "+(isDark?"#2F352F":"#E3E0D8"),flexShrink:0}}>
      {["table","graph"].map((mode)=>{
        const active = value === mode;
        return (
          <button
            key={mode}
            type="button"
            onClick={()=>onChange(mode)}
            style={{
              border:0,
              borderRadius:"999px",
              background:active?(isDark?GOLD:"#1A1A1A"):(isDark?"#FFF":"transparent"),
              color:active?"#FFF":(isDark?"#050505":"#59645D"),
              padding:"7px 12px",
              fontFamily:F,
              fontSize:"9.5px",
              fontWeight:900,
              letterSpacing:"1px",
              textTransform:"uppercase",
              cursor:"pointer",
            }}
          >
            {mode}
          </button>
        );
      })}
    </div>
  );

  // === ANALYTICS COMPUTATIONS — all from full Top-50 data ===
  const top10sData=analyticsActive?analyticsRowsFor(anMonth).slice(0,10).map(e=>({...e,name:e.title.length>16?e.title.slice(0,14)+"…":e.title,title:e.title,artist:e.artist,pts:e.pts})):[];
  const monthlyComp=analyticsActive?analysisMonths.map(m=>{
    const rows=analyticsRowsFor(m);
    return {
      month:m.split(" ")[0].slice(0,3),
      singles:getCombined("singles",m).length,
      albums:getCombined("albums",m).length,
      new:rows.filter(entry=>entry.is_new).length,
      debut:rows.filter(entry=>entry.is_new&&Number(entry.rank)<=10).length,
    };
  }):[];

  const topArtistTrajectoryArtists = analyticsActive ? artists.slice(0,3) : [];
  const topArtistsLine=analyticsActive?analysisMonths.map(m=>{
    const obj={month:m.split(" ")[0].slice(0,3)};
    topArtistTrajectoryArtists.forEach(a=>{
      obj[a.n]=a.mp[m]||0;
    });
    return obj;
  }):[];

  const cmp1=artists.find(x=>x.n===cmpA1)||{n:cmpA1,p:0,m:0,t:0,pk:"-",mp:{}};
  const cmp2=artists.find(x=>x.n===cmpA2)||{n:cmpA2,p:0,m:0,t:0,pk:"-",mp:{}};

  // === SONG / ALBUM COMPARISON ===
  const PLATS_FOR = currentPlatformKeys;
  // Unique titles for the current chart type, with their artist
  const allTitles=useMemo(()=>{
    if(!analyticsActive)return [];
    const map={};
    analysisMonths.forEach(m=>analyticsRowsFor(m).forEach(e=>{const k=e.title+" — "+e.artist;if(!map[k])map[k]={key:k,title:e.title,artist:e.artist,primary_artist:e.primary_artist||e.artist,is_artist_entry:e.is_artist_entry};}));
    return Object.values(map).sort((a,b)=>a.title.localeCompare(b.title));
  },[analyticsActive,ct,anMonth]);
  // Build a full profile for a song key
  const songProfile=(key)=>{
    const meta=allTitles.find(t=>t.key===key);
    if(!meta)return null;
    const {title,artist,primary_artist}=meta;
    const prof={title,artist,primary_artist,monthly:{},platforms:{},totalPts:0,peak:999,months:0,debutMonth:null,bestCov:0,avgRank:0};
    let rankSum=0,rankCount=0;
    analysisMonths.forEach(m=>{
      const e=analyticsRowsFor(m).find(x=>entryKey(x)===entryKey({title,primary_artist}));
      if(e){
        prof.monthly[m]={rank:e.rank,pts:e.pts,cov:e.plat};
        prof.totalPts+=e.pts; prof.months+=1;
        if(e.rank<prof.peak)prof.peak=e.rank;
        if(!prof.debutMonth)prof.debutMonth=m;
        const covNum=parseInt((e.plat||"0/0").split("/")[0],10)||0;
        if(covNum>prof.bestCov)prof.bestCov=covNum;
        rankSum+=e.rank; rankCount+=1;
      }
    });
    prof.avgRank=rankCount?Math.round(rankSum/rankCount):0;
    const releaseKey=entryKey({title,primary_artist});
    PLATS_FOR.forEach(pl=>{
      let best=null;
      analysisMonths.forEach(m=>{const pe=isArtists ? buildArtistChart(m,pl).find(x=>entryKey(x)===releaseKey) : getRawPlatformIndex(releaseCt,pl,m).get(releaseKey);if(pe&&((pe.r||pe.rank)&&(best===null||Number(pe.r||pe.rank)<best)))best=Number(pe.r||pe.rank);});
      if(best!==null)prof.platforms[pl]=best;
    });
    prof.platformCount=Object.keys(prof.platforms).length;
    // weeks-equivalent: number of (platform×month) chart appearances
    let appearances=0;
    PLATS_FOR.forEach(pl=>analysisMonths.forEach(m=>{if(isArtists ? buildArtistChart(m,pl).some(x=>entryKey(x)===releaseKey) : getRawPlatformIndex(releaseCt,pl,m).has(releaseKey))appearances+=1;}));
    prof.appearances=appearances;
    // #1 count on combined
    prof.numberOnes=Object.values(prof.monthly).filter(x=>x.rank===1).length;
    return prof;
  };
  // Default song selections to the current month's #1 and #2
  useEffect(()=>{
    if(!analyticsActive)return;
    const cd=analyticsRowsFor(anMonth);
    if(cd[0])setCmpS1(cd[0].title+" — "+cd[0].artist);
    if(cd[1])setCmpS2(cd[1].title+" — "+cd[1].artist);
  },[analyticsActive,ct,anMonth]);
  useEffect(()=>{
    if(!analyticsActive||!allTitles.length)return;
    const available = new Set(allTitles.map((item) => item.key));
    const defaults = comparisonDefaultKeys(ct, anMonth).filter((key) => available.has(key));
    if(defaults[0])setCmpS1(defaults[0]);
    if(defaults[1]||defaults[0])setCmpS2(defaults[1]||defaults[0]);
  },[analyticsActive,ct,anMonth,allTitles]);
  const [sp1,sp2]=useMemo(()=>{
    if(!analyticsActive)return [null,null];
    return [
      songProfile(cmpS1)||songProfile(allTitles[0]?.key),
      songProfile(cmpS2)||songProfile(allTitles[1]?.key),
    ];
  },[analyticsActive,ct,cmpS1,cmpS2,allTitles]);
  const songMonthlyData=analyticsActive?analysisMonths.map(m=>({month:m.split(" ")[0].slice(0,3),A:sp1?.monthly[m]?.pts||0,B:sp2?.monthly[m]?.pts||0})):[];
  const songRankData=analyticsActive?analysisMonths.map(m=>({month:m.split(" ")[0].slice(0,3),A:sp1?.monthly[m]?.rank||null,B:sp2?.monthly[m]?.rank||null})):[];

  const yearEnd=isArtists?buildArtistYearEndRows():(isSingles?COMBINED_YEAR_END.singles:COMBINED_YEAR_END.albums);

  const tracked=analyticsRowsFor(analyticsActive?anMonth:CURRENT_MONTH).slice(0,5).map(entry=>entry.title);
  const rankJourneyStartIndex=tracked.reduce((earliest,title)=>{
    const idx=analysisMonths.findIndex(m=>analyticsRowsFor(m).some(e=>e.title===title));
    return idx>=0?Math.min(earliest,idx):earliest;
  },analysisMonths.length);
  const rankJourneyMonths=rankJourneyStartIndex<analysisMonths.length?analysisMonths.slice(rankJourneyStartIndex):analysisMonths;

  const certs=buildCertifications(yearEnd);
  const certIcons=CERTIFICATION_LEVELS.reduce((acc, item) => {
    acc[item.level] = item.icon;
    return acc;
  }, {});
  const certColors=CERTIFICATION_LEVELS.reduce((acc, item) => {
    acc[item.level] = item.color;
    return acc;
  }, {});
  const certificationLookup = useMemo(() => {
    const buildLookup = (items = []) => {
      const map = new Map();
      items.forEach((item) => {
        const level = getCertificationLevel(item.totalPts);
        const meta = certificationMetaForLevel(level);
        if (!meta) return;
        map.set(certificationKey(item.t, item.a), {
          ...meta,
          totalPts: Number(item.totalPts) || 0,
        });
      });
      return map;
    };

    return {
      singles: buildLookup(COMBINED_YEAR_END.singles),
      albums: buildLookup(COMBINED_YEAR_END.albums),
    };
  }, []);
  const getCertificationForEntry = (entry = {}, fallbackType) => {
    const type = String(fallbackType || entry.type || (isSingles ? "single" : "album")).toLowerCase();
    const bucket = type.includes("album") ? "albums" : "singles";
    const title = releaseTitle(entry);
    const artist = releaseArtist(entry);

    const explicitLevel = String(
      entry.certification_level ||
      entry.certificationLevel ||
      entry.certification ||
      entry.cert_level ||
      ""
    )
      .trim()
      .toLowerCase()
      .replace(/\s+certified$/, "");

    const explicitMeta = certificationMetaForLevel(explicitLevel);
    const totalPts = firstFiniteNumber(
      entry.totalPts,
      entry.total_points,
      entry.totalPoints,
      entry.cumulative_points,
      entry.certification_points,
      entry.certificationPoints
    );

    const fromLookup = certificationLookup[bucket]?.get(certificationKey(title, artist));
    if (fromLookup) return fromLookup;

    if (explicitMeta) {
      return { ...explicitMeta, totalPts: totalPts || 0 };
    }

    const levelFromPoints = getCertificationLevel(totalPts);
    const metaFromPoints = certificationMetaForLevel(levelFromPoints);
    return metaFromPoints ? { ...metaFromPoints, totalPts: totalPts || 0 } : null;
  };
  const allCertifiedReleases = useMemo(() => {
    const build = (items = [], type) => buildCertifications(items).map((item) => {
      const meta = certificationMetaForLevel(item.level);
      return meta ? { ...item, ...meta, type } : null;
    }).filter(Boolean);

    return [
      ...build(COMBINED_YEAR_END.singles, "single"),
      ...build(COMBINED_YEAR_END.albums, "album"),
    ].sort((a, b) => b.totalPts - a.totalPts || b.pts - a.pts);
  }, []);

  const getCertificationsForNews = (news = {}, limit = 3) => {
    const text = `${news.title || ""} ${news.excerpt || ""} ${news.body || ""}`.toLowerCase();
    if (!text.trim()) return [];

    const seen = new Set();
    return allCertifiedReleases.filter((cert) => {
      const key = certificationKey(cert.t, cert.a);
      if (seen.has(key)) return false;
      const title = String(cert.t || "").toLowerCase();
      const artist = String(cert.a || "").toLowerCase();
      const matches = title && text.includes(title) || (artist && title && text.includes(artist) && text.includes(title));
      if (matches) seen.add(key);
      return matches;
    }).slice(0, limit);
  };

  const CertificationTag = ({ cert, compact = true, style = {} }) => {
    if (!cert) return null;
    const certificationLabel = `${cert.label} certified · ${Number(cert.totalPts || 0).toLocaleString()} points`;
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: "fit-content",
          maxWidth: "100%",
          minWidth: compact ? "24px" : "30px",
          minHeight: compact ? "24px" : "30px",
          padding: compact ? "2px 5px" : "4px 6px",
          borderRadius: "999px",
          background: `${cert.color}14`,
          border: `1px solid ${cert.color}40`,
          color: cert.color,
          fontFamily: F,
          fontSize: compact ? "13px" : "17px",
          lineHeight: 1.1,
          whiteSpace: "nowrap",
          verticalAlign: "middle",
          ...style,
        }}
        title={certificationLabel}
        aria-label={certificationLabel}
      >
        <span aria-hidden="true">{cert.icon}</span>
      </span>
    );
  };

  // Hall of Fame: #1 each month for both singles and albums
  const hof=MONTHS.flatMap(m=>{
    const s=getCombined("singles",m)[0];
    const a=getCombined("albums",m)[0];
    return [s?{...s,month:m,type:"single"}:null,a?{...a,month:m,type:"album"}:null];
  }).filter(Boolean);

  const releaseJourney=r=>{
    if(!r)return [];
    return MONTHS.map(m=>{
      const sc=getCombined(releaseCt,m).find(e=>sameRelease(e,r));
      const platforms=isSingles?["APPLE MUSIC","AUDIOMACK","BOOMPLAY","SPOTIFY","YOUTUBE","SHAZAM"]:["APPLE MUSIC","AUDIOMACK"];
      const entries=platforms.map(pl=>{const d=getPlatform(releaseCt,pl,m).find(e=>sameRelease(e,r));return d?{platform:PLAT_LABEL[pl]||pl,rank:d.rank,pts:d.pts}:null;}).filter(Boolean);
      return {month:m,combined:sc||null,platforms:entries};
    });
  };

  const allArtistNames=[...new Set(artists.map(a=>a.n))].sort();
  const selectedArtistEntries = selA ? MONTHS.flatMap((monthLabel) =>
    getArtistSourceCombined(ct, monthLabel)
      .filter((entry) => artistCreditMembers(entry).some((name) => name.toLowerCase() === selA.n.toLowerCase()))
      .map((entry) => ({...entry, month: monthLabel}))
  ) : [];
  const selectedArtistReleases = selA ? [...new Map(selectedArtistEntries.map((entry) => [entryKey(entry), entry])).values()] : [];
  const selectedArtistEntryGroups = selA ? [...selectedArtistEntries.reduce((map, entry) => {
    const key = entryKey(entry);
    const current = map.get(key) || {
      title: entry.title,
      artist: entry.artist,
      primary_artist: entry.primary_artist,
      featured_artists: entry.featured_artists,
      totalPoints: 0,
      peak: Number.POSITIVE_INFINITY,
      rows: [],
    };
    current.totalPoints += Number(entry.pts) || 0;
    current.peak = Math.min(current.peak, Number(entry.rank) || Number.POSITIVE_INFINITY);
    current.rows.push(entry);
    map.set(key, current);
    return map;
  }, new Map()).values()].sort((a, b) => b.totalPoints - a.totalPoints || a.peak - b.peak || a.title.localeCompare(b.title)) : [];
  const selectedArtistRankData = selA ? MONTHS.map((monthLabel) => ({
    month: monthLabel.split(" ")[0].slice(0, 3),
    rank: selA.rh?.[monthLabel] || null,
    points: selA.mp?.[monthLabel] || 0,
  })) : [];

  const pageContext = {
    API_BASE,
    AnalyticsDeepSection,
    BRONZE,
    Bar,
    BarChart,
    CC,
    CERTIFICATION_LEVELS,
    CartesianGrid,
    Cell,
    CertificationTag,
    CountryBadge,
    DATA_PERIOD,
    F,
    GOLD,
    Legend,
    Line,
    LineChart,
    MEDALS,
    MONTHS,
    NEWS: liveNews || NEWS,
    PAD,
    PAGE_MAX,
    PC,
    PUBLIC_PLATFORMS,
    PUBLIC_METHODOLOGY,
    PLATS_FOR,
    PLAT_LABEL,
    Pie,
    PieChart,
    PremiumChartsPage,
    RecordIcon,
    ResponsiveContainer,
    SF,
    SILVER,
    SITE_NAME,
    SecMark,
    TXT,
    Tog,
    Tooltip,
    TrendBars,
    VO,
    ViewToggle,
    XAxis,
    YAxis,
    allArtistNames,
    allTitles,
    anMonth,
    analyticsRowsFor,
    artistMonth,
    artistTrendFor,
    artists,
    card,
    certColors,
    certIcons,
    certs: liveCerts || certs,
    chartTypeLabel,
    closeDetails,
    cmp1,
    cmp2,
    cmpA1,
    cmpA2,
    cmpS1,
    cmpS2,
    coverageData,
    crossPlatformRows,
    ct,
    currentPlatformKeys,
    currentRecords,
    currentTrending,
    data,
    display,
    expandedArtistRows,
    expandedTrendingRows,
    expandedYearEndRows,
    featureAnalytics,
    formulaLabel,
    fullCoverageClub,
    getArtistCountry,
    getCertificationForEntry,
    getCombined,
    hof,
    isDark,
    isMobile,
    isArtists,
    isAlbums,
    isSingles,
    releaseCt,
    latestMonth,
    latestMonthName,
    latestMonthShort,
    liveChartLoading,
    liveChartMeta,
    liveStatus,
    loaded,
    month,
    monthIndex,
    mvData,
    navTo,
    openArtistDetails,
    openMomentumRelease,
    openRecord,
    openReleaseDetails,
    plat,
    platList,
    platOnes,
    platTotalsData,
    rankJourneyMonths,
    rankJourneyView,
    releaseJourney,
    releaseLabel,
    releaseLabelLower,
    secLbl,
    selA,
    selNews,
    selR,
    selectedArtistEntries,
    selectedArtistEntryGroups,
    selectedArtistRankData,
    selectedArtistReleases,
    setAnMonth,
    setArtistMonth,
    setCmpA1,
    setCmpA2,
    setCmpS1,
    setCmpS2,
    setCt,
    setMonth,
    setOpenRecord,
    setPlat,
    setRankJourneyView,
    setSelA,
    setSelNews,
    setSelR,
    setVc,
    songMonthlyData,
    songRankData,
    sp1,
    sp2,
    toggleArtistRow,
    toggleTrendingRow,
    toggleYearEndRow,
    top,
    top10sData,
    topArtistTrajectoryArtists,
    topArtistsLine,
    topCountryData,
    tp,
    tracked,
    trendLabelText,
    uniqueByMomentumIdentity,
    uniquePlatformData,
    vc,
    viewMode,
    yearEnd
  };

  const managedSections = [
    ...(PUBLIC_DATA.page_content?.[page] || []),
    ...(page === "charts" ? (PUBLIC_DATA.page_content?.home || []) : []),
  ];

  return(
    <div className="ngoma-app-shell" data-theme={theme} style={{fontFamily:SF,background:themeColors.page,color:themeColors.text,minHeight:"100vh",width:"100%",overflowX:"hidden"}}>
      <link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600;700;800;900&family=Instrument+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet"/>
      <style>{`
        html, body, #root{max-width:100%;overflow-x:hidden;}
        *, *::before, *::after{box-sizing:border-box;}
        img, svg, canvas, video{max-width:100%;}
        button, input, select, textarea{max-width:100%;}
        footer button:not([data-keep-share-card="true"]){display:none !important;}
        footer .share-card-button, footer [data-share-card]:not([data-keep-share-card="true"]), footer [aria-label*="Share"]{display:none !important;}
        button[data-stray-share-hidden="true"]{display:none !important;visibility:hidden !important;pointer-events:none !important;}
        .ngoma-mobile-text-safe{min-width:0;overflow-wrap:anywhere;}
        .ngoma-analytics-chart-scroll{max-width:100%;overflow-x:auto;overflow-y:hidden;padding-bottom:4px;}
        .ngoma-analytics-chart-inner{min-width:0;}
        .ngoma-analytics-metric-label{color:#59645D !important;}
        .ngoma-analytics-muted{color:#59645D !important;}
        .ngoma-analytics-page > *{content-visibility:auto;contain-intrinsic-size:auto 320px;}
        .ngoma-mobile-collapsible{margin:0 0 20px;}
        .ngoma-mobile-collapsible > summary{display:none;}
        @media (max-width: 860px){
          .anl-2col{grid-template-columns:1fr !important;}
        }
        @media (max-width: 640px){
          .anl-grid-2{grid-template-columns:1fr !important;}
          .anl-2col{grid-template-columns:1fr !important;}
          .anl-grid-3{grid-template-columns:1fr !important;}
          .anl-grid-4{grid-template-columns:1fr 1fr !important;}
          .podium-grid{grid-template-columns:1fr !important;}
          .race-card{min-width:100% !important;}
          .ngoma-artist-row{grid-template-columns:34px 34px minmax(0,1fr) 82px !important;gap:9px !important;padding:13px 8px !important;}
          .ngoma-artist-pts-label{display:none !important;}
          .ngoma-mobile-center-frame{padding-left:clamp(20px,5vw,28px) !important;padding-right:clamp(20px,5vw,28px) !important;}
          .ngoma-analytics-chart-scroll{margin-left:-2px;margin-right:-2px;padding-bottom:8px;}
          .ngoma-analytics-chart-inner{min-width:520px;}
          .ngoma-analytics-wide-chart{min-width:620px;}
          .ngoma-mobile-collapsible{background:#FFF;border:1px solid #EFEDE7;border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,0.02),0 8px 24px rgba(0,0,0,0.02);overflow:hidden;}
          .ngoma-mobile-collapsible > summary{display:flex;align-items:center;justify-content:space-between;gap:12px;list-style:none;padding:15px 16px;font-family:"Instrument Sans",Helvetica,sans-serif;font-size:10.5px;font-weight:850;letter-spacing:1.8px;text-transform:uppercase;color:#59645D;cursor:pointer;}
          .ngoma-mobile-collapsible > summary::-webkit-details-marker{display:none;}
          .ngoma-mobile-collapsible > summary span{font-size:10px;letter-spacing:0.8px;color:#B8860B;text-transform:none;}
          .ngoma-mobile-collapsible[open] > summary{border-bottom:1px solid #F2F0EA;}
          .ngoma-mobile-collapsible[open] > summary span{font-size:0;}
          .ngoma-mobile-collapsible[open] > summary span::after{content:"Hide";font-size:10px;color:#B8860B;}
          .ngoma-mobile-collapsible-body > div{border:none !important;box-shadow:none !important;margin-bottom:0 !important;border-radius:0 !important;}
        }
        ::-webkit-scrollbar{height:5px;width:5px;}
        ::-webkit-scrollbar-thumb{background:#D8D2C4;border-radius:3px;}
        * { -webkit-tap-highlight-color: transparent; }
        .ngoma-title-link:hover{ text-decoration: underline; text-underline-offset: 2px; }
        .ngoma-artist-link:hover{ color:#B8860B !important; text-decoration: underline; text-underline-offset: 2px; }
        @keyframes fadeUp{from{opacity:0;transform:translateY(10px);}to{opacity:1;transform:none;}}
      `}</style>

      {MAINTENANCE_SETTING.enabled&&<div role="status" style={{padding:"11px 18px",background:MAINTENANCE_SETTING.background || "#FFF3CD",color:MAINTENANCE_SETTING.color || "#5F4700",fontFamily:F,fontSize:"12px",fontWeight:800,textAlign:"center",borderBottom:`1px solid ${GOLD}55`}}>{MAINTENANCE_SETTING.message || `${SITE_NAME} is currently undergoing maintenance.`}</div>}

      {/* HEADER */}
      <header style={{background:themeColors.surface,borderBottom:`3px solid ${themeColors.text}`,position:"sticky",top:0,zIndex:50}}>
        <div style={{background:"#1A1A1A",color:"#FFF"}}>
          <div style={{...pageFrame({display:"flex",justifyContent:"flex-end",alignItems:"center",gap:"10px",padding:isMobile?"6px 16px":"5px 28px"}),fontFamily:F,fontSize:isMobile?"8px":"9.5px",letterSpacing:isMobile?"1px":"2px",textTransform:"uppercase"}}>
            <span style={{color:"rgba(255,255,255,0.68)",fontSize:isMobile?"8px":"9.5px",letterSpacing:isMobile?"0.5px":"1px",fontFamily:"inherit",whiteSpace:"nowrap"}}>
              {new Date().toLocaleDateString(undefined,{weekday:"short",day:"numeric",month:"short",year:"numeric"})}
            </span>
          </div>
        </div>
          <div style={{...pageFrame({display:"flex",justifyContent:"space-between",alignItems:"center",padding:isMobile?"14px 16px":"18px 28px 22px"}),columnGap:isMobile?"16px":"60px",rowGap:"16px",flexWrap:"wrap"}}>
          <div onClick={()=>navTo("charts")} style={{display:"flex",alignItems:"center",gap:"14px",cursor:"pointer"}}>
            <svg width={isMobile?"24":"32"} height={isMobile?"26":"34"} viewBox="0 0 22 24" style={{flexShrink:0}}>
              <rect x="0" y="15" width="3.5" height="9" fill={themeColors.text} rx="0.5"/>
              <rect x="5.5" y="10" width="3.5" height="14" fill={themeColors.text} rx="0.5"/>
              <rect x="11" y="5" width="3.5" height="19" fill={GOLD} rx="0.5"/>
              <rect x="16.5" y="0" width="3.5" height="24" fill={themeColors.text} rx="0.5"/>
            </svg>
            <div style={{display:"flex",flexDirection:"column",lineHeight:1,cursor:"pointer"}}>
              <span
                style={{
                  fontFamily:F,
                  fontSize:isMobile?"20px":"28px",
                  fontWeight:950,
                  letterSpacing:isMobile?"2px":"4px",
                  color:themeColors.text,
                  textTransform:"uppercase",
                }}
              >
                <span style={{color:GOLD,fontWeight:950}}>{SITE_NAME}</span>
              </span>
              <span
                style={{
                  marginTop:"4px",
                  fontFamily:F,
                  fontSize:isMobile?"9.5px":"13px",
                  fontWeight:900,
                  letterSpacing:isMobile?"1.4px":"2.2px",
                  color:themeColors.muted,
                  textTransform:"uppercase",
                  whiteSpace:"nowrap",
                }}
              >
                Music ranking intelligence
              </span>
            </div>
          </div>
          {isMobile ? (
            <>
              <button
                onClick={()=>setMNav(o=>!o)}
                aria-label="Toggle menu"
                aria-expanded={mNav}
                style={{display:"flex",flexDirection:"column",justifyContent:"center",gap:"4px",width:"42px",height:"38px",border:`1px solid ${themeColors.border}`,borderRadius:"11px",background:themeColors.elevated,cursor:"pointer",padding:"0 10px",flexShrink:0,marginLeft:"auto"}}
              >
                <span style={{display:"block",height:"2px",background:themeColors.text,borderRadius:"2px",transition:"all .2s",transform:mNav?"translateY(6px) rotate(45deg)":"none"}}/>
                <span style={{display:"block",height:"2px",background:themeColors.text,borderRadius:"2px",opacity:mNav?0:1,transition:"opacity .2s"}}/>
                <span style={{display:"block",height:"2px",background:themeColors.text,borderRadius:"2px",transition:"all .2s",transform:mNav?"translateY(-6px) rotate(-45deg)":"none"}}/>
              </button>
              {mNav&&(
                <div style={{width:"100%",display:"flex",flexDirection:"column",gap:"2px",marginTop:"8px",borderTop:`1px solid ${themeColors.border}`,paddingTop:"10px"}}>
                  {navItems.map(t=>(
                    <span key={t} onClick={()=>navTo(t)} style={{cursor:"pointer",padding:"13px 14px",borderRadius:"12px",fontFamily:F,fontSize:"13px",fontWeight:page===t?800:600,letterSpacing:"1px",textTransform:"uppercase",color:page===t?themeColors.text:themeColors.muted,background:page===t?themeColors.active:"transparent",border:page===t?"1px solid #D4B65E":"1px solid transparent"}}>{navLabel(t)}</span>
                  ))}
                  <span onClick={()=>{setMNav(false);setSOpen(true);}} style={{cursor:"pointer",padding:"13px 14px",borderRadius:"12px",fontFamily:F,fontSize:"13px",fontWeight:600,letterSpacing:"1px",textTransform:"uppercase",color:themeColors.muted}}>Search</span>
                  {themeToggle({hideDot:true,width:"100%",justifyContent:"flex-start",borderRadius:"12px",minHeight:"44px",padding:"0 14px",marginTop:"4px",fontSize:"13px",fontWeight:600,letterSpacing:"1px"})}
                </div>
              )}
            </>
          ) : (
            <nav style={{display:"flex",gap:"14px",fontFamily:F,fontSize:"11px",fontWeight:700,letterSpacing:"1.5px",textTransform:"uppercase",alignItems:"center",flexShrink:0,position:"relative"}}>
              {primaryNavItems.map(t=>(
                <span key={t} onClick={()=>navTo(t)} style={{color:page===t?themeColors.text:themeColors.muted,cursor:"pointer",whiteSpace:"nowrap",padding:"6px 12px",borderRadius:"20px",background:page===t?themeColors.active:"transparent",fontWeight:page===t?800:700,transition:"all 0.15s",border:page===t?"1px solid #D4B65E":"1px solid transparent"}}
                  onMouseEnter={e=>{if(page!==t)e.currentTarget.style.color=themeColors.text;}}
                  onMouseLeave={e=>{if(page!==t)e.currentTarget.style.color=themeColors.muted;}}
                >{navLabel(t)}</span>
              ))}
              <div style={{position:"relative"}}>
                <button
                  type="button"
                  onClick={()=>setMoreOpen((open)=>!open)}
                  aria-haspopup="menu"
                  aria-expanded={moreOpen}
                  style={{
                    cursor:"pointer",
                    color:moreNavItems.includes(page)?themeColors.text:themeColors.muted,
                    whiteSpace:"nowrap",
                    padding:"6px 12px",
                    borderRadius:"20px",
                    background:moreNavItems.includes(page)?themeColors.active:"transparent",
                    fontFamily:F,
                    fontSize:"11px",
                    fontWeight:moreNavItems.includes(page)?800:700,
                    letterSpacing:"1.5px",
                    textTransform:"uppercase",
                    border:moreNavItems.includes(page)?"1px solid #D4B65E":"1px solid transparent",
                    display:"inline-flex",
                    alignItems:"center",
                    gap:"6px",
                  }}
                  onMouseEnter={e=>{e.currentTarget.style.color=themeColors.text;e.currentTarget.style.background=moreNavItems.includes(page)?themeColors.active:themeColors.hover;}}
                  onMouseLeave={e=>{e.currentTarget.style.color=moreNavItems.includes(page)?themeColors.text:themeColors.muted;e.currentTarget.style.background=moreNavItems.includes(page)?themeColors.active:"transparent";}}
                >More <span style={{fontSize:"10px",lineHeight:1}}>{moreOpen?"▴":"▾"}</span></button>
                {moreOpen&&(
                  <div role="menu" style={{position:"absolute",right:0,top:"calc(100% + 10px)",minWidth:"176px",padding:"8px",borderRadius:"14px",background:themeColors.elevated,border:`1px solid ${themeColors.border}`,boxShadow:isDark?"0 18px 35px rgba(0,0,0,0.36)":"0 18px 35px rgba(31,36,31,0.14)",zIndex:80}}>
                    {moreNavItems.map(t=>(
                      <button key={t} type="button" role="menuitem" onClick={()=>navTo(t)} style={{display:"flex",width:"100%",alignItems:"center",justifyContent:"space-between",border:0,borderRadius:"10px",background:page===t?themeColors.active:"transparent",color:page===t?themeColors.text:themeColors.muted,padding:"10px 11px",fontFamily:F,fontSize:"11px",fontWeight:page===t?850:750,letterSpacing:"1.1px",textTransform:"uppercase",cursor:"pointer",textAlign:"left"}}
                        onMouseEnter={e=>{e.currentTarget.style.color=themeColors.text;e.currentTarget.style.background=page===t?themeColors.active:themeColors.hover;}}
                        onMouseLeave={e=>{e.currentTarget.style.color=page===t?themeColors.text:themeColors.muted;e.currentTarget.style.background=page===t?themeColors.active:"transparent";}}
                      >{navLabel(t)}<span aria-hidden="true" style={{color:GOLD}}>›</span></button>
                    ))}
                  </div>
                )}
              </div>
              <span
                onClick={()=>{setMoreOpen(false);setSOpen(true);}}
                style={{
                  cursor:"pointer",
                  color:themeColors.muted,
                  whiteSpace:"nowrap",
                  padding:"6px 12px",
                  borderRadius:"20px",
                  fontFamily:F,
                  fontSize:"11px",
                  fontWeight:700,
                  letterSpacing:"1.5px",
                  textTransform:"uppercase",
                  border:"1px solid transparent",
                }}
                onMouseEnter={e=>{e.currentTarget.style.color=themeColors.text;e.currentTarget.style.background=themeColors.hover;}}
                onMouseLeave={e=>{e.currentTarget.style.color=themeColors.muted;e.currentTarget.style.background="transparent";}}
              >Search</span>
              {themeToggle()}
            </nav>
          )}
        </div>
      </header>

      {/* SHARE IMAGE PREVIEW */}
      {/* SEARCH */}
      {sOpen&&(
        <div style={{position:"fixed",inset:0,background:"rgba(0,0,0,0.5)",zIndex:100,display:"flex",justifyContent:"center",paddingTop:"70px"}} onClick={()=>{setSOpen(false);setSrch("");}}>
          <div onClick={e=>e.stopPropagation()} style={{background:"#FFF",borderRadius:"12px",width:isMobile?"calc(100vw - 32px)":"560px",maxWidth:"100%",maxHeight:"560px",overflow:"hidden",boxShadow:"0 20px 60px rgba(0,0,0,0.25)",boxSizing:"border-box"}}>
            <div style={{padding:"16px 20px",borderBottom:"1px solid #EEE",display:"flex",alignItems:"center",gap:"10px"}}>
              <span style={{fontSize:"18px",color:"#CCC"}}>⌕</span>
              <input value={srch} onChange={e=>setSrch(e.target.value)} placeholder="Search across all songs, albums, artists..." autoFocus style={{flex:1,border:"none",outline:"none",fontSize:"16px",fontFamily:SF}}/>
              <span onClick={()=>{setSOpen(false);setSrch("");}} style={{cursor:"pointer",color:"#CCC"}}>✕</span>
            </div>
            <div style={{maxHeight:"480px",overflow:"auto"}}>
              {sRes.map((e,i)=>(
                <div key={i} style={{padding:"11px 20px",borderBottom:"1px solid #F5F5F3",display:"flex",justifyContent:"space-between",alignItems:"center"}}
                  onMouseEnter={x=>x.currentTarget.style.background="#FAFAF6"} onMouseLeave={x=>x.currentTarget.style.background="transparent"}>
                  <div><button type="button" onClick={()=>{setSOpen(false);setSrch("");setPage("charts");setMonth(e.month);openReleaseDetails(e,e.type);}} style={{border:0,background:"transparent",padding:0,fontFamily:SF,fontSize:"14px",fontWeight:700,cursor:"pointer",textAlign:"left"}}>{e.title}</button><div style={{fontSize:"10.5px",color:"#999",fontFamily:F}}>{e.artist} · <span style={{color:GOLD}}>{e.type} · {e.month}</span></div></div>
                  <div style={{fontFamily:F,fontSize:"10.5px",color:GOLD,fontWeight:600}}>#{e.rank} · {e.pts.toLocaleString()} pts</div>
                </div>
              ))}
              {srch.length>1&&!sRes.length&&<div style={{padding:"24px",textAlign:"center",color:"#CCC",fontFamily:F}}>No results across all months</div>}
              {srch.length<=1&&<div style={{padding:"24px",textAlign:"center",color:"#DDD",fontFamily:F,fontSize:"13px"}}>Type to search across all 50+ entries from each platform</div>}
            </div>
          </div>
        </div>
      )}

      <main style={pageFrame({padding:isMobile?"0 4px":0,overflow:"hidden"})}>
      {managedSections.map((section)=><section key={section.id || section.section} style={{margin:isMobile?"14px 18px":"18px 28px",padding:isMobile?"16px":"20px",border:`1px solid ${GOLD}33`,borderRadius:"14px",background:themeColors.elevated}}>
        {section.title&&<h2 style={{margin:"0 0 8px",fontFamily:SF,fontSize:isMobile?"19px":"23px",color:themeColors.text}}>{section.title}</h2>}
        {section.content&&<div style={{fontFamily:F,fontSize:"13px",lineHeight:1.75,color:themeColors.muted,whiteSpace:"pre-wrap"}}>{section.content}</div>}
        {section.data?.image&&<img src={section.data.image} alt={section.data.alt || section.title || ""} style={{display:"block",marginTop:"12px",maxHeight:"360px",borderRadius:"10px",objectFit:"cover"}} />}
        {section.data?.cta_url&&<a href={section.data.cta_url} style={{display:"inline-flex",marginTop:"12px",padding:"9px 14px",borderRadius:"999px",background:GOLD,color:"#FFF",fontFamily:F,fontSize:"11px",fontWeight:850,textDecoration:"none"}}>{section.data.cta_label || "Learn more"}</a>}
      </section>)}
      {/* RELEASE DETAIL */}
      {selR && <ReleaseDetailPage ctx={pageContext} />}

      {/* ARTIST PROFILE */}
      {selA && !selR && <ArtistDetailPage ctx={pageContext} />}

      {/* CHARTS PAGE */}
      {page === "charts" && !selA && !selR && <ChartsPage ctx={pageContext} />}

      {/* ANALYTICS PAGE */}
      {page === "analytics" && !selA && !selR && <AnalyticsPage ctx={pageContext} />}

      {/* RECORDS & MILESTONES PAGE */}
      {page === "records" && !selA && !selR && <RecordsPage ctx={pageContext} />}

      {/* YEAR-END PAGE */}
      {page === "year-end" && !selA && !selR && <YearEndPage ctx={pageContext} />}

      {/* CERTIFICATIONS PAGE */}
      {page === "certifications" && !selA && !selR && <CertificationsPage ctx={pageContext} />}

      {/* NEWS PAGE */}
      {page === "news" && !selNews && !selA && !selR && <NewsPage ctx={pageContext} />}
      {page === "news" && selNews && !selA && !selR && <NewsDetailPage ctx={pageContext} />}

      {/* ABOUT PAGE */}
      {page === "about" && !selA && !selR && <AboutPage ctx={pageContext} />}

      </main>

      {/* FOOTER */}
      <footer style={{padding:isMobile?"32px 18px 36px":"22px 28px",borderTop:"3px solid #1A1A1A",background:"#1A1A1A",fontFamily:F,boxSizing:"border-box",overflow:"hidden"}}>
        <div style={{...pageFrame(),display:"flex",justifyContent:"space-between",alignItems:"center",flexWrap:"wrap",gap:isMobile?"18px":"14px",flexDirection:isMobile?"column":"row",textAlign:isMobile?"center":"left"}}>
          <div onClick={()=>navTo("charts")} style={{display:"flex",alignItems:"center",gap:"9px",cursor:"pointer"}}>
            <svg width="16" height="18" viewBox="0 0 22 24" style={{flexShrink:0}}>
              <rect x="0" y="15" width="3.5" height="9" fill="#FFF" rx="0.5"/>
              <rect x="5.5" y="10" width="3.5" height="14" fill="#FFF" rx="0.5"/>
              <rect x="11" y="5" width="3.5" height="19" fill={GOLD} rx="0.5"/>
              <rect x="16.5" y="0" width="3.5" height="24" fill="#FFF" rx="0.5"/>
            </svg>
            <span style={{fontFamily:F,fontSize:isMobile?"12px":"11px",fontWeight:800,letterSpacing:"2.5px",color:GOLD,textTransform:"uppercase"}}>{SITE_NAME}</span>
          </div>
          <div style={{display:"flex",gap:isMobile?"10px":"14px",alignItems:"center",justifyContent:"center"}}>
            {[
              {label:"Facebook", href:SOCIAL_LINKS.facebook || "https://www.facebook.com/ngomacharts", bg:"#1877F2", color:"#FFF",
               path:"M14 8.5h2V5.8h-2.4C11.5 5.8 10.5 7 10.5 9v1.5H8.7V13h1.8v6h2.6v-6h2l.3-2.5h-2.3V9.1c0-.4.2-.6.7-.6Z"},
              {label:"X", href:SOCIAL_LINKS.x || "https://x.com/Ngoma_Charts", bg:"#000", color:"#FFF", border:"1px solid rgba(255,255,255,0.18)",
               path:"M16.8 5h2.2l-4.8 5.5L20 19h-4.4l-3.5-4.6L8 19H5.8l5.1-5.9L5 5h4.5l3.1 4.2L16.8 5Zm-.8 12.6h1.2L9.1 6.3H7.8L16 17.6Z"},
              {label:"Instagram", href:SOCIAL_LINKS.instagram || "https://www.instagram.com/ngoma_charts/", bg:"linear-gradient(135deg,#F58529 0%,#DD2A7B 45%,#8134AF 72%,#515BD4 100%)", color:"#FFF",
               path:"M12 7.3A4.7 4.7 0 1012 16.7 4.7 4.7 0 0012 7.3Zm0 7.7a3 3 0 110-6 3 3 0 010 6Zm4.9-7.9a1.1 1.1 0 11-2.2 0 1.1 1.1 0 012.2 0ZM16.5 5h-9A2.5 2.5 0 005 7.5v9A2.5 2.5 0 007.5 19h9a2.5 2.5 0 002.5-2.5v-9A2.5 2.5 0 0016.5 5Z"},
            ].map(s=>(
              <a key={s.label} href={s.href} target="_blank" rel="noopener noreferrer" aria-label={s.label}
                 style={{display:"flex",alignItems:"center",justifyContent:"center",width:isMobile?"44px":"38px",height:isMobile?"44px":"38px",borderRadius:"50%",color:s.color,transition:"transform .2s, box-shadow .2s, background .2s",background:s.bg,border:s.border||"1px solid transparent",boxShadow:"0 8px 18px rgba(0,0,0,0.16)"}}
                 onMouseEnter={e=>{e.currentTarget.style.transform="translateY(-2px) scale(1.04)";e.currentTarget.style.boxShadow="0 12px 26px rgba(0,0,0,0.24)";}}
                 onMouseLeave={e=>{e.currentTarget.style.transform="none";e.currentTarget.style.boxShadow="0 8px 18px rgba(0,0,0,0.16)";}}>
                {s.label==="Instagram"?(
                  <svg width={isMobile?"22":"20"} height={isMobile?"22":"20"} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="5" y="5" width="14" height="14" rx="4.2" />
                    <circle cx="12" cy="12" r="3.2" />
                    <circle cx="16.4" cy="7.6" r="1" fill="currentColor" stroke="none" />
                  </svg>
                ):(
                  <svg width={isMobile?"22":"20"} height={isMobile?"22":"20"} viewBox="0 0 24 24" fill="currentColor"><path d={s.path}/></svg>
                )}
              </a>
            ))}
          </div>
        </div>
        <div
          style={{
            ...pageFrame(),
            marginTop: "8px",
            display: "flex",
            flexDirection: isMobile ? "column" : "row",
            gap: isMobile ? "4px" : "10px",
            alignItems: "center",
            justifyContent: isMobile ? "center" : "flex-start",
            textAlign: isMobile ? "center" : "left",
            fontSize: "8px",
            color: "rgba(255,255,255,0.38)",
            letterSpacing: "1px",
            textTransform: "uppercase",
          }}
        >
          <span>{FOOTER_SETTING.text || `© ${new Date().getFullYear()} ${SITE_NAME}`}</span>
        </div>
      </footer>
    </div>
  );
}
