"""Canonical, provider-tagged receipts for governed native workspace prompts."""

import re

_RECEIPT_FIELDS = {"channel", "target", "message_id", "thread_id", "team_id"}
_CHANNEL = re.compile(r"[CDG][A-Z0-9]{1,63}\Z")
_TEAM = re.compile(r"T[A-Z0-9]{1,63}\Z")
_USER = re.compile(r"[UW][A-Z0-9]{1,63}\Z")
_TIMESTAMP = re.compile(r"[0-9]{1,20}\.[0-9]{1,6}\Z")
_SNOWFLAKE = re.compile(r"[1-9][0-9]{0,19}\Z")
_DATA = re.compile(r"h067:[A-Za-z0-9_-]{16}:[0-9]{1,10}:[a-z][0-9]?\Z")


def _matches(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


def valid_receipt(receipt):
    if type(receipt) is not dict or set(receipt) != _RECEIPT_FIELDS:
        return False
    if receipt["channel"] == "slack":
        return (_matches(_CHANNEL, receipt["target"])
                and _matches(_TIMESTAMP, receipt["message_id"])
                and _matches(_TEAM, receipt["team_id"])
                and (receipt["thread_id"] is None or _matches(_TIMESTAMP, receipt["thread_id"])))
    if receipt["channel"] == "discord":
        return (_matches(_SNOWFLAKE, receipt["target"])
                and _matches(_SNOWFLAKE, receipt["message_id"])
                and receipt["thread_id"] is None and receipt["team_id"] is None)
    return False


def receipt_identity(receipt):
    return tuple(receipt[k] for k in ("channel", "target", "message_id", "thread_id", "team_id"))


def valid_callback(callback, channel):
    if type(callback) is not dict or callback.get("channel") != channel:
        return False
    receipt = {k: callback.get(k) for k in _RECEIPT_FIELDS}
    if not valid_receipt(receipt) or not _matches(_DATA, callback.get("data")):
        return False
    sender = callback.get("sender")
    if channel == "discord":
        return _matches(_SNOWFLAKE, sender)
    if type(sender) is not str:
        return False
    team, separator, user = sender.partition(":")
    return separator == ":" and team == receipt["team_id"] and _matches(_USER, user)


def receipt_matches(receipt, channel, delivery, sender):
    if not valid_receipt(receipt) or receipt["channel"] != channel:
        return False
    if channel == "slack":
        return (receipt["target"] == delivery.get("slack_channel")
                and receipt["thread_id"] == delivery.get("thread_ts")
                and type(sender) is str and sender.partition(":")[0] == receipt["team_id"])
    target = delivery.get("channel_id")
    return (type(target) in {str, int} and type(target) is not bool
            and receipt["target"] == str(target))


def valid_markup(markup):
    if type(markup) is not dict or set(markup) != {"inline_keyboard"}:
        return False
    rows = markup["inline_keyboard"]
    if type(rows) is not list or not 1 <= len(rows) <= 25:
        return False
    count = 0
    for row in rows:
        if type(row) is not list or not 1 <= len(row) <= 5:
            return False
        for button in row:
            if (type(button) is not dict or set(button) != {"text", "callback_data"}
                    or type(button["text"]) is not str or not 1 <= len(button["text"]) <= 16384
                    or not _matches(_DATA, button["callback_data"])):
                return False
            count += 1
    return count <= 25


def pack_markup(markup):
    """Keep signed task payloads inside the existing canonical nesting bound."""
    return [{"row": index, **button} for index, row in enumerate(markup["inline_keyboard"])
            for button in row]


def unpack_markup(buttons):
    if type(buttons) is not list or not 1 <= len(buttons) <= 25:
        return None
    rows = []
    for button in buttons:
        if type(button) is not dict or set(button) != {"row", "text", "callback_data"}:
            return None
        index = button["row"]
        if type(index) is not int or index < 0 or index > len(rows):
            return None
        if index == len(rows):
            rows.append([])
        elif index != len(rows) - 1:
            return None
        rows[index].append({"text": button["text"], "callback_data": button["callback_data"]})
    markup = {"inline_keyboard": rows}
    return markup if valid_markup(markup) else None
