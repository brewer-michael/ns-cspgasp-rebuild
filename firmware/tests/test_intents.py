"""On-device intents: what the speaker handles itself, and what it passes on."""

from __future__ import annotations

import pytest

from open_speaker.intents import (
    EVERY_DAY,
    TOMORROW,
    WEEKDAYS,
    WEEKENDS,
    AlarmStatus,
    AskAlarmTime,
    AskTimerDuration,
    CancelAlarm,
    CancelTimer,
    ChangeVolume,
    ClockTime,
    Intent,
    SetAlarm,
    Snooze,
    StartTimer,
    Stop,
    TimerStatus,
    describe_clock,
    describe_duration,
    describe_repeat,
    normalize,
    parse_clock_time,
    parse_duration,
    parse_number,
    recognize,
    recognize_answer,
)

MONDAY, FRIDAY, SATURDAY = 0, 4, 5

START_TIMER = [
    ("set a timer for 5 minutes", StartTimer(300)),
    ("Set a timer for five minutes.", StartTimer(300)),
    ("timer for 10 seconds", StartTimer(10)),
    ("set timer 10 minutes", StartTimer(600)),
    ("set a 10 minute timer", StartTimer(600)),
    ("set a ten-minute timer", StartTimer(600)),
    ("10 minute timer", StartTimer(600)),
    ("start a timer for an hour", StartTimer(3600)),
    ("set a timer for 90 seconds", StartTimer(90)),
    ("set a timer for 45 secs", StartTimer(45)),
    ("set a timer for 5 min", StartTimer(300)),
    ("set a timer for 2 hrs", StartTimer(7200)),
    ("set a timer for 1.5 minutes", StartTimer(90)),
    ("set a timer for twenty five minutes", StartTimer(1500)),
    ("set a timer for a hundred seconds", StartTimer(100)),
    ("set a timer for one hundred and twenty seconds", StartTimer(120)),
    ("set a timer for 1 hour and 15 minutes", StartTimer(4500)),
    ("set a timer for 1 hour 30 minutes", StartTimer(5400)),
    ("set a timer for 2 minutes 30 seconds", StartTimer(150)),
    ("set a timer for fifteen minutes and thirty seconds", StartTimer(930)),
    ("set a timer for a couple of minutes", StartTimer(120)),
    ("set a timer for half an hour", StartTimer(1800)),
    ("set a timer for a quarter of an hour", StartTimer(900)),
    ("set a timer for a quarter hour", StartTimer(900)),
    ("um set a timer for uh 5 minutes please", StartTimer(300)),
    # "and a half"
    ("set a timer for an hour and a half", StartTimer(5400)),
    ("set a timer for one and a half hours", StartTimer(5400)),
    ("set a timer for 2 and a half minutes", StartTimer(150)),
    ("set a timer for a minute and a half", StartTimer(90)),
    ("set a timer for 1 hour and a half", StartTimer(5400)),
    # named timers
    ("set a tea timer for 3 minutes", StartTimer(180, "tea")),
    ("set a timer called tea for 3 minutes", StartTimer(180, "tea")),
    ("timer called tea for 3 minutes", StartTimer(180, "tea")),
    ("set a timer named pasta for 8 minutes", StartTimer(480, "pasta")),
    ("set a timer for 3 minutes called tea", StartTimer(180, "tea")),
    ("set a pizza timer for 12 minutes", StartTimer(720, "pizza")),
    ("set a 5 minute egg timer", StartTimer(300, "egg")),
    ("start a 25 minute pomodoro timer", StartTimer(1500, "pomodoro")),
    ("set a green tea timer for 3 minutes", StartTimer(180, "green tea")),
    ("set a timer called green tea for 3 minutes", StartTimer(180, "green tea")),
    ("set a timer for 10 minutes for the pizza", StartTimer(600, "pizza")),
    # no duration: ask for one
    ("set a timer", AskTimerDuration()),
    ("start a timer", AskTimerDuration()),
    ("set a tea timer", AskTimerDuration("tea")),
    ("set a timer for 0 minutes", AskTimerDuration()),
]

TIMER_CONTROL = [
    ("cancel the timer", CancelTimer()),
    ("cancel my timer", CancelTimer()),
    ("turn off the timer", CancelTimer()),
    ("stop the tea timer", CancelTimer("tea")),
    ("delete the pizza timer", CancelTimer("pizza")),
    ("cancel the timer called tea", CancelTimer("tea")),
    ("cancel all timers", CancelTimer(all=True)),
    ("cancel all the timers", CancelTimer(all=True)),
    ("cancel the timers", CancelTimer(all=True)),
    ("how much time is left on the timer", TimerStatus()),
    ("how much time is left", TimerStatus()),
    ("how long is left on the tea timer", TimerStatus("tea")),
    ("how much time left on my pizza timer", TimerStatus("pizza")),
    ("what's left on the timer", TimerStatus()),
    ("check the timer", TimerStatus()),
    ("timer status", TimerStatus()),
]

SET_ALARM = [
    # 12-hour clock with am/pm
    ("set an alarm for 7 am", SetAlarm(7, 0)),
    ("set an alarm for 7am", SetAlarm(7, 0)),
    ("Set an alarm for 7:30 a.m.", SetAlarm(7, 30)),
    ("set an alarm for 6.30 am", SetAlarm(6, 30)),
    ("set an alarm for 6:45 pm", SetAlarm(18, 45)),
    ("set an alarm for 5 PM", SetAlarm(17, 0)),
    ("set an alarm for seven thirty am", SetAlarm(7, 30)),
    ("set an alarm for six thirty pm", SetAlarm(18, 30)),
    ("set an alarm for quarter past seven am", SetAlarm(7, 15)),
    ("set an alarm for 12 am", SetAlarm(0, 0)),
    ("set an alarm for 12:30 am", SetAlarm(0, 30)),
    ("set an alarm for 12 pm", SetAlarm(12, 0)),
    ("set alarm 6 am", SetAlarm(6, 0)),
    ("set a 7 am alarm", SetAlarm(7, 0)),
    ("set an alarm for seven o'clock in the morning", SetAlarm(7, 0)),
    ("wake me up in the morning at 6", SetAlarm(6, 0)),
    ("set an alarm for 5:30 in the afternoon", SetAlarm(17, 30)),
    ("set an alarm for 8 in the evening", SetAlarm(20, 0)),
    ("set an alarm for 10 at night", SetAlarm(22, 0)),
    ("set an alarm for 12 at night", SetAlarm(0, 0)),
    ("set an alarm for 7 tonight", SetAlarm(19, 0)),
    ("set an alarm for noon", SetAlarm(12, 0)),
    ("set an alarm for midnight", SetAlarm(0, 0)),
    # 24-hour clock
    ("set an alarm for 19:30", SetAlarm(19, 30)),
    ("set an alarm for 0:15", SetAlarm(0, 15)),
    ("set an alarm for 17", SetAlarm(17, 0)),
    ("set an alarm for 24:00", SetAlarm(0, 0)),
    # no am/pm: the hour is ambiguous (12 is stored as 0)
    ("set an alarm for 7", SetAlarm(7, 0, ambiguous=True)),
    ("set an alarm for seven", SetAlarm(7, 0, ambiguous=True)),
    ("alarm at 6", SetAlarm(6, 0, ambiguous=True)),
    ("set an alarm for seven thirty", SetAlarm(7, 30, ambiguous=True)),
    ("set an alarm for six oh five", SetAlarm(6, 5, ambiguous=True)),
    ("set an alarm for 7 45", SetAlarm(7, 45, ambiguous=True)),
    ("wake me up at 6:30", SetAlarm(6, 30, ambiguous=True)),
    ("wake me up at 6 30", SetAlarm(6, 30, ambiguous=True)),
    ("set an alarm for 12:30", SetAlarm(0, 30, ambiguous=True)),
    ("set an alarm for 7 o'clock", SetAlarm(7, 0, ambiguous=True)),
    ("set a 7 o'clock alarm", SetAlarm(7, 0, ambiguous=True)),
    ("set an alarm for half past six", SetAlarm(6, 30, ambiguous=True)),
    ("set an alarm for quarter to 8", SetAlarm(7, 45, ambiguous=True)),
    ("set an alarm for 20 past 6", SetAlarm(6, 20, ambiguous=True)),
    ("set an alarm for ten to seven", SetAlarm(6, 50, ambiguous=True)),
    ("wake me at 5 to 7", SetAlarm(6, 55, ambiguous=True)),
    ("set an alarm for twenty past seven", SetAlarm(7, 20, ambiguous=True)),
    ("set an alarm for twenty five past seven", SetAlarm(7, 25, ambiguous=True)),
    ("set an alarm for twenty five to eight", SetAlarm(7, 35, ambiguous=True)),
    # tomorrow, or a given day
    ("set an alarm for 6:30 tomorrow", SetAlarm(6, 30, day=TOMORROW, ambiguous=True)),
    ("set an alarm for tomorrow at 6:30 am", SetAlarm(6, 30, day=TOMORROW)),
    ("wake me up at 6 am tomorrow", SetAlarm(6, 0, day=TOMORROW)),
    ("set an alarm for 7 am on friday", SetAlarm(7, 0, day=FRIDAY)),
    ("set an alarm for friday at 7 am", SetAlarm(7, 0, day=FRIDAY)),
    ("set an alarm on saturday for 9", SetAlarm(9, 0, day=SATURDAY, ambiguous=True)),
    # repeating
    ("set an alarm for 6:30 am every weekday", SetAlarm(6, 30, WEEKDAYS)),
    ("set an alarm for 6:30 am on weekdays", SetAlarm(6, 30, WEEKDAYS)),
    ("set an alarm for 7 am on workdays", SetAlarm(7, 0, WEEKDAYS)),
    ("set a weekday alarm for 6:30", SetAlarm(6, 30, WEEKDAYS, ambiguous=True)),
    ("set an alarm for 7 in the morning every weekday", SetAlarm(7, 0, WEEKDAYS)),
    ("set an alarm for 9 am on weekends", SetAlarm(9, 0, WEEKENDS)),
    ("set an alarm for 8 am every weekend", SetAlarm(8, 0, WEEKENDS)),
    ("set an alarm for 7 am every day", SetAlarm(7, 0, EVERY_DAY)),
    ("set an alarm for 7 am everyday", SetAlarm(7, 0, EVERY_DAY)),
    ("set an alarm for 7 am daily", SetAlarm(7, 0, EVERY_DAY)),
    ("set an alarm for 7 am every monday", SetAlarm(7, 0, frozenset({MONDAY}))),
    ("set an alarm for 7 am on mondays", SetAlarm(7, 0, frozenset({MONDAY}))),
    ("set an alarm for 7 am every monday and wednesday", SetAlarm(7, 0, frozenset({0, 2}))),
    ("set an alarm for 7 am on mondays and wednesdays", SetAlarm(7, 0, frozenset({0, 2}))),
    ("set an alarm for 7 am every tuesday thursday", SetAlarm(7, 0, frozenset({1, 3}))),
    (
        "set an alarm for 7 am every monday, wednesday and friday",
        SetAlarm(7, 0, frozenset({0, 2, 4})),
    ),
    ("set an alarm for 7 am every saturday and sunday", SetAlarm(7, 0, WEEKENDS)),
    # no time of day: ask for one
    ("set an alarm", AskAlarmTime()),
    ("set an alarm for tomorrow", AskAlarmTime(day=TOMORROW)),
    ("wake me up tomorrow", AskAlarmTime(day=TOMORROW)),
    ("set an alarm every weekday", AskAlarmTime(repeat=WEEKDAYS)),
    ("set an alarm in 20 minutes", AskAlarmTime()),
    ("set an alarm for 10 minutes", AskAlarmTime()),
    ("set an alarm for an hour", AskAlarmTime()),
]

ALARM_CONTROL = [
    ("cancel my alarm", CancelAlarm()),
    ("cancel the alarm", CancelAlarm()),
    ("disable my alarm", CancelAlarm()),
    ("cancel all alarms", CancelAlarm(all=True)),
    ("cancel all my alarms", CancelAlarm(all=True)),
    ("delete my alarms", CancelAlarm(all=True)),
    ("cancel my 7 am alarm", CancelAlarm(7, 0)),
    ("cancel the alarm at 6:30 pm", CancelAlarm(18, 30)),
    ("cancel my six thirty pm alarm", CancelAlarm(18, 30)),
    ("cancel the 6:30 alarm", CancelAlarm(6, 30, ambiguous=True)),
    ("cancel my seven thirty alarm", CancelAlarm(7, 30, ambiguous=True)),
    ("cancel the alarm for 7", CancelAlarm(7, 0, ambiguous=True)),
    ("delete the 7 o'clock alarm", CancelAlarm(7, 0, ambiguous=True)),
    ("what alarms do i have", AlarmStatus()),
    ("what are my alarms", AlarmStatus()),
    ("what time is my alarm", AlarmStatus()),
    ("when is my alarm", AlarmStatus()),
    ("do i have any alarms", AlarmStatus()),
    ("are there any alarms", AlarmStatus()),
    ("is there an alarm set", AlarmStatus()),
    ("which alarms are set", AlarmStatus()),
    ("do i have an alarm set for tomorrow", AlarmStatus()),
    ("what time is my alarm set for", AlarmStatus()),
    ("is my alarm set", AlarmStatus()),
    ("is my alarm on", AlarmStatus()),
    ("are my alarms set for tomorrow", AlarmStatus()),
    ("have i set an alarm", AlarmStatus()),
    ("did i set an alarm for tomorrow", AlarmStatus()),
]

STOP_AND_SNOOZE = [
    ("stop", Stop()),
    ("Stop!", Stop()),
    ("  STOP  ", Stop()),
    ("OK stop", Stop()),
    ("Hey, stop.", Stop()),
    ("stop it", Stop()),
    ("stop the timer", Stop()),
    ("cancel", Stop()),
    ("never mind", Stop()),
    ("nevermind", Stop()),
    ("be quiet", Stop()),
    ("shut up", Stop()),
    ("that's enough", Stop()),
    ("that\u2019s enough", Stop()),
    ("stop the alarm", Stop(alarm=True)),
    ("turn off the alarm", Stop(alarm=True)),
    ("turn the alarm off", Stop(alarm=True)),
    ("alarm off", Stop(alarm=True)),
    ("dismiss the alarm", Stop(alarm=True)),
    ("snooze", Snooze()),
    ("snooze the alarm", Snooze()),
    ("snooze for 5 minutes", Snooze(5)),
    ("snooze for ten minutes", Snooze(10)),
    ("snooze 15 minutes", Snooze(15)),
    ("snooze for an hour", Snooze(60)),
    ("snooze for 30 seconds", Snooze(1)),
    ("snooze for 90 seconds", Snooze(2)),
]

VOLUME = [
    ("volume up", ChangeVolume(steps=1)),
    ("louder", ChangeVolume(steps=1)),
    ("Louder, please!", ChangeVolume(steps=1)),
    ("a bit louder", ChangeVolume(steps=1)),
    ("make it louder", ChangeVolume(steps=1)),
    ("turn it up", ChangeVolume(steps=1)),
    ("crank it up", ChangeVolume(steps=1)),
    ("turn the volume up", ChangeVolume(steps=1)),
    ("turn up the volume", ChangeVolume(steps=1)),
    ("increase the volume", ChangeVolume(steps=1)),
    ("raise volume", ChangeVolume(steps=1)),
    ("volume down", ChangeVolume(steps=-1)),
    ("quieter", ChangeVolume(steps=-1)),
    ("softer", ChangeVolume(steps=-1)),
    ("a little quieter", ChangeVolume(steps=-1)),
    ("make it softer", ChangeVolume(steps=-1)),
    ("turn it down", ChangeVolume(steps=-1)),
    ("turn down the volume", ChangeVolume(steps=-1)),
    ("bring the volume down", ChangeVolume(steps=-1)),
    ("decrease volume", ChangeVolume(steps=-1)),
    ("lower the volume", ChangeVolume(steps=-1)),
    ("reduce the volume", ChangeVolume(steps=-1)),
    # 0-10 is a scale of ten, anything else is a percentage
    ("set the volume to 5", ChangeVolume(level=50)),
    ("volume 7", ChangeVolume(level=70)),
    ("volume at 3", ChangeVolume(level=30)),
    ("volume level 4", ChangeVolume(level=40)),
    ("set the volume to 10", ChangeVolume(level=100)),
    ("set the volume to 0", ChangeVolume(level=0)),
    ("volume zero", ChangeVolume(level=0)),
    ("set the volume to fifty", ChangeVolume(level=50)),
    ("volume to 50 percent", ChangeVolume(level=50)),
    ("set volume to 30%", ChangeVolume(level=30)),
    ("set the volume to 10 percent", ChangeVolume(level=10)),
    ("set volume to seventy five percent", ChangeVolume(level=75)),
    ("set volume to 150", ChangeVolume(level=100)),
    ("max volume", ChangeVolume(level=100)),
    ("maximum volume", ChangeVolume(level=100)),
    ("full volume", ChangeVolume(level=100)),
    ("volume to max", ChangeVolume(level=100)),
]

NOT_INTENTS = [
    "",
    "   ",
    "what's the weather like",
    "what time is it",
    "turn on the kitchen lights",
    "set the thermostat to 20",
    "turn up the heat",
    "play some music",
    "stop playing music in the kitchen",
    "stop the dishwasher",
    "cancel my dentist appointment",
    "tell me a joke",
    "how long does it take to boil an egg",
    "what is 5 minutes in seconds",
    "remind me in 10 minutes",
    "the alarm clock is broken",
    "what's the volume",
    "timer",
    "alarm",
    "volume",
]


def _check(text: str, expected: Intent) -> None:
    assert recognize(text) == expected


@pytest.mark.parametrize(("text", "expected"), START_TIMER)
def test_start_timer(text: str, expected: Intent) -> None:
    _check(text, expected)


@pytest.mark.parametrize(("text", "expected"), TIMER_CONTROL)
def test_cancel_and_check_timers(text: str, expected: Intent) -> None:
    _check(text, expected)


@pytest.mark.parametrize(("text", "expected"), SET_ALARM)
def test_set_alarm(text: str, expected: Intent) -> None:
    _check(text, expected)


@pytest.mark.parametrize(("text", "expected"), ALARM_CONTROL)
def test_cancel_and_check_alarms(text: str, expected: Intent) -> None:
    _check(text, expected)


@pytest.mark.parametrize(("text", "expected"), STOP_AND_SNOOZE)
def test_stop_and_snooze(text: str, expected: Intent) -> None:
    _check(text, expected)


@pytest.mark.parametrize(("text", "expected"), VOLUME)
def test_volume(text: str, expected: Intent) -> None:
    _check(text, expected)


@pytest.mark.parametrize("text", NOT_INTENTS)
def test_everything_else_goes_to_the_assistant(text: str) -> None:
    assert recognize(text) is None


@pytest.mark.parametrize(
    ("question", "answer", "expected"),
    [
        (AskTimerDuration(), "5 minutes", StartTimer(300)),
        (AskTimerDuration(), "an hour and a half", StartTimer(5400)),
        (AskTimerDuration("tea"), "three minutes", StartTimer(180, "tea")),
        (AskTimerDuration(), "ten", None),
        (AskTimerDuration(), "never mind", None),
        (AskAlarmTime(), "7", SetAlarm(7, 0, ambiguous=True)),
        (AskAlarmTime(), "seven thirty", SetAlarm(7, 30, ambiguous=True)),
        (AskAlarmTime(), "7:30 am", SetAlarm(7, 30)),
        (AskAlarmTime(), "6 pm", SetAlarm(18, 0)),
        (AskAlarmTime(), "19:45", SetAlarm(19, 45)),
        (AskAlarmTime(), "noon", SetAlarm(12, 0)),
        (AskAlarmTime(), "half past six", SetAlarm(6, 30, ambiguous=True)),
        (AskAlarmTime(), "tomorrow at 7", SetAlarm(7, 0, day=TOMORROW, ambiguous=True)),
        (AskAlarmTime(), "7 am every weekday", SetAlarm(7, 0, WEEKDAYS)),
        # the question's day or repeat carries over unless the answer names its own
        (AskAlarmTime(repeat=WEEKDAYS), "6:30 am", SetAlarm(6, 30, WEEKDAYS)),
        (
            AskAlarmTime(repeat=WEEKDAYS),
            "7 every weekend",
            SetAlarm(7, 0, WEEKENDS, ambiguous=True),
        ),
        (AskAlarmTime(day=TOMORROW), "6:30 am", SetAlarm(6, 30, day=TOMORROW)),
        (
            AskAlarmTime(day=TOMORROW),
            "6:30 on saturday",
            SetAlarm(6, 30, day=SATURDAY, ambiguous=True),
        ),
        (AskAlarmTime(), "25", None),
        (AskAlarmTime(), "10 minutes", None),
        (AskAlarmTime(), "banana", None),
        (AskAlarmTime(), "never mind", None),
        (Stop(), "7 am", None),
    ],
)
def test_recognize_answer(question: Intent, answer: str, expected: Intent | None) -> None:
    assert recognize_answer(question, answer) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Set an Alarm for 7 A.M.", "set an alarm for 7 am"),
        ("wake me at 7am", "wake me at 7 am"),
        ("at 7PM", "at 7 pm"),
        ("Hey, can you set a timer, please?", "set a timer"),
        ("um uh okay stop", "stop"),
        ("a five-minute timer", "a five minute timer"),
        ("volume 50%", "volume 50 percent"),
        ("at 7:30 or 6.30.", "at 7:30 or 6.30"),
        ("seven o'clock", "seven oclock"),
        ("that\u2019s enough", "that's enough"),
    ],
)
def test_normalize(text: str, expected: str) -> None:
    assert normalize(text) == expected


@pytest.mark.parametrize(
    ("words", "index", "expected"),
    [
        (["5"], 0, (5.0, 1)),
        (["2.5"], 0, (2.5, 1)),
        (["twenty"], 0, (20.0, 1)),
        (["twenty", "five"], 0, (25.0, 2)),
        (["ninety", "nine"], 0, (99.0, 2)),
        (["oh"], 0, (0.0, 1)),
        (["a"], 0, (1.0, 1)),
        (["an", "hour"], 0, (1.0, 1)),
        (["a", "couple"], 0, (2.0, 2)),
        (["a", "couple", "of", "minutes"], 0, (2.0, 3)),
        (["half", "an", "hour"], 0, (0.5, 1)),
        (["a", "half"], 0, (0.5, 2)),
        (["2", "and", "a", "half"], 0, (2.5, 4)),
        (["two", "and", "a", "half"], 0, (2.5, 4)),
        (["a", "hundred"], 0, (100.0, 2)),
        (["one", "hundred", "and", "twenty"], 0, (120.0, 4)),
        (["set", "5", "minutes"], 1, (5.0, 2)),
        (["minutes"], 0, (None, 0)),
        (["5"], 3, (None, 3)),
        ([], 0, (None, 0)),
    ],
)
def test_parse_number(words: list[str], index: int, expected: tuple[float | None, int]) -> None:
    assert parse_number(words, index) == expected


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("5 minutes", 300),
        ("1.5 hours", 5400),
        ("twenty five seconds", 25),
        ("half an hour", 1800),
        ("quarter hour", 900),
        ("3 hrs 20 mins 10 secs", 12010),
        ("0 minutes", None),
        ("5", None),
        ("no duration here", None),
    ],
)
def test_parse_duration(text: str, seconds: int | None) -> None:
    assert parse_duration(text)[0] == seconds


@pytest.mark.parametrize(
    ("text", "used"),
    [
        ("set a timer for 5 minutes", {4, 5}),
        ("an hour and 15 minutes", {0, 1, 3, 4}),
        ("a minute and a half", {0, 1, 2, 3, 4}),
        ("a quarter of an hour", {0, 1, 2, 3, 4}),
        ("tea for two", set()),
    ],
)
def test_parse_duration_reports_the_words_it_used(text: str, used: set[int]) -> None:
    assert parse_duration(text)[1] == used


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("at 7", ClockTime(7, 0, ambiguous=True)),
        ("at 7 am", ClockTime(7, 0)),
        ("at 7 pm", ClockTime(19, 0)),
        ("7:30 pm", ClockTime(19, 30)),
        ("at 12", ClockTime(0, 0, ambiguous=True)),
        ("at 12 am", ClockTime(0, 0)),
        ("at 12 pm", ClockTime(12, 0)),
        ("19:45", ClockTime(19, 45)),
        ("19:45 pm", ClockTime(19, 45)),
        ("0:05", ClockTime(0, 5)),
        ("24:00", ClockTime(0, 0)),
        ("noon", ClockTime(12, 0)),
        ("midday", ClockTime(12, 0)),
        ("midnight", ClockTime(0, 0)),
        ("at seven thirty", ClockTime(7, 30, ambiguous=True)),
        ("at six oh five", ClockTime(6, 5, ambiguous=True)),
        ("half past six", ClockTime(6, 30, ambiguous=True)),
        ("quarter to 8", ClockTime(7, 45, ambiguous=True)),
        ("quarter to one", ClockTime(0, 45, ambiguous=True)),
        ("ten past twelve", ClockTime(0, 10, ambiguous=True)),
        ("twenty five past seven", ClockTime(7, 25, ambiguous=True)),
        ("the 7 oclock alarm", ClockTime(7, 0, ambiguous=True)),
        ("my six thirty pm alarm", ClockTime(18, 30)),
        ("at 7 in the morning", ClockTime(7, 0)),
        ("at 3 in the afternoon", ClockTime(15, 0)),
        ("at 9 in the evening", ClockTime(21, 0)),
        ("at 10 at night", ClockTime(22, 0)),
        ("at 12 at night", ClockTime(0, 0)),
        ("at 7 tonight", ClockTime(19, 0)),
        ("for 10 minutes", None),
        ("at 25", None),
        ("7:75", None),
        ("tell me a joke", None),
    ],
)
def test_parse_clock_time(text: str, expected: ClockTime | None) -> None:
    assert parse_clock_time(text) == expected


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "0 seconds"),
        (1, "1 second"),
        (7, "7 seconds"),
        (60, "1 minute"),
        (61, "1 minute and 1 second"),
        (312, "5 minutes and 12 seconds"),
        (599, "9 minutes and 59 seconds"),
        (605, "10 minutes"),
        (3600, "1 hour"),
        (3661, "1 hour and 1 minute"),
        (3900, "1 hour and 5 minutes"),
        (5400, "1 hour and 30 minutes"),
        (7322, "2 hours and 2 minutes"),
        (59.6, "1 minute"),
        (0.4, "0 seconds"),
        (-5, "0 seconds"),
    ],
)
def test_describe_duration(seconds: float, text: str) -> None:
    assert describe_duration(seconds) == text


@pytest.mark.parametrize(
    ("hour", "minute", "clock_24h", "text"),
    [
        (7, 0, False, "7 AM"),
        (7, 30, False, "7:30 AM"),
        (19, 5, False, "7:05 PM"),
        (0, 0, False, "12 AM"),
        (0, 15, False, "12:15 AM"),
        (12, 0, False, "12 PM"),
        (12, 30, False, "12:30 PM"),
        (7, 0, True, "07:00"),
        (19, 5, True, "19:05"),
        (0, 0, True, "00:00"),
    ],
)
def test_describe_clock(hour: int, minute: int, clock_24h: bool, text: str) -> None:
    assert describe_clock(hour, minute, clock_24h) == text


@pytest.mark.parametrize(
    ("repeat", "text"),
    [
        (EVERY_DAY, "every day"),
        (WEEKDAYS, "on weekdays"),
        (WEEKENDS, "on weekends"),
        (frozenset({6}), "every Sunday"),
        (frozenset({0, 2}), "every Monday and Wednesday"),
        (frozenset({4, 0, 2}), "every Monday, Wednesday and Friday"),
    ],
)
def test_describe_repeat(repeat: frozenset[int], text: str) -> None:
    assert describe_repeat(repeat) == text


def test_recognized_timers_and_alarms_read_back_naturally() -> None:
    timer = recognize("set a timer for an hour and a half")
    alarm = recognize("set an alarm for 6:30 am on weekdays")
    assert isinstance(timer, StartTimer)
    assert isinstance(alarm, SetAlarm)
    assert describe_duration(timer.seconds) == "1 hour and 30 minutes"
    assert f"{describe_clock(alarm.hour, alarm.minute)} {describe_repeat(alarm.repeat)}" == (
        "6:30 AM on weekdays"
    )
