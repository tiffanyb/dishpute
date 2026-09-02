import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo


class NaturalLanguageError(ValueError):
    pass


@dataclass(frozen=True)
class InterpretedCommand:
    action: Literal["create_task", "record_completed_work"]
    title: str
    category: str
    started_at: datetime | None = None
    ended_at: datetime | None = None


_TIME_RANGE = re.compile(
    r"\b(?P<start>\d{1,2}(?::\d{2})?)\s*(?:to|-)\s*"
    r"(?P<end>\d{1,2}(?::\d{2})?)\b",
    re.IGNORECASE,
)


def _parse_time(value: str) -> time:
    hour_text, separator, minute_text = value.partition(":")
    hour = int(hour_text)
    minute = int(minute_text) if separator else 0
    if hour > 23 or minute > 59:
        raise NaturalLanguageError("The time range is not valid")
    return time(hour=hour, minute=minute)


def _time_range(
    text: str, *, reference_date: date, timezone_name: str
) -> tuple[datetime, datetime] | None:
    match = _TIME_RANGE.search(text)
    if match is None:
        return None

    timezone = ZoneInfo(timezone_name)
    started_at = datetime.combine(
        reference_date, _parse_time(match.group("start")), timezone
    )
    ended_at = datetime.combine(
        reference_date, _parse_time(match.group("end")), timezone
    )
    if ended_at <= started_at:
        raise NaturalLanguageError("The end time must be after the start time")
    return started_at, ended_at


def _work_title(text: str, time_match: re.Match[str] | None) -> str:
    without_time = text[: time_match.start()] if time_match is not None else text
    work = re.sub(
        r"^(?:i\s+)?(?:just\s+|will\s+)?", "", without_time.strip(), flags=re.IGNORECASE
    )
    work = work.strip(" .,")
    if not work:
        raise NaturalLanguageError("The household work needs a description")
    return work[0].upper() + work[1:]


def _category_for(title: str) -> str:
    lowered = title.lower()
    if any(word in lowered for word in ("clean", "vacuum", "mop", "dust")):
        return "cleaning"
    if any(word in lowered for word in ("meal", "cook", "dinner", "lunch", "breakfast")):
        return "food"
    return "other"


def interpret(
    text: str, *, reference_date: date, timezone_name: str
) -> InterpretedCommand:
    normalized = " ".join(text.split())
    if not normalized:
        raise NaturalLanguageError("Natural-language input cannot be empty")

    time_match = _TIME_RANGE.search(normalized)
    time_range = _time_range(
        normalized, reference_date=reference_date, timezone_name=timezone_name
    )
    title = _work_title(normalized, time_match)
    category = _category_for(title)

    if re.match(r"^i\s+just\b", normalized, re.IGNORECASE):
        if time_range is None:
            raise NaturalLanguageError("Completed work needs a time range")
        return InterpretedCommand(
            action="record_completed_work",
            title=title,
            category=category,
            started_at=time_range[0],
            ended_at=time_range[1],
        )

    if re.match(r"^i\s+will\b", normalized, re.IGNORECASE):
        return InterpretedCommand(
            action="create_task",
            title=title,
            category=category,
            started_at=time_range[0] if time_range is not None else None,
            ended_at=time_range[1] if time_range is not None else None,
        )

    if time_range is not None:
        raise NaturalLanguageError(
            "Say whether the work already happened or is planned"
        )
    return InterpretedCommand(action="create_task", title=title, category=category)
