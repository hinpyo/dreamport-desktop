from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Tuple

from .engine import (
    DEFAULT_CLUSTER_GAP_HOURS,
    DEFAULT_GAP_POLICY,
    DEFAULT_GENERIC_ASLEEP_AS,
    DEFAULT_INCREMENTAL_OVERLAP_DAYS,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_START,
    DEFAULT_PREFIX,
)
from .timezones import SYSTEM_TIMEZONE


@dataclass(frozen=True)
class OptionChoice:
    value: str
    label_key: str
    description_key: str = ""


@dataclass(frozen=True)
class OptionSpec:
    key: str
    label_key: str
    description_key: str
    default: Any
    widget: str
    beginner: bool = False
    advanced: bool = False
    section: str = "main"
    choices: Tuple[OptionChoice, ...] = field(default_factory=tuple)


OUTPUT_FORMAT_CHOICES = (
    OptionChoice("both", "value.output_format.both"),
    OptionChoice("dreem", "value.output_format.dreem"),
    OptionChoice("zeo", "value.output_format.zeo"),
)

GAP_POLICY_CHOICES = (
    OptionChoice("na", "value.gap_policy.na"),
    OptionChoice("wake", "value.gap_policy.wake"),
)

GENERIC_ASLEEP_CHOICES = (
    OptionChoice("light", "value.generic_asleep_as.light"),
    OptionChoice("na", "value.generic_asleep_as.na"),
)

OPTION_SPECS = (
    OptionSpec(
        key="output_format",
        label_key="option.output_format.label",
        description_key="option.output_format.description",
        default="both",
        widget="choice",
        beginner=True,
        section="main",
        choices=OUTPUT_FORMAT_CHOICES,
    ),
    OptionSpec(
        key="timezone",
        label_key="option.timezone.label",
        description_key="option.timezone.description",
        default=SYSTEM_TIMEZONE,
        widget="timezone",
        beginner=True,
        section="main",
    ),
    OptionSpec(
        key="ui_language",
        label_key="option.ui_language.label",
        description_key="option.ui_language.description",
        default="auto",
        widget="language",
        beginner=True,
        section="preferences_general",
    ),
    OptionSpec(
        key="prefix",
        label_key="option.prefix.label",
        description_key="option.prefix.description",
        default=DEFAULT_PREFIX,
        widget="entry",
        section="preferences_general",
    ),
    OptionSpec(
        key="source_contains",
        label_key="option.source_contains.label",
        description_key="option.source_contains.description",
        default="",
        widget="entry",
        advanced=True,
        section="preferences_advanced",
    ),
    OptionSpec(
        key="gap_policy",
        label_key="option.gap_policy.label",
        description_key="option.gap_policy.description",
        default=DEFAULT_GAP_POLICY,
        widget="choice",
        advanced=True,
        section="preferences_advanced",
        choices=GAP_POLICY_CHOICES,
    ),
    OptionSpec(
        key="generic_asleep_as",
        label_key="option.generic_asleep_as.label",
        description_key="option.generic_asleep_as.description",
        default=DEFAULT_GENERIC_ASLEEP_AS,
        widget="choice",
        advanced=True,
        section="preferences_advanced",
        choices=GENERIC_ASLEEP_CHOICES,
    ),
    OptionSpec(
        key="cluster_gap_hours",
        label_key="option.cluster_gap_hours.label",
        description_key="option.cluster_gap_hours.description",
        default=str(DEFAULT_CLUSTER_GAP_HOURS),
        widget="entry",
        advanced=True,
        section="preferences_advanced",
    ),
    OptionSpec(
        key="incremental_overlap_days",
        label_key="option.incremental_overlap_days.label",
        description_key="option.incremental_overlap_days.description",
        default=str(DEFAULT_INCREMENTAL_OVERLAP_DAYS),
        widget="entry",
        advanced=True,
        section="preferences_advanced",
    ),
    OptionSpec(
        key="night_start",
        label_key="option.night_start.label",
        description_key="option.night_start.description",
        default=DEFAULT_NIGHT_START.strftime("%H:%M"),
        widget="entry",
        advanced=True,
        section="preferences_advanced",
    ),
    OptionSpec(
        key="night_end",
        label_key="option.night_end.label",
        description_key="option.night_end.description",
        default=DEFAULT_NIGHT_END.strftime("%H:%M"),
        widget="entry",
        advanced=True,
        section="preferences_advanced",
    ),
    OptionSpec(
        key="rebuild_all",
        label_key="option.rebuild_all.label",
        description_key="option.rebuild_all.description",
        default=False,
        widget="bool",
        advanced=True,
        section="preferences_advanced",
    ),
)

OPTION_SPEC_BY_KEY: Dict[str, OptionSpec] = {spec.key: spec for spec in OPTION_SPECS}


def option_specs_for_section(section: str) -> Tuple[OptionSpec, ...]:
    return tuple(spec for spec in OPTION_SPECS if spec.section == section)


def default_option_values() -> Dict[str, Any]:
    return {spec.key: spec.default for spec in OPTION_SPECS}


def advanced_specs() -> Tuple[OptionSpec, ...]:
    return tuple(spec for spec in OPTION_SPECS if spec.advanced)


def coerce_saved_value(spec: OptionSpec, value: Any) -> Any:
    if value is None:
        return spec.default
    if spec.widget == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if spec.widget in {"entry", "choice", "timezone", "language"}:
        return str(value)
    return value


def merge_with_defaults(values: Dict[str, Any]) -> Dict[str, Any]:
    merged = default_option_values()
    for key, value in values.items():
        spec = OPTION_SPEC_BY_KEY.get(key)
        if spec is None:
            continue
        merged[key] = coerce_saved_value(spec, value)
    return merged


def count_non_default_advanced(values: Dict[str, Any]) -> int:
    count = 0
    for spec in advanced_specs():
        current = values.get(spec.key, spec.default)
        if current != spec.default:
            count += 1
    return count


def iter_option_keys() -> Iterable[str]:
    for spec in OPTION_SPECS:
        yield spec.key
