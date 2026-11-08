"""XChat's Text Events (src/common/textevents.in): what each server event prints. $1 $2 are the event's values, $t splits
the left column from the text. Formats are the user's; the values come from the network and are never read as codes."""
from __future__ import annotations

import re

# name: (default format, what $1 $2 ... are, sample values for the preview and Test All)
EVENTS = {
    "Join": ("-->$t$1 ($3) has joined $2", ("nick", "channel", "host"), ("Belon", "#skinhead", "b@host.my")),
    "Part": ("<--$t$1 ($2) has left $3", ("nick", "host", "channel"), ("Belon", "b@host.my", "#skinhead")),
    "Part with Reason": ("<--$t$1 ($2) has left $3 ($4)", ("nick", "host", "channel", "reason"), ("Belon", "b@host.my", "#skinhead", "later")),
    "You Part": ("<--$tYou have left channel $1", ("channel",), ("#skinhead",)),
    "Quit": ("<--$t$1 has quit ($2)", ("nick", "reason"), ("Belon", "Leaving")),
    "Kick": ("<--$t$1 has kicked $2 from $3 ($4)", ("kicker", "nick", "channel", "reason"), ("Fhazal", "Belon", "#skinhead", "behave")),
    "You Kicked": ("<--$tYou have been kicked from $1 by $2 ($3)", ("channel", "kicker", "reason"), ("#skinhead", "Fhazal", "behave")),
    "Change Nick": ("*$t$1 is now known as $2", ("old nick", "new nick"), ("Belon", "Belon2")),
    "Your Nick Changing": ("*$tYou are now known as $1", ("new nick",), ("Badaboom2",)),
    "Topic Change": ("*$t$1 has changed the topic to: $2", ("nick", "topic"), ("Fhazal", "new topic")),
    "Topic": ("*$tTopic for $1 is: $2", ("channel", "topic"), ("#skinhead", "the topic")),
    "Topic Creation": ("*$tTopic for $1 set by $2 at $3", ("channel", "nick", "time"), ("#skinhead", "Fhazal", "Sat Nov 07 12:00:00 2026")),
    "Channel Operator": ("*$t$1 gives channel operator status to $2", ("nick", "target"), ("Fhazal", "Belon")),
    "Channel DeOp": ("*$t$1 removes channel operator status from $2", ("nick", "target"), ("Fhazal", "Belon")),
    "Channel Voice": ("*$t$1 gives voice to $2", ("nick", "target"), ("Fhazal", "Belon")),
    "Channel DeVoice": ("*$t$1 removes voice from $2", ("nick", "target"), ("Fhazal", "Belon")),
    "Channel Ban": ("*$t$1 sets ban on $2", ("nick", "mask"), ("Fhazal", "*!*@bad.host")),
    "Channel UnBan": ("*$t$1 removes ban on $2", ("nick", "mask"), ("Fhazal", "*!*@bad.host")),
    "Invited": ("*$tYou have been invited to $1 by $2 ($3)", ("channel", "nick", "host"), ("#skinhead", "Belon", "b@host.my")),
    "Away Line": ("*$t$1 is away: $2", ("nick", "reason"), ("Belon", "out to lunch")),
    "Notify Online": ("*$tNotify: $1 is online ($2).", ("nick", "network"), ("Belon", "SkinIRC")),
    "Notify Offline": ("*$tNotify: $1 is offline ($2).", ("nick", "network"), ("Belon", "SkinIRC")),
    "CTCP Generic": ("*$tReceived a CTCP $1 from $2", ("what", "nick"), ("VERSION", "Belon")),
    # 0.2.0: your own modes on connect (one line, the user's wording) and mIRC's Local host line
    "Your Modes": ("*$t$1 sets mode: %C11[%O $2 %C11]%O", ("nick", "modes"), ("Belon", "+iwxz")),   # brackets like Raw Modes
    "Local Host": ("*$tLocal host: $1 ($2)", ("host", "ip"), ("unknown", "192.168.1.20")),
}
_CODE = re.compile(r"\$(\d|t)|%([BUCOR%])")
_CODES = {"B": "\x02", "U": "\x1f", "C": "\x03", "O": "\x0f", "R": "\x16", "%": "%"}


def render(fmt: str, args) -> tuple[str, str]:
    """(left column, text). One pass, so a nick containing $1 or %B stays as it is."""
    parts = re.split(r"\$t", fmt, maxsplit=1)
    left, right = (parts[0], parts[1]) if len(parts) == 2 else ("*", parts[0])

    def fill(m):
        if m.group(2):
            return _CODES[m.group(2)]
        i = int(m.group(1)) - 1
        return args[i] if 0 <= i < len(args) else ""
    return _CODE.sub(fill, left), _CODE.sub(fill, right)
