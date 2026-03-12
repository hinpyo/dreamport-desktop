from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

from .engine import (
    DEFAULT_CLUSTER_GAP_HOURS,
    DEFAULT_GAP_POLICY,
    DEFAULT_GENERIC_ASLEEP_AS,
    DEFAULT_INCREMENTAL_OVERLAP_DAYS,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_START,
    DEFAULT_PREFIX,
    DEFAULT_TIMEZONE,
    ConversionConfig,
    default_output_dir_for,
    run_conversion,
)


def build_arg_parser(default_output_dir: Optional[Path] = None) -> argparse.ArgumentParser:
    """Build the CLI parser.

    default_output_dir should normally be the repository root / "output" so the
    legacy `python oscar.py` workflow keeps behaving like the original script.
    """
    output_dir = default_output_dir or default_output_dir_for(Path.cwd())

    parser = argparse.ArgumentParser(
        description="Apple Health export.xml/export.zip 의 Apple Watch 수면 데이터를 OSCAR Dreem/Zeo 형식으로 변환합니다.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--input",
        default=None,
        help="입력 export.xml 또는 export.zip 경로. 생략하면 기준 폴더의 export.xml/export.zip 을 자동 선택",
    )
    parser.add_argument(
        "--output-dir",
        default=str(output_dir),
        help="출력 폴더. Dreem/ZEO 하위폴더를 자동 생성",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["dreem", "zeo", "both"],
        default="both",
        help="생성할 OSCAR 형식",
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help="출력 기준 타임존",
    )
    parser.add_argument(
        "--night-start",
        default=DEFAULT_NIGHT_START.strftime("%H:%M"),
        help="README/UI 호환용 야간 시작 시각. 현재 엔진의 기본 세션 복원은 cluster-gap-hours 기준을 유지",
    )
    parser.add_argument(
        "--night-end",
        default=DEFAULT_NIGHT_END.strftime("%H:%M"),
        help="README/UI 호환용 야간 종료 시각. 현재 엔진의 기본 세션 복원은 cluster-gap-hours 기준을 유지",
    )
    parser.add_argument(
        "--oscar-day-split",
        default="12:00",
        help="OSCAR/ResMed therapy day 경계 시각",
    )
    parser.add_argument(
        "--cluster-gap-hours",
        type=float,
        default=DEFAULT_CLUSTER_GAP_HOURS,
        help="같은 수면 세션으로 묶을 최대 빈 간격(시간)",
    )
    parser.add_argument(
        "--from",
        dest="from_dt",
        default=None,
        help="처리 시작 시각(선택)",
    )
    parser.add_argument(
        "--to",
        dest="to_dt",
        default=None,
        help="처리 종료 시각(선택)",
    )
    parser.add_argument(
        "--source-contains",
        default=None,
        help="source_name / device / source_family 에 이 텍스트가 포함된 기록만 사용",
    )
    parser.add_argument(
        "--shift-seconds",
        type=int,
        default=0,
        help="모든 세션에 적용할 고정 시프트(초)",
    )
    parser.add_argument(
        "--align-start",
        default=None,
        help="세션 시작 시각을 이 절대시각에 맞춘다",
    )
    parser.add_argument(
        "--align-onset",
        default=None,
        help="첫 수면 epoch 시작 시각을 이 절대시각에 맞춘다",
    )
    parser.add_argument(
        "--gap-policy",
        choices=["na", "wake"],
        default=DEFAULT_GAP_POLICY,
        help="레코드 사이 빈 구간 처리 방식",
    )
    parser.add_argument(
        "--generic-asleep-as",
        choices=["light", "na"],
        default=DEFAULT_GENERIC_ASLEEP_AS,
        help="세분화되지 않은 Asleep stage 처리 방식",
    )
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help="출력 파일명 접두어",
    )
    parser.add_argument(
        "--incremental-overlap-days",
        type=int,
        default=DEFAULT_INCREMENTAL_OVERLAP_DAYS,
        help="증분 실행 시 최근 며칠은 다시 검사할지",
    )
    parser.add_argument(
        "--rebuild-all",
        action="store_true",
        help="manifest 를 무시하고 전체 기간을 다시 계산한다",
    )

    return parser



def namespace_to_config(args: argparse.Namespace) -> ConversionConfig:
    return ConversionConfig(
        input_path=args.input,
        output_dir=args.output_dir,
        output_format=args.output_format,
        timezone=args.timezone,
        night_start=args.night_start,
        night_end=args.night_end,
        oscar_day_split=args.oscar_day_split,
        cluster_gap_hours=args.cluster_gap_hours,
        from_dt=args.from_dt,
        to_dt=args.to_dt,
        source_contains=args.source_contains,
        shift_seconds=args.shift_seconds,
        align_start=args.align_start,
        align_onset=args.align_onset,
        gap_policy=args.gap_policy,
        generic_asleep_as=args.generic_asleep_as,
        prefix=args.prefix,
        incremental_overlap_days=args.incremental_overlap_days,
        rebuild_all=args.rebuild_all,
    )



def main(argv: Optional[Sequence[str]] = None, *, base_dir: Optional[Path] = None) -> int:
    base_dir = (base_dir or Path.cwd()).expanduser().resolve()
    parser = build_arg_parser(default_output_dir=default_output_dir_for(base_dir))
    args = parser.parse_args(argv)

    config = namespace_to_config(args)

    try:
        run_conversion(config, base_dir=base_dir, logger=print)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    return 0
