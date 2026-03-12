from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

try:
    from zoneinfo import ZoneInfo, available_timezones
except ImportError:  # pragma: no cover
    from zoneinfo import ZoneInfo  # type: ignore

    def available_timezones() -> set[str]:  # type: ignore[override]
        return set()

from .app_paths import resource_path

FIXED_OFFSET_PREFIX = "UTC"
SYSTEM_TIMEZONE = "auto"


@dataclass(frozen=True)
class TimezoneEntry:
    value: str
    city: str
    region: str
    base_offset_minutes: int
    keywords: Sequence[str]

    @property
    def identity(self) -> str:
        return f"{self.city} {self.region} {self.value}".strip()


_TIMEZONE_CACHE: Optional[List[TimezoneEntry]] = None


WINDOWS_TZ_TO_IANA: Dict[str, str] = {
    "Dateline Standard Time": "Etc/GMT+12",
    "UTC-11": "Pacific/Pago_Pago",
    "Aleutian Standard Time": "America/Adak",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "Marquesas Standard Time": "Pacific/Marquesas",
    "Alaskan Standard Time": "America/Anchorage",
    "UTC-09": "Etc/GMT+9",
    "Pacific Standard Time (Mexico)": "America/Tijuana",
    "Pacific Standard Time": "America/Los_Angeles",
    "US Mountain Standard Time": "America/Phoenix",
    "Mountain Standard Time (Mexico)": "America/Chihuahua",
    "Mountain Standard Time": "America/Denver",
    "Central America Standard Time": "America/Guatemala",
    "Central Standard Time": "America/Chicago",
    "Easter Island Standard Time": "Pacific/Easter",
    "Central Standard Time (Mexico)": "America/Mexico_City",
    "Canada Central Standard Time": "America/Regina",
    "SA Pacific Standard Time": "America/Bogota",
    "Eastern Standard Time (Mexico)": "America/Cancun",
    "Eastern Standard Time": "America/New_York",
    "Haiti Standard Time": "America/Port-au-Prince",
    "Cuba Standard Time": "America/Havana",
    "US Eastern Standard Time": "America/Indianapolis",
    "Turks And Caicos Standard Time": "America/Grand_Turk",
    "Paraguay Standard Time": "America/Asuncion",
    "Atlantic Standard Time": "America/Halifax",
    "Venezuela Standard Time": "America/Caracas",
    "Central Brazilian Standard Time": "America/Cuiaba",
    "SA Western Standard Time": "America/La_Paz",
    "Pacific SA Standard Time": "America/Santiago",
    "Newfoundland Standard Time": "America/St_Johns",
    "Tocantins Standard Time": "America/Araguaina",
    "E. South America Standard Time": "America/Sao_Paulo",
    "SA Eastern Standard Time": "America/Cayenne",
    "Argentina Standard Time": "America/Buenos_Aires",
    "Greenland Standard Time": "America/Godthab",
    "Montevideo Standard Time": "America/Montevideo",
    "Magallanes Standard Time": "America/Punta_Arenas",
    "Saint Pierre Standard Time": "America/Miquelon",
    "Bahia Standard Time": "America/Bahia",
    "UTC-02": "Etc/GMT+2",
    "Mid-Atlantic Standard Time": "Atlantic/South_Georgia",
    "Azores Standard Time": "Atlantic/Azores",
    "Cape Verde Standard Time": "Atlantic/Cape_Verde",
    "UTC": "Etc/UTC",
    "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "Sao Tome Standard Time": "Africa/Sao_Tome",
    "Morocco Standard Time": "Africa/Casablanca",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest",
    "Romance Standard Time": "Europe/Paris",
    "Central European Standard Time": "Europe/Warsaw",
    "W. Central Africa Standard Time": "Africa/Lagos",
    "Jordan Standard Time": "Asia/Amman",
    "GTB Standard Time": "Europe/Bucharest",
    "Middle East Standard Time": "Asia/Beirut",
    "Egypt Standard Time": "Africa/Cairo",
    "E. Europe Standard Time": "Europe/Chisinau",
    "Syria Standard Time": "Asia/Damascus",
    "West Bank Standard Time": "Asia/Hebron",
    "South Africa Standard Time": "Africa/Johannesburg",
    "FLE Standard Time": "Europe/Kiev",
    "Israel Standard Time": "Asia/Jerusalem",
    "Kaliningrad Standard Time": "Europe/Kaliningrad",
    "Sudan Standard Time": "Africa/Khartoum",
    "Libya Standard Time": "Africa/Tripoli",
    "Namibia Standard Time": "Africa/Windhoek",
    "Arabic Standard Time": "Asia/Baghdad",
    "Turkey Standard Time": "Europe/Istanbul",
    "Arab Standard Time": "Asia/Riyadh",
    "Belarus Standard Time": "Europe/Minsk",
    "Russian Standard Time": "Europe/Moscow",
    "E. Africa Standard Time": "Africa/Nairobi",
    "Iran Standard Time": "Asia/Tehran",
    "Arabian Standard Time": "Asia/Dubai",
    "Astrakhan Standard Time": "Europe/Astrakhan",
    "Azerbaijan Standard Time": "Asia/Baku",
    "Russia Time Zone 3": "Europe/Samara",
    "Mauritius Standard Time": "Indian/Mauritius",
    "Saratov Standard Time": "Europe/Saratov",
    "Georgian Standard Time": "Asia/Tbilisi",
    "Volgograd Standard Time": "Europe/Volgograd",
    "Caucasus Standard Time": "Asia/Yerevan",
    "Afghanistan Standard Time": "Asia/Kabul",
    "West Asia Standard Time": "Asia/Tashkent",
    "Ekaterinburg Standard Time": "Asia/Yekaterinburg",
    "Pakistan Standard Time": "Asia/Karachi",
    "Qyzylorda Standard Time": "Asia/Qyzylorda",
    "India Standard Time": "Asia/Kolkata",
    "Sri Lanka Standard Time": "Asia/Colombo",
    "Nepal Standard Time": "Asia/Kathmandu",
    "Central Asia Standard Time": "Asia/Almaty",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "Omsk Standard Time": "Asia/Omsk",
    "Myanmar Standard Time": "Asia/Yangon",
    "SE Asia Standard Time": "Asia/Bangkok",
    "Altai Standard Time": "Asia/Barnaul",
    "W. Mongolia Standard Time": "Asia/Hovd",
    "North Asia Standard Time": "Asia/Krasnoyarsk",
    "N. Central Asia Standard Time": "Asia/Novosibirsk",
    "Tomsk Standard Time": "Asia/Tomsk",
    "China Standard Time": "Asia/Shanghai",
    "North Asia East Standard Time": "Asia/Irkutsk",
    "Singapore Standard Time": "Asia/Singapore",
    "W. Australia Standard Time": "Australia/Perth",
    "Taipei Standard Time": "Asia/Taipei",
    "Ulaanbaatar Standard Time": "Asia/Ulaanbaatar",
    "Aus Central W. Standard Time": "Australia/Eucla",
    "Transbaikal Standard Time": "Asia/Chita",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "Yakutsk Standard Time": "Asia/Yakutsk",
    "Cen. Australia Standard Time": "Australia/Adelaide",
    "AUS Central Standard Time": "Australia/Darwin",
    "E. Australia Standard Time": "Australia/Brisbane",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "West Pacific Standard Time": "Pacific/Port_Moresby",
    "Tasmania Standard Time": "Australia/Hobart",
    "Vladivostok Standard Time": "Asia/Vladivostok",
    "Lord Howe Standard Time": "Australia/Lord_Howe",
    "Bougainville Standard Time": "Pacific/Bougainville",
    "Russia Time Zone 10": "Asia/Srednekolymsk",
    "Magadan Standard Time": "Asia/Magadan",
    "Norfolk Standard Time": "Pacific/Norfolk",
    "Sakhalin Standard Time": "Asia/Sakhalin",
    "Central Pacific Standard Time": "Pacific/Guadalcanal",
    "Russia Time Zone 11": "Asia/Kamchatka",
    "New Zealand Standard Time": "Pacific/Auckland",
    "UTC+12": "Etc/GMT-12",
    "Fiji Standard Time": "Pacific/Fiji",
    "Chatham Islands Standard Time": "Pacific/Chatham",
    "UTC+13": "Etc/GMT-13",
    "Tonga Standard Time": "Pacific/Tongatapu",
    "Samoa Standard Time": "Pacific/Apia",
    "Line Islands Standard Time": "Pacific/Kiritimati",
}


KNOWN_FIXED_OFFSET_REPRESENTATIVES: Dict[int, tuple[str, str, Sequence[str]]] = {
    -14 * 60: ("Baker Island / Howland Island", "Representative region", ("baker", "howland", "line west")),
    -12 * 60: ("Baker Island / Howland Island", "Representative region", ("baker", "howland", "utc-12")),
    -11 * 60: ("Pago Pago / Niue", "American Samoa / Niue", ("pago pago", "niue", "samoa")),
    -10 * 60: ("Honolulu / Tahiti", "Hawaii / French Polynesia", ("honolulu", "tahiti", "hawaii")),
    -9 * 60 - 30: ("Marquesas Islands", "French Polynesia", ("marquesas", "french polynesia")),
    -9 * 60: ("Anchorage / Gambier", "Alaska (winter) / Gambier", ("anchorage", "gambier", "alaska")),
    -8 * 60: ("Los Angeles / Vancouver", "Pacific coast (winter)", ("los angeles", "vancouver", "pacific")),
    -7 * 60: ("Phoenix / Denver", "Southwest US / Rockies", ("phoenix", "denver", "rockies")),
    -6 * 60: ("Chicago / Mexico City", "Central North America", ("chicago", "mexico city", "central")),
    -5 * 60: ("New York / Lima / Bogotá", "Eastern Americas", ("new york", "lima", "bogota")),
    -4 * 60: ("Halifax / Caracas", "Atlantic Canada / northern South America", ("halifax", "caracas", "atlantic")),
    -3 * 60 - 30: ("St. John's", "Newfoundland", ("st. john's", "newfoundland")),
    -3 * 60: ("Buenos Aires / São Paulo", "Southern South America", ("buenos aires", "sao paulo", "south america")),
    -2 * 60: ("South Georgia / Fernando de Noronha", "South Atlantic", ("south georgia", "fernando de noronha")),
    -60: ("Azores / Cape Verde", "Atlantic islands", ("azores", "cape verde", "atlantic")),
    0: ("London / Lisbon / Reykjavík", "Western Europe / Atlantic", ("london", "lisbon", "reykjavik")),
    60: ("Berlin / Paris / Rome", "Central Europe", ("berlin", "paris", "rome")),
    120: ("Athens / Bucharest / Cairo", "Eastern Europe / eastern Mediterranean", ("athens", "bucharest", "cairo")),
    180: ("Moscow / Istanbul / Riyadh", "Eastern Europe / Middle East", ("moscow", "istanbul", "riyadh")),
    210: ("Tehran", "Iran", ("tehran", "iran")),
    240: ("Dubai / Baku", "Arabian Gulf / Caucasus", ("dubai", "baku", "uae")),
    270: ("Kabul", "Afghanistan", ("kabul", "afghanistan")),
    300: ("Karachi / Tashkent", "Pakistan / Central Asia", ("karachi", "tashkent", "pakistan")),
    330: ("Delhi / Colombo", "India / Sri Lanka", ("delhi", "colombo", "india")),
    345: ("Kathmandu", "Nepal", ("kathmandu", "nepal")),
    360: ("Dhaka / Almaty", "Bangladesh / Central Asia", ("dhaka", "almaty")),
    390: ("Yangon", "Myanmar", ("yangon", "myanmar")),
    420: ("Bangkok / Jakarta", "Thailand / western Indonesia", ("bangkok", "jakarta")),
    480: ("Beijing / Singapore / Perth", "East Asia / western Australia", ("beijing", "singapore", "perth")),
    525: ("Eucla", "Western Australia (UTC+08:45)", ("eucla", "australia")),
    540: ("Seoul / Tokyo", "Korea / Japan", ("seoul", "tokyo", "korea", "japan")),
    570: ("Darwin / Adelaide", "Northern / central Australia", ("darwin", "adelaide", "australia")),
    600: ("Sydney / Port Moresby", "Eastern Australia / Papua New Guinea", ("sydney", "port moresby")),
    630: ("Lord Howe Island", "Australia", ("lord howe", "australia")),
    660: ("Nouméa / Solomon Islands", "Southwest Pacific", ("noumea", "solomon")),
    720: ("Auckland / Fiji", "New Zealand / Fiji", ("auckland", "fiji")),
    765: ("Chatham Islands", "New Zealand", ("chatham", "new zealand")),
    780: ("Apia / Tongatapu", "Samoa / Tonga", ("apia", "tongatapu", "tonga")),
    840: ("Kiritimati", "Line Islands", ("kiritimati", "line islands")),
}


def _load_catalog_file(path: Path) -> List[TimezoneEntry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries: List[TimezoneEntry] = []
    for item in data:
        entries.append(
            TimezoneEntry(
                value=str(item["value"]),
                city=str(item.get("city") or item["value"]),
                region=str(item.get("region") or ""),
                base_offset_minutes=int(item["base_offset_minutes"]),
                keywords=tuple(str(keyword) for keyword in item.get("keywords", [])),
            )
        )
    return entries


def parse_fixed_offset_minutes(zone_name: str) -> Optional[int]:
    text = zone_name.strip().upper().replace("GMT", "UTC")
    if not text.startswith("UTC"):
        return None
    if text == "UTC":
        return 0
    remainder = text[3:]
    if not remainder:
        return 0
    sign = 1
    if remainder[0] == "+":
        remainder = remainder[1:]
    elif remainder[0] == "-":
        sign = -1
        remainder = remainder[1:]
    parts = remainder.split(":", 1)
    try:
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        return None
    if hours > 14 or minutes not in {0, 15, 30, 45}:
        return None
    total = sign * (hours * 60 + minutes)
    if total < -14 * 60 or total > 14 * 60:
        return None
    return total


def fixed_offset_value(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    total = abs(minutes)
    return f"UTC{sign}{total // 60:02d}:{total % 60:02d}"


def _parse_etc_gmt(zone_name: str) -> Optional[int]:
    if not zone_name.startswith("Etc/GMT"):
        return None
    suffix = zone_name[7:]
    if not suffix:
        return 0
    try:
        sign = -1 if suffix[0] == "+" else 1
        hours = int(suffix[1:])
    except Exception:
        return None
    return sign * hours * 60


def _nearest_known_fixed_offset(minutes: int) -> tuple[str, str, Sequence[str]]:
    best_key = min(KNOWN_FIXED_OFFSET_REPRESENTATIVES, key=lambda key: abs(key - minutes))
    return KNOWN_FIXED_OFFSET_REPRESENTATIVES[best_key]


def _representative_for_fixed_offset(minutes: int) -> tuple[str, str, Sequence[str]]:
    direct = KNOWN_FIXED_OFFSET_REPRESENTATIVES.get(minutes)
    if direct is not None:
        return direct
    near_city, _near_region, near_keywords = _nearest_known_fixed_offset(minutes)
    return (
        fixed_offset_value(minutes),
        f"Custom fixed offset · near {near_city}",
        ("custom", "fixed", *near_keywords),
    )


def _friendly_parts(zone_name: str) -> tuple[str, str, tuple[str, ...]]:
    etc_offset = _parse_etc_gmt(zone_name)
    if etc_offset is not None:
        city, region, keywords = _representative_for_fixed_offset(etc_offset)
        return city, f"{fixed_offset_value(etc_offset)} · {region}", tuple(keywords)

    cleaned = zone_name.replace("_", " ")
    parts = cleaned.split("/")
    city = parts[-1]
    region = " / ".join(parts[:-1]) if len(parts) > 1 else "IANA"
    keywords = tuple(part for part in parts if part)
    return city, region, keywords


def _fixed_offset_entries() -> List[TimezoneEntry]:
    entries: List[TimezoneEntry] = []
    for minutes in range(-14 * 60, 14 * 60 + 1, 15):
        value = fixed_offset_value(minutes)
        city, region, keywords = _representative_for_fixed_offset(minutes)
        entries.append(
            TimezoneEntry(
                value=value,
                city=city,
                region=region,
                base_offset_minutes=minutes,
                keywords=("utc", "gmt", "fixed", *tuple(keywords)),
            )
        )
    return entries


def _dynamic_zone_entries() -> List[TimezoneEntry]:
    zone_names = sorted(
        zone_name
        for zone_name in available_timezones()
        if zone_name
        and not zone_name.startswith(("posix/", "right/", "SystemV/"))
        and zone_name not in {"Factory", "localtime"}
    )
    entries: List[TimezoneEntry] = []
    for zone_name in zone_names:
        city, region, keywords = _friendly_parts(zone_name)
        offset = current_offset_minutes(zone_name, 0)
        entries.append(
            TimezoneEntry(
                value=zone_name,
                city=city,
                region=region,
                base_offset_minutes=offset,
                keywords=keywords,
            )
        )
    return entries


def load_timezone_catalog() -> List[TimezoneEntry]:
    global _TIMEZONE_CACHE
    if _TIMEZONE_CACHE is not None:
        return list(_TIMEZONE_CACHE)

    entries: List[TimezoneEntry] = []
    try:
        entries.extend(_dynamic_zone_entries())
    except Exception:
        entries = []

    if not entries:
        entries.extend(_load_catalog_file(resource_path("timezones.json")))

    by_value: Dict[str, TimezoneEntry] = {entry.value: entry for entry in entries}
    for entry in _fixed_offset_entries():
        by_value.setdefault(entry.value, entry)

    _TIMEZONE_CACHE = list(by_value.values())
    return list(_TIMEZONE_CACHE)


def current_offset_minutes(zone_name: str, fallback: int) -> int:
    parsed_fixed = parse_fixed_offset_minutes(zone_name)
    if parsed_fixed is not None:
        return parsed_fixed
    etc_fixed = _parse_etc_gmt(zone_name)
    if etc_fixed is not None:
        return etc_fixed
    try:
        tz = ZoneInfo(zone_name)
        now = datetime.now(tz)
        offset = now.utcoffset()
        if offset is None:
            return fallback
        return int(offset.total_seconds() // 60)
    except Exception:
        return fallback


def format_gmt_offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    abs_minutes = abs(minutes)
    hours = abs_minutes // 60
    mins = abs_minutes % 60
    return f"GMT{sign}{hours:02d}:{mins:02d}"


def entry_sort_key(entry: TimezoneEntry) -> tuple[int, int, str, str]:
    offset = current_offset_minutes(entry.value, entry.base_offset_minutes)
    is_fixed = 1 if (parse_fixed_offset_minutes(entry.value) is not None or _parse_etc_gmt(entry.value) is not None) else 0
    return (offset, is_fixed, entry.city.lower(), entry.value.lower())


def build_timezone_label(entry: TimezoneEntry) -> str:
    offset = current_offset_minutes(entry.value, entry.base_offset_minutes)
    is_fixed = parse_fixed_offset_minutes(entry.value) is not None
    if is_fixed:
        if entry.city != entry.value:
            return f"({format_gmt_offset(offset)}) {entry.city} — {entry.value} · {entry.region}"
        return f"({format_gmt_offset(offset)}) {entry.value} — {entry.region}"
    if entry.region:
        return f"({format_gmt_offset(offset)}) {entry.city} — {entry.value}"
    return f"({format_gmt_offset(offset)}) {entry.city}"


def timezone_search_blob(entry: TimezoneEntry) -> str:
    parts = [
        entry.city,
        entry.region,
        entry.value,
        *entry.keywords,
        build_timezone_label(entry),
        format_gmt_offset(entry.base_offset_minutes),
    ]
    return " ".join(part for part in parts if part).casefold()


def _normalize_timezone_candidate(value: str) -> Optional[str]:
    text = str(value).strip()
    if not text:
        return None
    if text in {SYSTEM_TIMEZONE, "system", "auto"}:
        return SYSTEM_TIMEZONE

    fixed_minutes = parse_fixed_offset_minutes(text)
    if fixed_minutes is not None:
        return fixed_offset_value(fixed_minutes)

    mapped = WINDOWS_TZ_TO_IANA.get(text)
    if mapped:
        return mapped

    if text in {entry.value for entry in load_timezone_catalog()}:
        return text

    alt = text.replace("\\", "/")
    if alt in {entry.value for entry in load_timezone_catalog()}:
        return alt

    try:
        ZoneInfo(text)
        return text
    except Exception:
        return None


def _macos_system_timezone_candidates() -> Iterable[str]:
    if sys.platform != "darwin":
        return ()
    commands = [
        ["/usr/sbin/systemsetup", "-gettimezone"],
        ["/usr/sbin/scutil", "--get", "TimeZone"],
    ]
    out: List[str] = []
    for command in commands:
        try:
            completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=1.5)
        except Exception:
            continue
        if completed.returncode != 0:
            continue
        text = completed.stdout.strip()
        if not text:
            continue
        if "Time Zone:" in text:
            text = text.split(":", 1)[1].strip()
        out.append(text)
    return tuple(out)


def _linux_system_timezone_candidates() -> Iterable[str]:
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return ()
    out: List[str] = []
    for path in (Path("/etc/timezone"),):
        try:
            if path.exists():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    out.append(value)
        except Exception:
            pass
    for link_path in (Path("/etc/localtime"), Path("/var/db/timezone/localtime")):
        try:
            if link_path.is_symlink():
                target = link_path.resolve()
                for marker in ("/zoneinfo/", "\\zoneinfo\\"):
                    text = str(target)
                    if marker in text:
                        out.append(text.split(marker, 1)[1].replace("\\", "/"))
        except Exception:
            pass
    try:
        completed = subprocess.run(["timedatectl", "show", "-p", "Timezone", "--value"], check=False, capture_output=True, text=True, timeout=1.5)
        if completed.returncode == 0 and completed.stdout.strip():
            out.append(completed.stdout.strip())
    except Exception:
        pass
    return tuple(out)


def _windows_system_timezone_candidates() -> Iterable[str]:
    if not sys.platform.startswith("win"):
        return ()
    out: List[str] = []
    try:
        completed = subprocess.run(["tzutil", "/g"], check=False, capture_output=True, text=True, timeout=1.5)
        if completed.returncode == 0 and completed.stdout.strip():
            out.append(completed.stdout.strip())
    except Exception:
        pass
    try:
        tzinfo = datetime.now().astimezone().tzinfo
        key = getattr(tzinfo, "key", None)
        if key:
            out.append(str(key))
    except Exception:
        pass
    return tuple(out)


def detect_system_timezone() -> Optional[str]:
    candidates: List[str] = []
    tz_env = os.environ.get("TZ")
    if tz_env:
        candidates.append(tz_env)
    candidates.extend(_windows_system_timezone_candidates())
    candidates.extend(_macos_system_timezone_candidates())
    candidates.extend(_linux_system_timezone_candidates())
    try:
        tzinfo = datetime.now().astimezone().tzinfo
        key = getattr(tzinfo, "key", None)
        if key:
            candidates.append(str(key))
        name = tzinfo.tzname(datetime.now().astimezone()) if tzinfo is not None else None
        if name:
            candidates.append(str(name))
    except Exception:
        pass

    for candidate in candidates:
        normalized = _normalize_timezone_candidate(candidate)
        if normalized and normalized != SYSTEM_TIMEZONE:
            return normalized
    return None


def resolved_timezone_value(value: Optional[str], *, fallback: str) -> str:
    normalized = _normalize_timezone_candidate(value or "")
    if normalized == SYSTEM_TIMEZONE or not normalized:
        return detect_system_timezone() or fallback
    return normalized


def system_timezone_label(*, fallback: str) -> str:
    value = detect_system_timezone() or fallback
    entry = find_timezone_entry(value)
    if entry is None:
        return value
    return build_timezone_label(entry)


def sorted_timezone_entries() -> List[TimezoneEntry]:
    entries = load_timezone_catalog()
    entries.sort(key=entry_sort_key)
    return entries


def timezone_label_map() -> Dict[str, str]:
    return {entry.value: build_timezone_label(entry) for entry in sorted_timezone_entries()}


def find_timezone_entry(value: str) -> Optional[TimezoneEntry]:
    for entry in load_timezone_catalog():
        if entry.value == value:
            return entry
    return None


def timezone_values() -> Iterable[str]:
    for entry in sorted_timezone_entries():
        yield entry.value
