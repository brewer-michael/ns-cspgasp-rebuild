"""On-device commands: timers, alarms, stop/snooze and volume (English).

These are recognized before a request is sent to Home Assistant or a language model,
so the clock-radio basics keep working when the network or Home Assistant is down.
Anything not recognized here is passed on unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Intents


@dataclass(frozen=True)
class Intent:
    pass


@dataclass(frozen=True)
class StartTimer(Intent):
    seconds: int
    name: str | None = None


@dataclass(frozen=True)
class CancelTimer(Intent):
    name: str | None = None
    all: bool = False


@dataclass(frozen=True)
class TimerStatus(Intent):
    name: str | None = None


@dataclass(frozen=True)
class SetAlarm(Intent):
    hour: int  # 0-23
    minute: int
    # Weekdays the alarm repeats on (0 = Monday). Empty = rings once.
    repeat: frozenset[int] = field(default_factory=frozenset)
    # For one-shot alarms: a specific weekday, or "tomorrow" (-1).
    day: int | None = None
    # No am/pm given: "7" may mean 7:00 or 19:00 (the next one is used).
    ambiguous: bool = False


@dataclass(frozen=True)
class CancelAlarm(Intent):
    hour: int | None = None
    minute: int | None = None
    all: bool = False
    ambiguous: bool = False


@dataclass(frozen=True)
class AlarmStatus(Intent):
    pass


@dataclass(frozen=True)
class Stop(Intent):
    # The request named the alarm ("turn off the alarm"): if nothing is ringing,
    # it means "cancel my next alarm".
    alarm: bool = False


@dataclass(frozen=True)
class Snooze(Intent):
    minutes: int | None = None


@dataclass(frozen=True)
class ChangeVolume(Intent):
    steps: int = 0  # relative change in volume steps
    level: int | None = None  # absolute level 0-100


@dataclass(frozen=True)
class AskTimerDuration(Intent):
    """ "Set a timer" without a duration: ask how long, then expect an answer."""

    name: str | None = None


@dataclass(frozen=True)
class AskAlarmTime(Intent):
    """ "Set an alarm" without a time: ask when, then expect an answer."""

    repeat: frozenset[int] = field(default_factory=frozenset)
    day: int | None = None


TOMORROW = -1
WEEKDAYS = frozenset(range(5))
WEEKENDS = frozenset({5, 6})
EVERY_DAY = frozenset(range(7))
DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# ---------------------------------------------------------------------------
# Normalization and numbers

_UNITS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}  # fmt: skip


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\b([ap])\.\s?m\b\.?", r"\1m", text)  # a.m. -> am
    text = text.replace("o'clock", "oclock").replace("\u2019", "'")  # curly apostrophe
    text = re.sub(r"(?<=\d)(am|pm)\b", r" \1", text)  # 7am -> 7 am
    text = re.sub(r"(?<=\d)%", " percent", text)
    text = re.sub(r"(?<=[a-z0-9])-(?=[a-z0-9])", " ", text)  # five-minute -> five minute
    text = re.sub(r"[^\w\s:.']", " ", text)  # drop punctuation except : . '
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text)  # keep "." only inside numbers
    text = re.sub(r"\b(please|hey|okay|ok|um|uh|could you|can you|would you)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_number(words: list[str], i: int) -> tuple[float | None, int]:
    """Parse a number starting at ``words[i]``; returns (value, next index)."""
    if i >= len(words):
        return None, i
    word = words[i]
    if re.fullmatch(r"\d+(\.\d+)?", word):
        if words[i + 1 : i + 4] == ["and", "a", "half"]:  # "2 and a half"
            return float(word) + 0.5, i + 4
        return float(word), i + 1
    if word in ("a", "an") and i + 1 < len(words) and words[i + 1] == "couple":
        j = i + 2 + (1 if i + 2 < len(words) and words[i + 2] == "of" else 0)
        return 2.0, j
    if word in ("a", "an", "one") and i + 1 < len(words) and words[i + 1] == "half":
        return 0.5, i + 2
    if word == "half":
        return 0.5, i + 1
    value: float | None = None
    j = i
    if word in _TENS:
        value, j = float(_TENS[word]), i + 1
        if j < len(words) and words[j] in _UNITS and 0 < _UNITS[words[j]] < 10:
            value += _UNITS[words[j]]
            j += 1
    elif word in _UNITS:
        value, j = float(_UNITS[word]), i + 1
    elif word in ("a", "an"):
        value, j = 1.0, i + 1
    if value is not None and j < len(words) and words[j] == "hundred":
        value *= 100
        j += 1
        if j < len(words) and words[j] == "and":
            extra, k = parse_number(words, j + 1)
            if extra is not None and extra < 100:
                value += extra
                j = k
    # "one and a half" / "two and a half"
    if value is not None and words[j : j + 3] == ["and", "a", "half"]:
        value += 0.5
        j += 3
    return value, j


_UNIT_SECONDS = {
    "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600, "h": 3600,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60,
    "second": 1, "seconds": 1, "sec": 1, "secs": 1, "s": 1,
}  # fmt: skip


def parse_duration(text: str) -> tuple[int | None, set[int]]:
    """Find a duration like "an hour and 15 minutes"; returns (seconds, used word indexes)."""
    words = text.split()
    total = 0.0
    found = False
    used: set[int] = set()
    i = 0
    while i < len(words):
        # "a quarter of an hour" / "quarter hour"
        if words[i] == "quarter":
            j = i + 1
            while j < len(words) and words[j] in ("of", "an", "a"):
                j += 1
            if j < len(words) and words[j] in ("hour", "hours"):
                start = i - 1 if i > 0 and words[i - 1] in ("a", "one") else i
                total += 900
                found = True
                used.update(range(start, j + 1))
                i = j + 1
                continue
        value, j = parse_number(words, i)
        if value is not None:
            k = j
            while k < len(words) and words[k] in ("an", "a", "of"):  # "half an hour"
                k += 1
            if k < len(words) and words[k] in _UNIT_SECONDS:
                unit = _UNIT_SECONDS[words[k]]
                total += value * unit
                found = True
                used.update(range(i, k + 1))
                i = k + 1
                # "a minute and a half"
                if words[i : i + 3] == ["and", "a", "half"]:
                    total += unit / 2
                    used.update(range(i, i + 3))
                    i += 3
                continue
        i += 1
    return (round(total) if found and total > 0 else None), used


_TIME_WORDS = {"noon": (12, 0), "midday": (12, 0), "midnight": (0, 0)}


@dataclass(frozen=True)
class ClockTime:
    hour: int
    minute: int
    # True when the hour is ambiguous (no am/pm, 1-12): 7 could be 7:00 or 19:00.
    ambiguous: bool = False


def parse_clock_time(text: str) -> ClockTime | None:
    """Parse "7", "7:30 pm", "seven thirty", "half past six", "quarter to 8", "noon"..."""
    for word, (hour, minute) in _TIME_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return ClockTime(hour, minute)

    match = re.search(r"\b(\d{1,2})[:.](\d{2})\b", text)
    words = text.split()
    hour: int | None = None
    minute = 0
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
    else:
        rel = re.search(
            r"\b(half|quarter|(?:(?:twenty|thirty|forty|fifty) )?\S+(?: minutes?)?) "
            r"(past|after|to|till|before) (\S+)",
            text,
        )
        if rel:
            amount, direction, target = rel.groups()
            offset = {"half": 30, "quarter": 15}.get(amount)
            if offset is None:
                value, _ = parse_number(amount.replace(" minutes", "").split(), 0)
                offset = int(value) if value is not None else None
            base, _ = parse_number([target], 0)
            if offset is not None and base is not None and 1 <= base <= 12:
                hour = int(base)
                minute = offset
                if direction in ("to", "till", "before"):
                    hour = (hour - 1) % 12 or 12
                    minute = 60 - offset
        if hour is None:
            # "my 7 am alarm", "six thirty pm", "my seven thirty alarm", "the 7 o'clock
            # alarm": a time right before am/pm, o'clock or the word alarm
            for i, word in enumerate(words):
                if word not in ("am", "pm", "oclock", "alarm", "alarms"):
                    continue
                for start in (i - 2, i - 1):
                    if start < 0 or words[start] in ("a", "an"):
                        continue
                    value, j = parse_number(words, start)
                    if value is None or value != int(value) or not 1 <= value <= 12:
                        continue
                    if j == i:  # "7 am"
                        hour = int(value)
                    else:  # "six thirty pm"
                        minutes, k = parse_number(words, j)
                        if k == i and minutes is not None and minutes == int(minutes) < 60:
                            hour, minute = int(value), int(minutes)
                    if hour is not None:
                        break
                if hour is not None:
                    break
        if hour is None:
            for i, word in enumerate(words):
                if word in ("at", "for", "to") and i + 1 < len(words):
                    value, j = parse_number(words, i + 1)
                    if value is None or value != int(value) or value > 24:
                        continue
                    if j < len(words) and words[j] in _UNIT_SECONDS:  # "for 10 minutes"
                        continue
                    hour = int(value)
                    # "seven thirty" / "7 45" / "six oh five"
                    if j < len(words) and words[j] not in ("am", "pm"):
                        minutes, k = parse_number(words, j)
                        if minutes is not None and minutes == int(minutes) and minutes < 60:
                            if j < len(words) and words[j] in ("oh", "zero") and minutes == 0:
                                more, k = parse_number(words, j + 1)
                                minutes = more if more is not None and more < 10 else minutes
                            if k >= len(words) or words[k] not in _UNIT_SECONDS:
                                minute = int(minutes)
                    break
    if hour is None or not 0 <= hour <= 24 or not 0 <= minute <= 59:
        return None
    if hour == 24:
        hour = 0

    meridiem = re.search(
        r"\b(am|pm|in the morning|in the afternoon|in the evening|at night|tonight)\b", text
    )
    if meridiem:
        mark = meridiem.group(1)
        pm = mark in ("pm", "in the afternoon", "in the evening", "at night", "tonight")
        if hour > 12:
            return ClockTime(hour, minute)
        if mark == "at night" and hour == 12:
            return ClockTime(0, minute)
        hour = hour % 12 + (12 if pm else 0)
        return ClockTime(hour, minute)
    if hour == 0 or hour > 12:
        return ClockTime(hour, minute)
    return ClockTime(hour % 12, minute, ambiguous=True)


def _repeat_days(text: str) -> tuple[frozenset[int], int | None]:
    """Return (repeat weekdays, one-shot day) from phrases like "every weekday"."""
    if re.search(r"\b(every day|everyday|daily|each day)\b", text):
        return EVERY_DAY, None
    if re.search(r"\b(every weekday|weekdays?|workdays|work days|every workday)\b", text):
        return WEEKDAYS, None
    if re.search(r"\b(every weekend|weekends)\b", text):
        return WEEKENDS, None
    every = re.search(r"\bevery ((?:\w+day(?:s)?(?: and | )?)+)", text)
    if every:
        days = {DAY_NAMES.index(d.rstrip("s")) for d in re.findall(r"\w+day", every.group(1))
                if d.rstrip("s") in DAY_NAMES}  # fmt: skip
        if days:
            return frozenset(days), None
    # "on mondays and wednesdays"
    plural = {DAY_NAMES.index(d) for d in re.findall(r"\b(\w+day)s\b", text) if d in DAY_NAMES}
    if plural:
        return frozenset(plural), None
    if re.search(r"\btomorrow\b", text):
        return frozenset(), TOMORROW
    for index, name in enumerate(DAY_NAMES):
        if re.search(rf"\b(on )?{name}\b", text):
            return frozenset(), index
    return frozenset(), None


# ---------------------------------------------------------------------------
# Recognition

_STOP_PHRASES = {
    "stop", "stop it", "stop that", "stop alarm", "stop the alarm", "stop timer",
    "stop the timer", "alarm off", "turn off the alarm", "turn off alarm", "turn the alarm off",
    "dismiss", "dismiss alarm", "dismiss the alarm", "cancel", "cancel that", "never mind",
    "nevermind", "be quiet", "quiet", "silence", "shut up", "enough", "that's enough",
    "stop the music", "stop playing",
}  # fmt: skip
_VOLUME_UP = re.compile(
    r"^(volume up|louder|(turn|crank) (it|the volume|volume) up|turn up the volume|"
    r"(increase|raise) (the )?volume|(a bit|a little|much) louder|make it louder)$"
)
_VOLUME_DOWN = re.compile(
    r"^(volume down|quieter|softer|(turn|bring) (it|the volume|volume) down|turn down the volume|"
    r"(decrease|lower|reduce) (the )?volume|(a bit|a little|much) (quieter|softer)|"
    r"make it (quieter|softer))$"
)
_TIMER_NAME_STOP = {
    "a", "an", "the", "my", "for", "of", "timer", "set", "start", "create", "make",
    "and", "on", "called", "named", "labeled", "with", "new", "another", "please",
}  # fmt: skip


def _timer_name(text: str, used: set[int]) -> str | None:
    words = text.split()
    labelled = re.search(r"\b(called|named|labeled|labelled) (.+)$", text)
    if labelled:
        label = labelled.group(2)
        # "called tea for 3 minutes" -> "tea"
        cut = re.search(r"\s(for|of)\s(.+)$", label)
        if cut and parse_duration(cut.group(2))[0] is not None:
            label = label[: cut.start()]
        label = re.sub(r"\btimer\b", "", label).strip()
        return label or None
    if "timer" in words:
        t = words.index("timer")
        before = [w for i, w in enumerate(words[:t]) if i not in used]
        # the words right before "timer" that are not the verb/article/duration
        name: list[str] = []
        for word in reversed(before):
            if word in _TIMER_NAME_STOP:
                break
            name.insert(0, word)
        if name:
            return " ".join(name)
        after = words[t + 1 :]
        # "... timer for 10 minutes for the pizza"
        tail = re.search(r"\bfor (?:the |my )?([a-z][a-z ]*)$", " ".join(after))
        if tail:
            candidate = tail.group(1).strip()
            if parse_duration(candidate)[0] is None:
                return candidate
    return None


def recognize(text: str) -> Intent | None:
    """Return an on-device intent for ``text``, or None to hand it to the assistant."""
    text = normalize(text)
    if not text:
        return None
    words = set(text.split())

    if text in _STOP_PHRASES:
        return Stop(alarm="alarm" in words)

    if text.startswith("snooze"):
        minutes, _ = parse_duration(text)
        return Snooze(minutes // 60 if minutes else None)

    if _VOLUME_UP.match(text):
        return ChangeVolume(steps=1)
    if _VOLUME_DOWN.match(text):
        return ChangeVolume(steps=-1)
    if re.search(r"\b(max|maximum|full) volume\b|\bvolume (to )?(max|maximum|full)\b", text):
        return ChangeVolume(level=100)
    volume = re.search(r"\bvolume (?:to |at |level )?(\S+(?: \S+)?)(?: percent)?$", text)
    if volume and re.search(r"^(set )?(the )?volume\b", text):
        value, _ = parse_number(volume.group(1).split(), 0)
        if value is not None:
            level = value * 10 if value <= 10 and "percent" not in text else value
            return ChangeVolume(level=max(0, min(100, int(level))))

    if words & {"timer", "timers"}:
        name_match = None
        if re.search(r"\b(cancel|stop|delete|remove|clear|end|turn off|kill)\b", text):
            all_timers = "all" in words or ("timers" in words and "timer" not in words)
            if not all_timers:
                name_match = _timer_name(text.replace("timers", "timer"), set())
            return CancelTimer(name=name_match, all=all_timers)
        if re.search(r"\b(how (much|long)|time left|remaining|left on|status|check)\b", text):
            return TimerStatus(name=_timer_name(text, set()))
        seconds, used = parse_duration(text)
        if seconds:
            return StartTimer(seconds, _timer_name(text, used))
        if re.search(r"\b(set|start|create|make|add)\b", text):
            return AskTimerDuration(_timer_name(text, used))
        return None

    if re.search(r"\bhow much time\b.*\bleft\b", text):
        return TimerStatus()

    if words & {"alarm", "alarms"} or re.search(r"\bwake me\b", text):
        if re.search(r"\b(cancel|delete|remove|clear|turn off|disable|stop)\b", text):
            when = parse_clock_time(text)
            if "all" in words or ("alarms" in words and "alarm" not in words):
                return CancelAlarm(all=True)
            if when is not None:
                return CancelAlarm(hour=when.hour, minute=when.minute, ambiguous=when.ambiguous)
            return CancelAlarm()
        # "set" after "alarm"/"is"/"are" is a question: "is there an alarm set"
        if re.search(r"\b(what|when|which|do i have|is there|any)\b", text) and not re.search(
            r"\b(?<!alarm )(?<!alarms )(?<!is )(?<!are )set\b|\bwake me\b", text
        ):
            return AlarmStatus()
        when = parse_clock_time(text)
        repeat, day = _repeat_days(text)
        if when is not None:
            return SetAlarm(
                when.hour, when.minute, repeat=repeat, day=day, ambiguous=when.ambiguous
            )
        if re.search(r"\b(set|create|make|add|wake me)\b", text):
            return AskAlarmTime(repeat=repeat, day=day)
        return None

    return None


def recognize_answer(question: Intent, text: str) -> Intent | None:
    """Interpret the reply to an :class:`AskTimerDuration` / :class:`AskAlarmTime` question."""
    text = normalize(text)
    if isinstance(question, AskTimerDuration):
        seconds, _ = parse_duration(text)
        return StartTimer(seconds, question.name) if seconds else None
    if isinstance(question, AskAlarmTime):
        # "7" / "seven thirty" alone: treat the whole answer as the time
        when = parse_clock_time(text) or parse_clock_time(f"at {text}")
        if when is None:
            return None
        repeat, day = _repeat_days(text)
        return SetAlarm(
            when.hour,
            when.minute,
            repeat=repeat or question.repeat,
            day=day if day is not None else question.day,
            ambiguous=when.ambiguous,
        )
    return None


# ---------------------------------------------------------------------------
# Phrasing


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def describe_duration(seconds: float) -> str:
    """7 -> "7 seconds", 312 -> "5 minutes and 12 seconds", 3900 -> "1 hour and 5 minutes"."""
    seconds = max(0, round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(_plural(hours, "hour"))
    if minutes:
        parts.append(_plural(minutes, "minute"))
    if secs and not hours and (minutes < 10):
        parts.append(_plural(secs, "second"))
    return _join(parts) or "0 seconds"


def describe_clock(hour: int, minute: int, clock_24h: bool = False) -> str:
    if clock_24h:
        return f"{hour:02d}:{minute:02d}"
    suffix = "AM" if hour < 12 else "PM"
    display = hour % 12 or 12
    return f"{display}:{minute:02d} {suffix}" if minute else f"{display} {suffix}"


def describe_repeat(repeat: frozenset[int]) -> str:
    if repeat == EVERY_DAY:
        return "every day"
    if repeat == WEEKDAYS:
        return "on weekdays"
    if repeat == WEEKENDS:
        return "on weekends"
    return "every " + _join([DAY_NAMES[d].capitalize() for d in sorted(repeat)])
