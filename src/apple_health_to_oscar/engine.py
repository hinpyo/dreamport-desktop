#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Core conversion engine for Apple Health -> OSCAR CSV generation.

This module is intentionally close to the original single-file `oscar.py` logic.
The goal of this refactor is separation of concerns, not algorithmic change:
- core session reconstruction and CSV output stay here;
- CLI lives in `cli.py`;
- Tkinter desktop GUI lives in `gui.py`.
"""

from __future__ import annotations

import csv
import hashlib
import math
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union
from zoneinfo import ZoneInfo

from .timezones import parse_fixed_offset_minutes


# ======================================================================================
# 기본 설정
# ======================================================================================

DEFAULT_OUTPUT_DIR_NAME = "output"
DEFAULT_DREEM_DIR_NAME = "Dreem"
DEFAULT_ZEO_DIR_NAME = "ZEO"
DEFAULT_MANIFEST_FILENAME = "apple_watch_to_oscar_manifest.csv"

DEFAULT_TIMEZONE = "Asia/Seoul"
DEFAULT_NIGHT_START = time(19, 0, 0)
DEFAULT_NIGHT_END = time(11, 0, 0)
DEFAULT_OSCAR_DAY_SPLIT = time(12, 0, 0)
DEFAULT_CLUSTER_GAP_HOURS = 4.0
DEFAULT_INCREMENTAL_OVERLAP_DAYS = 3
DEFAULT_PREFIX = "AppleWatch_OSCAR"
DEFAULT_GENERIC_ASLEEP_AS = "light"
DEFAULT_GAP_POLICY = "na"
MANIFEST_VERSION = "4"

WATCH_HINTS = (
    "applewatch",
    "apple watch",
    "watchultra",
    "watchse",
    "watch",
    "애플워치",
    "시계",
)

GENERIC_SOURCE_NAMES = {
    "health",
    "applehealth",
    "sleep",
    "수면",
    "건강",
}

SLEEP_STAGE_SET = {"REM", "Light", "Deep"}
SPECIFIC_STAGE_SET = {"WAKE", "REM", "Light", "Deep"}

DREEM_HEADER = [
    "Type",
    "Start Time",
    "Stop Time",
    "Sleep Duration",
    "Sleep Onset Duration",
    "Light Sleep Duration",
    "Deep Sleep Duration",
    "REM Duration",
    "Wake After Sleep Onset Duration",
    "Number of awakenings",
    "Position Changes",
    "Mean Heart Rate",
    "Mean Respiration CPM",
    "Number of Stimulations",
    "Sleep efficiency",
    "Hypnogram",
]

ZEO_HEADER = [
    "ZQ",
    "Total Z",
    "Time to Z",
    "Time in Wake",
    "Time in REM",
    "Time in Light",
    "Time in Deep",
    "Awakenings",
    "Sleep Graph",
    "Detailed Sleep Graph",
    "Start of Night",
    "End of Night",
    "Rise Time",
    "Alarm Reason",
    "Snooze Time",
    "Wake Tone",
    "Wake Window",
    "Alarm Type",
    "First Alarm Ring",
    "Last Alarm Ring",
    "First Snooze Time",
    "Last Snooze Time",
    "Set Alarm Time",
    "Morning Feel",
    "Firmware Version",
    "My ZEO Version",
]

ZEO_STAGE_MAP = {
    "NA": "0",
    "WAKE": "1",
    "REM": "2",
    "Light": "3",
    "Deep": "4",
}

ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


# ======================================================================================
# 데이터 구조
# ======================================================================================

@dataclass(frozen=True)
class SleepEntry:
    """원시 수면 레코드 1개."""

    start: datetime
    end: datetime
    stage: str
    priority: int
    raw_stage: str
    source_name: str
    device: str
    source_family: str
    origin: str


@dataclass
class Bucket:
    """시간적으로 가까운 원시 레코드 묶음.

    한 밤의 실제 수면 세션(혹은 낮잠)을 복원하기 위한 임시 버킷이다.
    이 버킷 안에는 여러 source 가 섞여 있을 수 있고,
    그중 가장 적절한 source family 를 나중에 고른다.
    """

    start: datetime
    end: datetime
    entries: List[SleepEntry]


@dataclass
class NightSession:
    """최종 출력 세션."""

    apple_date: date
    oscar_date: date
    source_summary: str
    start_time: datetime
    stop_time: datetime
    applied_shift_seconds: int
    epochs: List[str]
    sleep_duration: timedelta
    sleep_onset_duration: timedelta
    light_duration: timedelta
    deep_duration: timedelta
    rem_duration: timedelta
    wake_after_sleep_onset: timedelta
    awakenings: int
    sleep_efficiency: int
    session_key: str
    content_hash: str
    dreem_file: Optional[Path] = None
    zeo_file: Optional[Path] = None


@dataclass
class ExistingManifestRow:
    """기존 manifest 1행."""

    row: dict
    session_key: str
    content_hash: str
    dreem_file: Optional[Path]
    zeo_file: Optional[Path]


@dataclass
class RunStats:
    """실행 요약."""

    parsed_records: int = 0
    selected_records: int = 0
    provisional_buckets: int = 0
    final_sessions: int = 0
    files_written: int = 0
    files_reused: int = 0
    migrated_files: int = 0
    rebuild_all: bool = False
    incremental_cutoff: Optional[datetime] = None
    chosen_sources: Counter = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.chosen_sources is None:
            self.chosen_sources = Counter()


LogCallback = Optional[Callable[[str], None]]


@dataclass
class ConversionConfig:
    """GUI / CLI 공용 변환 설정.

    참고:
    - night_start/night_end 는 기존 README/UI 호환을 위해 유지한다.
      현재 엔진의 실제 세션 복원은 cluster_gap_hours 기반으로 동작하며,
      기본 동작을 보존하기 위해 이 두 값은 계산 로직에 강제로 개입하지 않는다.
    """

    input_path: Optional[Union[str, Path]] = None
    output_dir: Union[str, Path] = DEFAULT_OUTPUT_DIR_NAME
    output_format: str = "both"
    timezone: str = DEFAULT_TIMEZONE
    night_start: Union[str, time] = DEFAULT_NIGHT_START
    night_end: Union[str, time] = DEFAULT_NIGHT_END
    oscar_day_split: Union[str, time] = DEFAULT_OSCAR_DAY_SPLIT
    cluster_gap_hours: float = DEFAULT_CLUSTER_GAP_HOURS
    from_dt: Optional[Union[str, datetime]] = None
    to_dt: Optional[Union[str, datetime]] = None
    source_contains: Optional[str] = None
    shift_seconds: int = 0
    align_start: Optional[Union[str, datetime]] = None
    align_onset: Optional[Union[str, datetime]] = None
    gap_policy: str = DEFAULT_GAP_POLICY
    generic_asleep_as: str = DEFAULT_GENERIC_ASLEEP_AS
    prefix: str = DEFAULT_PREFIX
    incremental_overlap_days: int = DEFAULT_INCREMENTAL_OVERLAP_DAYS
    rebuild_all: bool = False


@dataclass
class ConversionResult:
    """변환 실행 결과."""

    config: ConversionConfig
    input_path: Path
    output_dir: Path
    manifest_path: Path
    source_summary: str
    stats: RunStats
    sessions: List[NightSession]
    summary_lines: List[str]


# ======================================================================================
# 문자열 / 시간 유틸
# ======================================================================================


def safe_zoneinfo(name: Optional[str]) -> Optional[tzinfo]:
    """문자열 타임존을 ZoneInfo 또는 고정 UTC 오프셋으로 바꾼다."""
    if not name:
        return None

    fixed_minutes = parse_fixed_offset_minutes(str(name))
    if fixed_minutes is not None:
        return timezone(timedelta(minutes=fixed_minutes), name=str(name))

    try:
        return ZoneInfo(name)
    except Exception:
        return None



def get_local_timezone() -> tzinfo:
    """실행 환경의 로컬 타임존."""
    tz = datetime.now().astimezone().tzinfo
    if tz is None:
        raise RuntimeError("로컬 타임존을 확인하지 못했습니다.")
    return tz



def normalize_text(text: Optional[str]) -> str:
    """느슨한 비교용 정규화 문자열."""
    if text is None:
        return ""
    value = str(text)
    value = value.casefold()
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[_\-/:;'\".,;(){}\[\]<>|]+", "", value)
    return value



def insert_colon_into_offset(text: str) -> str:
    """+0900 -> +09:00 형태로 바꿔 datetime 파서를 돕는다."""
    return re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)



def parse_datetime_loose(text: Optional[str], default_tz: Optional[tzinfo]) -> Optional[datetime]:
    """여러 날짜 문자열 형식을 느슨하게 해석한다."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None

    candidates = [raw, insert_colon_into_offset(raw), raw.replace("Z", "+00:00")]
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None and default_tz is not None:
                dt = dt.replace(tzinfo=default_tz)
            return dt
        except ValueError:
            pass

    formats = [
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M %z",
        "%Y-%m-%d %H:%M%z",
        "%Y-%m-%dT%H:%M%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ]
    raw_fixed = insert_colon_into_offset(raw)
    for fmt in formats:
        try:
            dt = datetime.strptime(raw_fixed, fmt)
            if dt.tzinfo is None and default_tz is not None:
                dt = dt.replace(tzinfo=default_tz)
            return dt
        except ValueError:
            continue

    raise ValueError(f"날짜/시간을 해석할 수 없습니다: {text}")



def parse_hhmm(text: str) -> time:
    """HH:MM 또는 HH:MM:SS 를 time 으로 변환한다."""
    raw = text.strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"시각 형식을 해석할 수 없습니다: {text}")



def parse_bound_datetime(raw: Optional[str], default_tz: tzinfo, fallback_time: Optional[time]) -> Optional[datetime]:
    """--from / --to 용 경계 시각 파서."""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None

    dt = parse_datetime_loose(text, default_tz)
    if dt is None:
        return None

    # 날짜만 들어오면 fallback_time 을 붙인다.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) and fallback_time is not None:
        dt = dt.replace(
            hour=fallback_time.hour,
            minute=fallback_time.minute,
            second=fallback_time.second,
            microsecond=0,
        )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt



def isoformat_with_offset(dt: datetime) -> str:
    """타임존 포함 ISO 문자열(초 단위)."""
    return dt.isoformat(timespec="seconds")



def format_td_hms(td: timedelta) -> str:
    """timedelta -> H:MM:SS."""
    total_seconds = max(0, int(round(td.total_seconds())))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours}:{minutes:02d}:{seconds:02d}"



def td_to_minutes(td: timedelta) -> int:
    """timedelta -> 분."""
    total_seconds = max(0, int(round(td.total_seconds())))
    return total_seconds // 60



def zeo_time(dt: Optional[datetime]) -> str:
    """Zeo CSV 용 시각 문자열."""
    if dt is None:
        return ""
    return dt.strftime("%m/%d/%Y %H:%M")



def make_safe_filename(text: str) -> str:
    """안전한 파일명 문자열 생성."""
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "_", text)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "output"



def hash_text(text: str) -> str:
    """짧은 안정적 해시."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


# ======================================================================================
# 입력 파일 열기
# ======================================================================================


def resolve_default_input(script_dir: Path) -> Path:
    """루트 폴더에서 export.xml / export.zip 을 자동 선택한다.

    둘 다 있으면 수정 시각이 더 최신인 파일을 우선한다.
    """
    candidates = []
    for name in ("export.xml", "export.zip"):
        path = script_dir / name
        if path.exists() and path.is_file():
            candidates.append(path)

    if not candidates:
        raise FileNotFoundError(
            f"{script_dir} 안에서 export.xml 또는 export.zip 을 찾지 못했습니다."
        )

    candidates.sort(key=lambda p: (p.stat().st_mtime, p.suffix.lower() == ".zip"), reverse=True)
    return candidates[0]


@contextmanager
def open_export_xml_stream(path: Path) -> Iterator[Iterable[bytes]]:
    """export.xml 또는 export.zip 안의 export.xml 스트림을 연다."""
    suffix = path.suffix.casefold()

    if suffix == ".xml":
        with path.open("rb") as f:
            yield f
        return

    if suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            xml_name = None
            for candidate in zf.namelist():
                if Path(candidate).name == "export.xml":
                    xml_name = candidate
                    break
            if xml_name is None:
                xml_candidates = [n for n in zf.namelist() if n.casefold().endswith(".xml")]
                if not xml_candidates:
                    raise FileNotFoundError(f"{path} 안에서 XML 파일을 찾지 못했습니다.")
                xml_name = xml_candidates[0]

            with zf.open(xml_name, "r") as f:
                yield f
        return

    raise ValueError(f"지원하지 않는 입력 형식입니다: {path}")


# ======================================================================================
# 수면 단계 정규화
# ======================================================================================


def canonicalize_stage(raw_stage: Optional[str], generic_asleep_as: str = "light") -> Tuple[str, int]:
    """여러 stage 표현을 OSCAR 호환 label 로 바꾼다.

    반환값
    - stage: NA / WAKE / REM / Light / Deep
    - priority: 겹치는 구간 우선순위
    """
    norm = normalize_text(raw_stage)
    if not norm:
        return "NA", 0

    if "hkcategoryvaluesleepanalysisasleeprem" in norm or norm.endswith("asleeprem") or norm == "rem" or "rem수면" in norm:
        return "REM", 4
    if "hkcategoryvaluesleepanalysisasleepdeep" in norm or norm.endswith("asleepdeep") or norm == "deep" or "깊" in norm or "심층" in norm:
        return "Deep", 4
    if "hkcategoryvaluesleepanalysisasleepcore" in norm or norm.endswith("asleepcore") or norm == "core" or norm == "light" or "코어" in norm or "얕" in norm:
        return "Light", 4

    if "hkcategoryvaluesleepanalysisawake" in norm or norm == "awake" or norm == "wake" or "깨어" in norm or "각성" in norm:
        return "WAKE", 3
    if "hkcategoryvaluesleepanalysisinbed" in norm or norm == "inbed" or ("침대" in norm and "깨어" not in norm):
        return "WAKE", 1

    if (
        "hkcategoryvaluesleepanalysisasleepunspecified" in norm
        or "hkcategoryvaluesleepanalysisasleep" in norm
        or norm == "asleep"
        or norm.endswith("asleep")
        or norm == "sleep"
        or norm == "수면"
        or norm == "잠"
    ):
        if generic_asleep_as == "na":
            return "NA", 0
        return "Light", 2

    if norm in {"w", "wakeup"}:
        return "WAKE", 3
    if norm in {"r"}:
        return "REM", 4
    if norm in {"d"}:
        return "Deep", 4
    if norm in {"l", "n1", "n2"}:
        return "Light", 4

    return "NA", 0



def looks_like_apple_watch(source_name: str, device: str) -> bool:
    """source/device 문자열을 보고 Apple Watch 계열인지 느슨하게 판정한다."""
    combined = " ".join([source_name or "", device or ""])
    norm = normalize_text(combined)

    if not norm:
        return False

    if any(normalize_text(hint) in norm for hint in WATCH_HINTS):
        return True

    if re.search(r"watch\d+(,\d+)?", norm):
        return True

    if "apple" in norm and "watch" in norm:
        return True

    return False



def source_family_key_from_text(source_name: str, device: str, origin: str) -> str:
    """source 선택용 느슨한 family key.

    같은 Apple Watch 도 export 시점에 따라 sourceName/device 문자열이 조금씩 바뀔 수 있어서,
    너무 엄격하게 묶으면 특정 날짜 이후 데이터가 빠질 수 있다.
    """
    norm_source = normalize_text(source_name)
    norm_device = normalize_text(device)

    if norm_device:
        hardware_match = re.search(r"watch\d+(?:,\d+)?", norm_device)
        if hardware_match:
            return hardware_match.group(0)
        if "applewatch" in norm_device or "watch" in norm_device:
            return "applewatch"

    if norm_source and norm_source not in GENERIC_SOURCE_NAMES:
        return norm_source

    if looks_like_apple_watch(source_name, device):
        return "applewatch"

    if norm_device:
        return norm_device
    if norm_source:
        return norm_source
    return normalize_text(origin) or "(unknown)"



def logical_source_label(entry: SleepEntry) -> str:
    """사람이 보기 쉬운 source 라벨."""
    if entry.source_name and entry.device:
        if normalize_text(entry.source_name) in normalize_text(entry.device):
            return entry.source_name
        return f"{entry.source_name} | {entry.device}"
    if entry.source_name:
        return entry.source_name
    if entry.device:
        return entry.device
    return entry.origin



def summarize_sources(entries: Sequence[SleepEntry]) -> str:
    """manifest / 콘솔 출력용 source 요약 문자열."""
    labels = Counter(logical_source_label(e) for e in entries if logical_source_label(e))
    if not labels:
        return "(알 수 없는 source)"
    ordered = [label for label, _count in labels.most_common()]
    if len(ordered) <= 3:
        return ", ".join(ordered)
    return ", ".join(ordered[:3]) + f" 외 {len(ordered) - 3}개"



def entry_from_parts(
    *,
    start: Optional[datetime],
    end: Optional[datetime],
    raw_stage: Optional[str],
    source_name: str,
    device: str,
    origin: str,
    output_tz: tzinfo,
    generic_asleep_as: str,
) -> Optional[SleepEntry]:
    """원시 필드를 SleepEntry 로 정규화한다."""
    if start is None or end is None:
        return None
    if end <= start:
        return None

    if start.tzinfo is None:
        start = start.replace(tzinfo=output_tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=output_tz)

    start = start.astimezone(output_tz)
    end = end.astimezone(output_tz)

    stage, priority = canonicalize_stage(raw_stage, generic_asleep_as)
    return SleepEntry(
        start=start,
        end=end,
        stage=stage,
        priority=priority,
        raw_stage=str(raw_stage or ""),
        source_name=str(source_name or "").strip(),
        device=str(device or "").strip(),
        source_family=source_family_key_from_text(source_name or "", device or "", origin),
        origin=origin,
    )


# ======================================================================================
# Apple Health XML 파서
# ======================================================================================


def deduplicate_entries(entries: Sequence[SleepEntry]) -> List[SleepEntry]:
    """완전히 같은 레코드를 제거한다."""
    seen = set()
    out: List[SleepEntry] = []
    for entry in sorted(
        entries,
        key=lambda e: (
            e.start,
            e.end,
            e.stage,
            e.priority,
            e.raw_stage,
            e.source_name,
            e.device,
            e.source_family,
        ),
    ):
        key = (
            entry.start,
            entry.end,
            entry.stage,
            entry.priority,
            entry.raw_stage,
            entry.source_name,
            entry.device,
            entry.source_family,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out



def parse_apple_health_xml(
    input_path: Path,
    output_tz: tzinfo,
    generic_asleep_as: str,
    min_end_dt: Optional[datetime],
    logger: LogCallback = None,
) -> List[SleepEntry]:
    """Apple Health export.xml / export.zip 에서 수면 레코드를 스트리밍으로 읽는다."""
    entries: List[SleepEntry] = []

    with open_export_xml_stream(input_path) as fh:
        file_size: Optional[int] = None
        try:
            current_pos = fh.tell()
            fh.seek(0, 2)
            file_size = fh.tell()
            fh.seek(current_pos)
        except Exception:
            try:
                if input_path.suffix.lower() == ".xml":
                    file_size = int(input_path.stat().st_size)
            except Exception:
                file_size = None

        emitted_percent = -1
        processed_records = 0
        sleep_records_seen = 0

        context = ET.iterparse(fh, events=("end",))
        for _event, elem in context:
            if elem.tag != "Record":
                continue

            processed_records += 1
            if file_size and processed_records % 50 == 0:
                try:
                    current_bytes = int(fh.tell())
                except Exception:
                    current_bytes = 0
                if current_bytes > 0:
                    percent = max(1, min(99, int((current_bytes / max(file_size, 1)) * 100)))
                    bucket = percent - (percent % 2)
                    if bucket > emitted_percent:
                        emitted_percent = bucket
                        _emit(logger, f"XML 파싱 진행: {bucket}% ({sleep_records_seen}개 레코드 발견)")

            if elem.attrib.get("type") != "HKCategoryTypeIdentifierSleepAnalysis":
                elem.clear()
                continue

            hk_tz: Optional[tzinfo] = None
            for child in elem:
                if child.tag == "MetadataEntry" and child.attrib.get("key") == "HKTimeZone":
                    hk_tz = safe_zoneinfo(child.attrib.get("value"))
                    break

            start = parse_datetime_loose(elem.attrib.get("startDate"), hk_tz or output_tz)
            end = parse_datetime_loose(elem.attrib.get("endDate"), hk_tz or output_tz)

            # 증분 실행 시 너무 오래된 레코드는 메모리에 쌓지 않는다.
            if min_end_dt is not None and end is not None:
                end_cut = end if end.tzinfo is not None else end.replace(tzinfo=output_tz)
                if end_cut.astimezone(output_tz) <= min_end_dt:
                    elem.clear()
                    continue

            entry = entry_from_parts(
                start=start,
                end=end,
                raw_stage=elem.attrib.get("value"),
                source_name=str(elem.attrib.get("sourceName", "")),
                device=str(elem.attrib.get("device", "")),
                origin=f"{input_path.name}:sleep",
                output_tz=output_tz,
                generic_asleep_as=generic_asleep_as,
            )
            if entry is not None:
                entries.append(entry)
                sleep_records_seen += 1

            elem.clear()

    return deduplicate_entries(entries)


# ======================================================================================
# source 선택 / 세션 버킷 구성
# ======================================================================================


def filter_entries_by_source(entries: Sequence[SleepEntry], source_contains: Optional[str]) -> Tuple[List[SleepEntry], str]:
    """사용할 source 범위를 1차 필터링한다.

    여기서는 "버리는 범위"를 결정할 뿐, 최종 source 선택은 버킷별로 다시 한다.
    - --source-contains 가 있으면 부분 일치한 것만 유지
    - 없으면 watch-like source 들을 우선 유지
    - 그래도 하나도 없으면 모든 수면 source 를 유지
    """
    if not entries:
        return [], "(없음)"

    if source_contains:
        target = normalize_text(source_contains)
        kept = [
            e for e in entries
            if target in normalize_text(f"{e.source_name} {e.device} {e.source_family}")
        ]
        if not kept:
            available = sorted({logical_source_label(e) for e in entries})
            raise ValueError(
                "--source-contains 와 일치하는 source 를 찾지 못했습니다. "
                f"사용 가능한 source: {', '.join(available)}"
            )
        return kept, summarize_sources(kept)

    watch_entries = [e for e in entries if looks_like_apple_watch(e.source_name, e.device)]
    if watch_entries:
        return watch_entries, summarize_sources(watch_entries)

    return list(entries), summarize_sources(entries)



def build_provisional_buckets(entries: Sequence[SleepEntry], cluster_gap: timedelta) -> List[Bucket]:
    """시간적으로 가까운 레코드를 provisional bucket 으로 묶는다.

    기존 버전은 먼저 "밤 날짜"를 정하고 그 날짜에 레코드를 밀어 넣는 방식이었다.
    그 방식은 날짜 보정이 섞이면 실제 3/9 세션이 아니라 3/8 세션을 골라놓고
    시각만 3/9 로 밀어버리는 버그를 만들기 쉬웠다.

    이번 버전은 반대로,
    1) 먼저 실제 수면 세션 자체를 시간 순서대로 복원한 뒤
    2) 그 세션에 대해 apple_date 와 oscar_date 를 각각 계산한다.
    """
    if not entries:
        return []

    ordered = sorted(entries, key=lambda e: (e.start, e.end, e.priority))
    buckets: List[Bucket] = []
    current = Bucket(start=ordered[0].start, end=ordered[0].end, entries=[ordered[0]])

    for entry in ordered[1:]:
        if entry.start <= current.end + cluster_gap:
            current.entries.append(entry)
            if entry.end > current.end:
                current.end = entry.end
        else:
            buckets.append(current)
            current = Bucket(start=entry.start, end=entry.end, entries=[entry])
    buckets.append(current)

    return buckets



def duration_seconds(entries: Sequence[SleepEntry], predicate) -> int:
    """조건을 만족하는 entry 총 길이(초)."""
    total = 0.0
    for entry in entries:
        if predicate(entry):
            total += (entry.end - entry.start).total_seconds()
    return int(round(total))



def source_group_score(entries: Sequence[SleepEntry]) -> Tuple[int, int, int, int, int, int, int]:
    """버킷 안에서 source family 후보의 점수를 계산한다.

    우선순위
    1) REM/Light/Deep 같은 세분화 수면 단계가 실제로 있는가
    2) Apple Watch 로 보이는가
    3) 세분화 수면 단계 길이가 긴가
    4) 총 수면 길이가 긴가
    5) Awake 길이가 있는가
    6) 전체 길이가 긴가
    7) 최근에 끝나는가 (동점 방지용)
    """
    has_specific = any(e.stage in SLEEP_STAGE_SET and e.priority >= 4 for e in entries)
    watch_like = any(looks_like_apple_watch(e.source_name, e.device) for e in entries)
    specific_sleep_seconds = duration_seconds(entries, lambda e: e.stage in SLEEP_STAGE_SET and e.priority >= 4)
    total_sleep_seconds = duration_seconds(entries, lambda e: e.stage in SLEEP_STAGE_SET)
    awake_seconds = duration_seconds(entries, lambda e: e.stage == "WAKE")
    total_seconds = duration_seconds(entries, lambda e: True)
    last_end = max((int(e.end.timestamp()) for e in entries), default=0)

    return (
        int(has_specific),
        int(watch_like),
        specific_sleep_seconds,
        total_sleep_seconds,
        awake_seconds,
        total_seconds,
        last_end,
    )



def choose_entries_for_bucket(bucket: Bucket, source_contains: Optional[str]) -> Tuple[List[SleepEntry], str, str]:
    """버킷 안에서 실제로 쓸 source family 를 고른다.

    반환값
    - 선택된 entries
    - source_summary
    - chosen_source_family
    """
    if not bucket.entries:
        return [], "(없음)", "(없음)"

    if source_contains:
        target = normalize_text(source_contains)
        kept = [
            e for e in bucket.entries
            if target in normalize_text(f"{e.source_name} {e.device} {e.source_family}")
        ]
        if not kept:
            return [], "(없음)", "(없음)"
        return sorted(kept, key=lambda e: (e.start, e.end, e.priority)), summarize_sources(kept), kept[0].source_family

    families: Dict[str, List[SleepEntry]] = defaultdict(list)
    for entry in bucket.entries:
        families[entry.source_family].append(entry)

    ranked = sorted(
        families.items(),
        key=lambda item: source_group_score(item[1]),
        reverse=True,
    )

    chosen_family, chosen_entries = ranked[0]
    chosen_entries = sorted(chosen_entries, key=lambda e: (e.start, e.end, e.priority))
    return chosen_entries, summarize_sources(chosen_entries), chosen_family


# ======================================================================================
# 날짜 계산 / epoch 생성
# ======================================================================================


def overlap_seconds(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> float:
    """두 구간의 겹치는 길이(초)."""
    start = max(start_a, start_b)
    end = min(end_a, end_b)
    return max(0.0, (end - start).total_seconds())



def choose_apple_date(session_start: datetime, session_end: datetime) -> date:
    """Apple Health 일간 보기와 가장 비슷한 날짜를 계산한다.

    규칙
    - 세션이 실제로 가장 오래 걸친 local calendar day 를 apple_date 로 사용한다.
    - 동률이면 더 늦은 날짜를 선택한다.

    예시
    - 2026-03-09 02:14 ~ 11:54  -> apple_date = 2026-03-09
    - 2025-11-16 23:46 ~ 07:10  -> apple_date = 2025-11-17 (대부분이 자정 이후)
    - 2025-11-16 14:00 ~ 15:00  -> apple_date = 2025-11-16
    """
    tz = session_start.tzinfo
    start_day = session_start.date()
    end_day = session_end.date()
    day_count = (end_day - start_day).days

    best_day = start_day
    best_key = (-1.0, date.min)

    for offset in range(day_count + 1):
        d = start_day + timedelta(days=offset)
        day_start = datetime.combine(d, time(0, 0, 0), tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        ov = overlap_seconds(session_start, session_end, day_start, day_end)
        key = (ov, d)
        if key > best_key:
            best_key = key
            best_day = d

    return best_day



def compute_oscar_date(start_time: datetime, split_time: time) -> date:
    """OSCAR/ResMed 달력과 맞추기 위한 therapy day 날짜 계산.

    기본 split_time 은 12:00 이다.
    즉, 자정 이후 ~ 정오 이전에 시작한 세션은 전날 therapy day 로 본다.
    """
    local_t = start_time.timetz().replace(tzinfo=None)
    if local_t < split_time:
        return start_time.date() - timedelta(days=1)
    return start_time.date()



def build_epochs(entries: Sequence[SleepEntry], gap_policy: str) -> Tuple[datetime, datetime, List[str]]:
    """선택된 entry 로부터 30초 epoch hypnogram 을 생성한다."""
    if not entries:
        raise ValueError("epoch 를 만들 수 있는 entry 가 없습니다.")

    session_start = min(e.start for e in entries)
    session_end = max(e.end for e in entries)
    total_seconds = max(0.0, (session_end - session_start).total_seconds())
    epoch_count = int(math.ceil(total_seconds / 30.0))
    if epoch_count <= 0:
        epoch_count = 1

    fill_stage = "NA" if gap_policy == "na" else "WAKE"
    fill_priority = 0 if gap_policy == "na" else 1

    epochs = [fill_stage] * epoch_count
    priorities = [fill_priority] * epoch_count

    for entry in sorted(entries, key=lambda e: (e.start, e.end, e.priority)):
        start_offset = (entry.start - session_start).total_seconds()
        end_offset = (entry.end - session_start).total_seconds()

        start_idx = max(0, int(math.floor(start_offset / 30.0)))
        end_idx = min(epoch_count, int(math.ceil(end_offset / 30.0)))
        if end_idx <= start_idx:
            continue

        for idx in range(start_idx, end_idx):
            if entry.priority >= priorities[idx]:
                epochs[idx] = entry.stage
                priorities[idx] = entry.priority

    return session_start, session_end, epochs



def apply_time_sync(
    session_start: datetime,
    session_end: datetime,
    epochs: Sequence[str],
    shift_seconds: int,
    align_start: Optional[datetime],
    align_onset: Optional[datetime],
) -> Tuple[datetime, datetime, int]:
    """사용자가 명시적으로 요청한 시간 동기화만 적용한다.

    아주 중요
    - apple_date / oscar_date 문제를 해결하기 위해 여기서 날짜를 임의로 +/-1일 하지 않는다.
    - 이 함수는 오직 사용자가 명시한 보정 옵션만 적용한다.
    """
    if align_start is not None and align_onset is not None:
        raise ValueError("--align-start 와 --align-onset 은 동시에 사용할 수 없습니다.")

    total_shift = shift_seconds
    shifted_start = session_start + timedelta(seconds=shift_seconds)
    shifted_end = session_end + timedelta(seconds=shift_seconds)

    if align_start is not None:
        extra = int(round((align_start - shifted_start).total_seconds()))
        total_shift += extra
        shifted_start += timedelta(seconds=extra)
        shifted_end += timedelta(seconds=extra)
        return shifted_start, shifted_end, total_shift

    if align_onset is not None:
        try:
            onset_idx = next(i for i, stage in enumerate(epochs) if stage in SLEEP_STAGE_SET)
        except StopIteration:
            raise ValueError("수면 시작 epoch 가 없어 --align-onset 을 적용할 수 없습니다.")
        raw_onset = shifted_start + timedelta(seconds=onset_idx * 30)
        extra = int(round((align_onset - raw_onset).total_seconds()))
        total_shift += extra
        shifted_start += timedelta(seconds=extra)
        shifted_end += timedelta(seconds=extra)

    return shifted_start, shifted_end, total_shift



def compute_metrics(
    epochs: Sequence[str],
    session_start: datetime,
    session_end: datetime,
) -> Tuple[timedelta, timedelta, timedelta, timedelta, timedelta, timedelta, int, int]:
    """epoch 로부터 핵심 메트릭 계산."""
    light_count = sum(1 for stage in epochs if stage == "Light")
    deep_count = sum(1 for stage in epochs if stage == "Deep")
    rem_count = sum(1 for stage in epochs if stage == "REM")

    sleep_count = light_count + deep_count + rem_count
    light_duration = timedelta(seconds=light_count * 30)
    deep_duration = timedelta(seconds=deep_count * 30)
    rem_duration = timedelta(seconds=rem_count * 30)
    sleep_duration = light_duration + deep_duration + rem_duration

    try:
        onset_idx = next(i for i, stage in enumerate(epochs) if stage in SLEEP_STAGE_SET)
        sleep_onset_duration = timedelta(seconds=onset_idx * 30)
    except StopIteration:
        onset_idx = len(epochs)
        sleep_onset_duration = session_end - session_start

    wake_after_sleep_onset_count = sum(1 for stage in epochs[onset_idx:] if stage == "WAKE")
    wake_after_sleep_onset = timedelta(seconds=wake_after_sleep_onset_count * 30)

    awakenings = 0
    for prev_stage, cur_stage in zip(epochs[onset_idx:], epochs[onset_idx + 1 :]):
        if prev_stage in SLEEP_STAGE_SET and cur_stage == "WAKE":
            awakenings += 1

    known_count = sum(1 for stage in epochs if stage != "NA")
    sleep_efficiency = int(round(100.0 * sleep_count / known_count)) if known_count > 0 else 0

    return (
        sleep_duration,
        sleep_onset_duration,
        light_duration,
        deep_duration,
        rem_duration,
        wake_after_sleep_onset,
        awakenings,
        sleep_efficiency,
    )



def calc_rise_time(session_start: datetime, epochs: Sequence[str]) -> Optional[datetime]:
    """Zeo rise time 계산."""
    last_sleep_idx = None
    for idx, stage in enumerate(epochs):
        if stage in SLEEP_STAGE_SET:
            last_sleep_idx = idx
    if last_sleep_idx is None:
        return None
    return session_start + timedelta(seconds=last_sleep_idx * 30)



def make_session_key(start_time: Optional[datetime], stop_time: Optional[datetime]) -> str:
    """세션 식별 키."""
    if start_time is None or stop_time is None:
        return ""
    return f"{isoformat_with_offset(start_time)}|{isoformat_with_offset(stop_time)}"



def make_session_content_hash(session_start: datetime, session_end: datetime, epochs: Sequence[str], shift_seconds: int) -> str:
    """세션 내용 비교용 해시."""
    payload = "\n".join(
        [
            isoformat_with_offset(session_start),
            isoformat_with_offset(session_end),
            str(shift_seconds),
            ",".join(epochs),
        ]
    )
    return hash_text(payload)


# ======================================================================================
# 세션 구성
# ======================================================================================


def build_sessions(
    entries: Sequence[SleepEntry],
    source_contains: Optional[str],
    cluster_gap_hours: float,
    gap_policy: str,
    shift_seconds: int,
    align_start: Optional[datetime],
    align_onset: Optional[datetime],
    oscar_day_split: time,
    from_dt: Optional[datetime],
    to_dt: Optional[datetime],
    stats: RunStats,
) -> List[NightSession]:
    """원시 entry 를 최종 세션으로 변환한다."""
    sessions: List[NightSession] = []
    cluster_gap = timedelta(hours=max(0.0, float(cluster_gap_hours)))

    buckets = build_provisional_buckets(entries, cluster_gap)
    stats.provisional_buckets = len(buckets)

    for bucket in buckets:
        chosen_entries, source_summary, chosen_family = choose_entries_for_bucket(bucket, source_contains)
        if not chosen_entries:
            continue

        # 버킷 안에 source 가 여러 개 겹쳐 있어도, 최종 세션은 chosen_entries 로만 만든다.
        session_start_raw = min(e.start for e in chosen_entries)
        session_end_raw = max(e.end for e in chosen_entries)

        if from_dt is not None and session_end_raw <= from_dt:
            continue
        if to_dt is not None and session_start_raw >= to_dt:
            continue

        session_start, session_end, epochs = build_epochs(chosen_entries, gap_policy=gap_policy)
        session_start, session_end, applied_shift_seconds = apply_time_sync(
            session_start,
            session_end,
            epochs,
            shift_seconds=shift_seconds,
            align_start=align_start,
            align_onset=align_onset,
        )

        # 실제 수면 단계가 전혀 없으면 스킵한다.
        if not any(stage in SLEEP_STAGE_SET for stage in epochs):
            continue

        (
            sleep_duration,
            sleep_onset_duration,
            light_duration,
            deep_duration,
            rem_duration,
            wake_after_sleep_onset,
            awakenings,
            sleep_efficiency,
        ) = compute_metrics(epochs, session_start, session_end)

        apple_date = choose_apple_date(session_start, session_end)
        oscar_date = compute_oscar_date(session_start, oscar_day_split)
        session_key = make_session_key(session_start, session_end)
        content_hash = make_session_content_hash(session_start, session_end, epochs, applied_shift_seconds)

        sessions.append(
            NightSession(
                apple_date=apple_date,
                oscar_date=oscar_date,
                source_summary=source_summary,
                start_time=session_start,
                stop_time=session_end,
                applied_shift_seconds=applied_shift_seconds,
                epochs=list(epochs),
                sleep_duration=sleep_duration,
                sleep_onset_duration=sleep_onset_duration,
                light_duration=light_duration,
                deep_duration=deep_duration,
                rem_duration=rem_duration,
                wake_after_sleep_onset=wake_after_sleep_onset,
                awakenings=awakenings,
                sleep_efficiency=sleep_efficiency,
                session_key=session_key,
                content_hash=content_hash,
            )
        )
        stats.chosen_sources[chosen_family] += 1

    return sessions


# ======================================================================================
# Dreem / Zeo 출력
# ======================================================================================


def build_dreem_row(session: NightSession) -> dict:
    """Dreem CSV 한 줄."""
    hypnogram = "[" + ",".join(session.epochs) + "]"
    return {
        "Type": "night",
        "Start Time": isoformat_with_offset(session.start_time),
        "Stop Time": isoformat_with_offset(session.stop_time),
        "Sleep Duration": format_td_hms(session.sleep_duration),
        "Sleep Onset Duration": format_td_hms(session.sleep_onset_duration),
        "Light Sleep Duration": format_td_hms(session.light_duration),
        "Deep Sleep Duration": format_td_hms(session.deep_duration),
        "REM Duration": format_td_hms(session.rem_duration),
        "Wake After Sleep Onset Duration": format_td_hms(session.wake_after_sleep_onset),
        "Number of awakenings": str(session.awakenings),
        "Position Changes": "0",
        "Mean Heart Rate": "0",
        "Mean Respiration CPM": "0",
        "Number of Stimulations": "0",
        "Sleep efficiency": str(session.sleep_efficiency),
        "Hypnogram": hypnogram,
    }



def build_zeo_row(session: NightSession) -> dict:
    """Zeo CSV 한 줄."""
    rise_time = calc_rise_time(session.start_time, session.epochs)
    detailed_graph = " ".join(ZEO_STAGE_MAP[stage] for stage in session.epochs)
    return {
        "ZQ": str(session.sleep_efficiency),
        "Total Z": str(td_to_minutes(session.sleep_duration)),
        "Time to Z": str(td_to_minutes(session.sleep_onset_duration)),
        "Time in Wake": str(td_to_minutes(session.wake_after_sleep_onset)),
        "Time in REM": str(td_to_minutes(session.rem_duration)),
        "Time in Light": str(td_to_minutes(session.light_duration)),
        "Time in Deep": str(td_to_minutes(session.deep_duration)),
        "Awakenings": str(session.awakenings),
        "Sleep Graph": "",
        "Detailed Sleep Graph": detailed_graph,
        "Start of Night": zeo_time(session.start_time),
        "End of Night": zeo_time(session.stop_time),
        "Rise Time": zeo_time(rise_time),
        "Alarm Reason": "",
        "Snooze Time": "",
        "Wake Tone": "",
        "Wake Window": "",
        "Alarm Type": "",
        "First Alarm Ring": "",
        "Last Alarm Ring": "",
        "First Snooze Time": "",
        "Last Snooze Time": "",
        "Set Alarm Time": "",
        "Morning Feel": "0",
        "Firmware Version": "",
        "My ZEO Version": "",
    }



def write_csv(path: Path, header: Sequence[str], row: dict, delimiter: str) -> None:
    """헤더 + 데이터 한 줄 CSV 저장."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(header), delimiter=delimiter, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(row)


# ======================================================================================
# Manifest 로딩 / 저장 / 증분 처리
# ======================================================================================


def resolve_manifest_file_path(raw_path: str, output_dir: Path) -> Optional[Path]:
    """manifest 안의 파일 경로를 실제 Path 로 복원한다."""
    text = (raw_path or "").strip()
    if not text:
        return None

    path = Path(text)
    root = output_dir.parent

    if path.is_absolute():
        return path

    candidates = [
        root / path,                           # output/Dreem/... 형태 저장된 경우
        output_dir / path,                     # output 기준 상대경로
        output_dir / path.name,                # 파일명만 저장된 경우
        output_dir / "Dreem" / path.name,     # 예전 버전에서 폴더가 바뀐 경우
        output_dir / "ZEO" / path.name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]



def load_existing_manifest(manifest_path: Path, output_dir: Path, output_tz: tzinfo) -> Tuple[Dict[str, ExistingManifestRow], bool]:
    """기존 manifest 를 읽는다.

    반환값
    - session_key -> ExistingManifestRow
    - modern_manifest 여부
    """
    if not manifest_path.exists():
        return {}, False

    with manifest_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        modern = {
            "manifest_version",
            "session_key",
            "content_hash",
            "apple_date",
            "oscar_date",
            "dreem_file",
            "zeo_file",
        }.issubset(fieldnames)

        rows: Dict[str, ExistingManifestRow] = {}
        for row in reader:
            session_key = (row.get("session_key") or "").strip()
            if not session_key:
                start_dt = parse_datetime_loose(row.get("start_time"), output_tz)
                stop_dt = parse_datetime_loose(row.get("stop_time"), output_tz)
                session_key = make_session_key(start_dt, stop_dt)
            if not session_key:
                continue

            rows[session_key] = ExistingManifestRow(
                row=row,
                session_key=session_key,
                content_hash=(row.get("content_hash") or "").strip(),
                dreem_file=resolve_manifest_file_path(row.get("dreem_file", ""), output_dir),
                zeo_file=resolve_manifest_file_path(row.get("zeo_file", ""), output_dir),
            )

        same_version = all((rec.row.get("manifest_version") or "") == MANIFEST_VERSION for rec in rows.values()) if rows else False
        return rows, (modern and same_version)



def compute_incremental_cutoff(
    existing_rows: Dict[str, ExistingManifestRow],
    modern_manifest: bool,
    output_tz: tzinfo,
    overlap_days: int,
) -> Optional[datetime]:
    """증분 실행 시 재검사 시작 시점을 계산한다."""
    if not modern_manifest or not existing_rows:
        return None

    stop_times: List[datetime] = []
    for rec in existing_rows.values():
        dt = parse_datetime_loose(rec.row.get("stop_time"), output_tz)
        if dt is not None:
            stop_times.append(dt.astimezone(output_tz))

    if not stop_times:
        return None

    latest_stop = max(stop_times)
    return latest_stop - timedelta(days=max(0, overlap_days))



def desired_base_name(session: NightSession, prefix: str) -> str:
    """출력 파일의 기본 이름.

    파일명 날짜는 apple_date 가 아니라 oscar_date 를 쓴다.
    하지만 내부 Start Time / Start of Night 는 실제 Apple 세션 시각 그대로 유지한다.
    """
    time_part = session.start_time.strftime("%H-%M-%S")
    return make_safe_filename(f"{prefix}_{session.oscar_date.isoformat()}_{time_part}")



def migrate_existing_file(old_path: Optional[Path], new_path: Path) -> bool:
    """기존 파일을 새 경로로 옮긴다.

    반환값은 "실제로 이동이 일어났는지" 여부다.
    """
    if old_path is None:
        return False

    try:
        if old_path.resolve() == new_path.resolve():
            return False
    except Exception:
        pass

    if new_path.exists():
        return False
    if not old_path.exists():
        return False

    new_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old_path), str(new_path))
    return True



def relative_to_root(path: Optional[Path], root_dir: Path) -> str:
    """manifest 저장용 상대경로."""
    if path is None:
        return ""
    try:
        return str(path.resolve().relative_to(root_dir.resolve()))
    except Exception:
        return str(path)



def session_to_manifest_row(session: NightSession, root_dir: Path) -> dict:
    """NightSession -> manifest 행."""
    return {
        "manifest_version": MANIFEST_VERSION,
        "apple_date": session.apple_date.isoformat(),
        "oscar_date": session.oscar_date.isoformat(),
        "calendar_start_date": session.start_time.date().isoformat(),
        "calendar_stop_date": session.stop_time.date().isoformat(),
        "source_summary": session.source_summary,
        "start_time": isoformat_with_offset(session.start_time),
        "stop_time": isoformat_with_offset(session.stop_time),
        "applied_shift_seconds": str(session.applied_shift_seconds),
        "sleep_duration": format_td_hms(session.sleep_duration),
        "sleep_onset_duration": format_td_hms(session.sleep_onset_duration),
        "light_duration": format_td_hms(session.light_duration),
        "deep_duration": format_td_hms(session.deep_duration),
        "rem_duration": format_td_hms(session.rem_duration),
        "wake_after_sleep_onset": format_td_hms(session.wake_after_sleep_onset),
        "awakenings": str(session.awakenings),
        "sleep_efficiency": str(session.sleep_efficiency),
        "session_key": session.session_key,
        "content_hash": session.content_hash,
        "dreem_file": relative_to_root(session.dreem_file, root_dir),
        "zeo_file": relative_to_root(session.zeo_file, root_dir),
    }



def write_manifest(manifest_path: Path, all_rows: Dict[str, dict]) -> None:
    """전체 manifest 저장."""
    fieldnames = [
        "manifest_version",
        "apple_date",
        "oscar_date",
        "calendar_start_date",
        "calendar_stop_date",
        "source_summary",
        "start_time",
        "stop_time",
        "applied_shift_seconds",
        "sleep_duration",
        "sleep_onset_duration",
        "light_duration",
        "deep_duration",
        "rem_duration",
        "wake_after_sleep_onset",
        "awakenings",
        "sleep_efficiency",
        "session_key",
        "content_hash",
        "dreem_file",
        "zeo_file",
    ]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    rows = list(all_rows.values())
    rows.sort(key=lambda row: ((row.get("start_time") or ""), (row.get("oscar_date") or "")))

    with manifest_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


# ======================================================================================
# 파일 출력
# ======================================================================================


def write_session_outputs(
    session: NightSession,
    output_dir: Path,
    output_format: str,
    prefix: str,
    existing: Optional[ExistingManifestRow],
    root_dir: Path,
    stats: RunStats,
    force_rewrite: bool,
) -> None:
    """세션 1개를 Dreem / Zeo 로 기록한다."""
    base_name = desired_base_name(session, prefix)
    dreem_dir = output_dir / "Dreem"
    zeo_dir = output_dir / "ZEO"
    desired_dreem = dreem_dir / f"{base_name}.dreem.csv"
    desired_zeo = zeo_dir / f"{base_name}.zeo.csv"

    wants_dreem = output_format in {"dreem", "both"}
    wants_zeo = output_format in {"zeo", "both"}

    if existing is not None:
        if wants_dreem and migrate_existing_file(existing.dreem_file, desired_dreem):
            stats.migrated_files += 1
        if wants_zeo and migrate_existing_file(existing.zeo_file, desired_zeo):
            stats.migrated_files += 1

    can_skip = (
        not force_rewrite
        and existing is not None
        and existing.content_hash
        and existing.content_hash == session.content_hash
    )

    wrote_count = 0

    if wants_dreem:
        if can_skip and desired_dreem.exists():
            session.dreem_file = desired_dreem
        else:
            write_csv(desired_dreem, DREEM_HEADER, build_dreem_row(session), delimiter=";")
            session.dreem_file = desired_dreem
            wrote_count += 1

    if wants_zeo:
        if can_skip and desired_zeo.exists():
            session.zeo_file = desired_zeo
        else:
            write_csv(desired_zeo, ZEO_HEADER, build_zeo_row(session), delimiter=",")
            session.zeo_file = desired_zeo
            wrote_count += 1

    if wrote_count > 0:
        stats.files_written += wrote_count
    else:
        stats.files_reused += int(wants_dreem) + int(wants_zeo)


def _emit(logger: LogCallback, message: str) -> None:
    if logger is not None:
        logger(str(message))



def _coerce_time_setting(value: Union[str, time], fallback: time) -> time:
    if isinstance(value, time):
        return value
    text = str(value or "").strip()
    if not text:
        return fallback
    return parse_hhmm(text)



def _coerce_datetime_setting(value: Optional[Union[str, datetime]], output_tz: tzinfo) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=output_tz)
    return parse_datetime_loose(str(value), output_tz)



def default_output_dir_for(base_dir: Path) -> Path:
    return base_dir / DEFAULT_OUTPUT_DIR_NAME



def validate_config(config: ConversionConfig) -> None:
    if config.output_format not in {"dreem", "zeo", "both"}:
        raise ValueError("format 은 dreem / zeo / both 중 하나여야 합니다.")
    if config.gap_policy not in {"na", "wake"}:
        raise ValueError("gap-policy 는 na / wake 중 하나여야 합니다.")
    if config.generic_asleep_as not in {"light", "na"}:
        raise ValueError("generic-asleep-as 는 light / na 중 하나여야 합니다.")
    if float(config.cluster_gap_hours) < 0:
        raise ValueError("cluster-gap-hours 는 0 이상이어야 합니다.")
    if int(config.incremental_overlap_days) < 0:
        raise ValueError("incremental-overlap-days 는 0 이상이어야 합니다.")

    # 기존 README/UI 호환용. 현재 엔진 동작을 바꾸지 않기 위해 값만 검증한다.
    _coerce_time_setting(config.night_start, DEFAULT_NIGHT_START)
    _coerce_time_setting(config.night_end, DEFAULT_NIGHT_END)
    _coerce_time_setting(config.oscar_day_split, DEFAULT_OSCAR_DAY_SPLIT)



def run_conversion(
    config: ConversionConfig,
    *,
    base_dir: Optional[Path] = None,
    logger: LogCallback = None,
) -> ConversionResult:
    """단일 변환 작업을 실행한다.

    base_dir 는 CLI 기본 입력/출력 경로를 계산할 때 기준이 되는 루트다.
    GUI에서는 보통 명시적 input/output 을 넘기면 된다.
    """
    validate_config(config)

    root_dir = (base_dir or Path.cwd()).expanduser().resolve()
    output_tz = safe_zoneinfo(config.timezone) or get_local_timezone()

    if config.input_path:
        input_path = Path(config.input_path).expanduser().resolve()
    else:
        input_path = resolve_default_input(root_dir)

    output_dir = Path(config.output_dir).expanduser().resolve()
    manifest_path = output_dir / DEFAULT_MANIFEST_FILENAME

    if not input_path.exists():
        raise FileNotFoundError(f"입력 파일을 찾지 못했습니다: {input_path}")
    if input_path.is_dir():
        raise ValueError("input 은 export.xml 또는 export.zip 파일이어야 합니다. 현재는 폴더가 지정되었습니다.")

    oscar_day_split = _coerce_time_setting(config.oscar_day_split, DEFAULT_OSCAR_DAY_SPLIT)
    from_dt = parse_bound_datetime(str(config.from_dt), output_tz, fallback_time=time(0, 0, 0)) if config.from_dt is not None else None
    to_dt = parse_bound_datetime(str(config.to_dt), output_tz, fallback_time=time(23, 59, 59)) if config.to_dt is not None else None
    align_start = _coerce_datetime_setting(config.align_start, output_tz)
    align_onset = _coerce_datetime_setting(config.align_onset, output_tz)

    stats = RunStats()

    _emit(logger, f"입력 파일 확인: {input_path}")
    _emit(logger, f"출력 폴더 준비: {output_dir}")
    _emit(logger, "기존 manifest 검사 중...")
    existing_rows, modern_manifest = load_existing_manifest(manifest_path, output_dir, output_tz)
    stats.rebuild_all = bool(config.rebuild_all or not modern_manifest)

    incremental_cutoff = None if stats.rebuild_all else compute_incremental_cutoff(
        existing_rows,
        modern_manifest=modern_manifest,
        output_tz=output_tz,
        overlap_days=int(config.incremental_overlap_days),
    )
    stats.incremental_cutoff = incremental_cutoff

    _emit(logger, "Apple Health XML 파싱 중...")
    all_entries = parse_apple_health_xml(
        input_path=input_path,
        output_tz=output_tz,
        generic_asleep_as=config.generic_asleep_as,
        min_end_dt=incremental_cutoff,
        logger=logger,
    )
    stats.parsed_records = len(all_entries)
    _emit(logger, f"파싱 완료: {stats.parsed_records}개 레코드")

    _emit(logger, "source 1차 필터링 중...")
    filtered_entries, source_summary = filter_entries_by_source(all_entries, config.source_contains)
    stats.selected_records = len(filtered_entries)
    _emit(logger, f"필터링 완료: {stats.selected_records}개 레코드 사용")

    _emit(logger, "세션 구성 중...")
    sessions = build_sessions(
        entries=filtered_entries,
        source_contains=config.source_contains,
        cluster_gap_hours=float(config.cluster_gap_hours),
        gap_policy=config.gap_policy,
        shift_seconds=int(config.shift_seconds),
        align_start=align_start,
        align_onset=align_onset,
        oscar_day_split=oscar_day_split,
        from_dt=from_dt,
        to_dt=to_dt,
        stats=stats,
    )
    stats.final_sessions = len(sessions)
    _emit(logger, f"세션 계산 완료: {stats.final_sessions}개")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / DEFAULT_DREEM_DIR_NAME).mkdir(parents=True, exist_ok=True)
    (output_dir / DEFAULT_ZEO_DIR_NAME).mkdir(parents=True, exist_ok=True)

    manifest_rows: Dict[str, dict] = {}
    for key, rec in existing_rows.items():
        manifest_rows[key] = dict(rec.row)

    for idx, session in enumerate(sessions, start=1):
        existing = existing_rows.get(session.session_key)
        write_session_outputs(
            session=session,
            output_dir=output_dir,
            output_format=config.output_format,
            prefix=config.prefix,
            existing=existing,
            root_dir=output_dir.parent,
            stats=stats,
            force_rewrite=stats.rebuild_all,
        )
        manifest_rows[session.session_key] = session_to_manifest_row(session, output_dir.parent)
        _emit(
            logger,
            f"[{idx}/{len(sessions)}] {session.start_time.strftime('%Y-%m-%d %H:%M:%S')} -> {session.stop_time.strftime('%H:%M:%S')} 처리 완료",
        )

    write_manifest(manifest_path, manifest_rows)
    _emit(logger, f"manifest 저장 완료: {manifest_path}")

    summary_lines = format_summary_lines(
        input_path=input_path,
        output_dir=output_dir,
        manifest_path=manifest_path,
        source_summary=source_summary,
        stats=stats,
        sessions=sessions,
    )
    for line in summary_lines:
        _emit(logger, line)

    return ConversionResult(
        config=config,
        input_path=input_path,
        output_dir=output_dir,
        manifest_path=manifest_path,
        source_summary=source_summary,
        stats=stats,
        sessions=sessions,
        summary_lines=summary_lines,
    )


# ======================================================================================
# 콘솔 출력
# ======================================================================================


def format_summary_lines(
    input_path: Path,
    output_dir: Path,
    manifest_path: Path,
    source_summary: str,
    stats: RunStats,
    sessions: Sequence[NightSession],
) -> List[str]:
    """실행 요약 문자열 목록."""
    lines: List[str] = []
    lines.append("=" * 96)
    lines.append("Apple Watch -> OSCAR 변환 요약")
    lines.append(f"- 입력 파일: {input_path}")
    lines.append(f"- 출력 폴더: {output_dir}")
    lines.append(f"- manifest: {manifest_path}")
    lines.append(f"- 1차 source 필터: {source_summary}")
    lines.append(f"- 파싱된 수면 레코드 수: {stats.parsed_records}")
    lines.append(f"- 선택된 수면 레코드 수: {stats.selected_records}")
    lines.append(f"- provisional bucket 수: {stats.provisional_buckets}")
    lines.append(f"- 최종 세션 수: {stats.final_sessions}")
    lines.append(f"- 전체 재생성 모드: {'예' if stats.rebuild_all else '아니오'}")
    if stats.incremental_cutoff is not None:
        lines.append(f"- 증분 컷오프: {isoformat_with_offset(stats.incremental_cutoff)}")
    lines.append(f"- 새로 기록한 파일 수: {stats.files_written}")
    lines.append(f"- 재사용한 파일 수: {stats.files_reused}")
    lines.append(f"- 이동(migrate)한 파일 수: {stats.migrated_files}")

    if stats.chosen_sources:
        lines.append("- 버킷별로 실제 선택된 source family:")
        for label, count in stats.chosen_sources.most_common():
            lines.append(f"  * {label}: {count}")

    lines.append("- 생성/평가한 세션:")
    for session in sessions:
        parts = [
            f"  * apple_date={session.apple_date.isoformat()}",
            f"oscar_date={session.oscar_date.isoformat()}",
            f"start={isoformat_with_offset(session.start_time)}",
            f"stop={isoformat_with_offset(session.stop_time)}",
            f"shift={session.applied_shift_seconds}s",
        ]
        if session.dreem_file:
            parts.append(f"Dreem={session.dreem_file.name}")
        if session.zeo_file:
            parts.append(f"Zeo={session.zeo_file.name}")
        lines.append(" | ".join(parts))
    lines.append("=" * 96)
    return lines



def print_summary(
    input_path: Path,
    output_dir: Path,
    manifest_path: Path,
    source_summary: str,
    stats: RunStats,
    sessions: Sequence[NightSession],
) -> None:
    """실행 요약."""
    for line in format_summary_lines(
        input_path=input_path,
        output_dir=output_dir,
        manifest_path=manifest_path,
        source_summary=source_summary,
        stats=stats,
        sessions=sessions,
    ):
        print(line)

