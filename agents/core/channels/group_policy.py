"""Inbound & group-chat policy ladder for chat adapters (H059, H111).

Nerva's original gating vocabulary was a flat ``allowed_user_ids`` list plus three Telegram
room toggles. This module implements the full default-deny inbound & group authorization
ladder shared across adapters and the unified :class:`~agents.core.channels.gateway.Gateway`:

* **Default-deny & DM pairing (H059)** — unknown senders are denied by default; DM behaviour
  for unauthorized senders is configurable between ``"pair"`` (hand to ``SenderPairing``) and
  ``"ignore"`` (silent drop before any side effect). Network-exposed channels refuse an
  ``"open"`` policy unless ``allow_all_users`` (or ``JARVIS_CHANNEL_OPEN=1``) is explicitly
  opted into. WhatsApp ``@lid`` and phone JIDs canonicalize to one E.164 identity when a
  ``lid_map`` is known so pairing and allowlists treat one human as one principal.
* **Ordered group decision ladder & per-channel rules (H111)** — ignored channels/threads,
  own-message and bot filters run before any side effect; DM vs group scope is separated;
  room, forum-topic, Discord RBAC role, Matrix room, Feishu 3-tier ``group_rules``, WeCom
  ``dm_policy``/``group_policy``, Photon mention gating, and Slack's six composable triggers
  (``mention``, ``dm``, ``thread_reply``, ``keyword``, ``reaction``, ``prefix``) compose
  with ``exclusive_bot_mentions``, regex ``mention_patterns``, ``free_response_chats``,
  ``free_response_topics``, ``guest_mode``, and silent ``observe_mode`` attribution.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..env_config import env_flag, env_str, is_recognized_bool, truthy
from .pairing import channel_open_acknowledged

PRIVATE_CHAT_TYPES = frozenset({"private", "dm", "im", "direct", "personal"})
GROUP_CHAT_TYPES = frozenset({"group", "supergroup", "channel", "room", "space", "guild", "mpim"})

ANSWER = "answer"
OBSERVE = "observe"
PAIR = "pair"
DROP = "drop"

DM_POLICIES = frozenset({"pairing", "allowlist", "open", "disabled"})
GROUP_POLICIES = frozenset({"allowlist", "open", "disabled"})
UNAUTHORIZED_DM_BEHAVIORS = frozenset({"pair", "ignore"})
SLACK_TRIGGERS = frozenset({"mention", "dm", "thread_reply", "keyword", "reaction", "prefix"})

_WA_JID_SUFFIXES = ("@s.whatsapp.net", "@c.us")
_DIGITS_RE = re.compile(r"^\+?[1-9][0-9]{5,19}$")
_OTHER_BOT_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{2,64}bot)\b", re.IGNORECASE)


class ChannelPolicyError(ValueError):
    """Raised when an adapter configuration opens a network surface without opt-in."""

    def __init__(self, reason: str, channel: str = "") -> None:
        super().__init__(f"{channel}: {reason}" if channel else reason)
        self.reason = reason
        self.channel = channel


def _flag(raw: str | None, *, default: bool) -> bool:
    """One boolean convention in the tree (`env_config`); an unrecognised spelling keeps the default."""
    if raw is None or not is_recognized_bool(raw):
        return default
    return truthy(raw, default)


def _csv(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def _fset(values: Iterable[Any] | None) -> frozenset[str]:
    if not values:
        return frozenset()
    return frozenset(str(v).strip() for v in values if str(v).strip())


def _normalize_phone_token(raw: str) -> str:
    core = raw.split(":", 1)[0].strip()
    if _DIGITS_RE.fullmatch(core):
        return "+" + core.lstrip("+")
    return core


def canonicalize_whatsapp_identity(
    sender: Any,
    lid_map: Mapping[str, str] | None = None,
) -> str:
    """Canonicalize WhatsApp E.164 numbers, ``@s.whatsapp.net`` JIDs, and ``@lid`` IDs.

    ``1234567890:3@s.whatsapp.net``, ``1234567890@c.us``, ``1234567890``, and ``+1234567890``
    all canonicalize to ``+1234567890``. A linked-device ``<id>[:dev]@lid`` resolves through
    *lid_map* (matching either ``<id>@lid`` or bare ``<id>``, or reverse-mapped values) to the
    same ``+<digits>`` identity; an unmapped LID stays ``<id>@lid`` so two strangers never
    collide.
    """
    raw = str(sender or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    for suffix in _WA_JID_SUFFIXES:
        if lower.endswith(suffix):
            return _normalize_phone_token(raw[: -len(suffix)])
    if lower.endswith("@lid"):
        lid_base = raw[:-4].split(":", 1)[0].strip().lower()
        canonical_lid = f"{lid_base}@lid" if lid_base else lower
        mapped = _lookup_lid(lid_base, canonical_lid, lid_map)
        return mapped if mapped else canonical_lid
    return _normalize_phone_token(raw)


def _lookup_lid(
    lid_base: str,
    canonical_lid: str,
    lid_map: Mapping[str, str] | None,
) -> str | None:
    if not lid_map or not lid_base:
        return None
    for key, val in lid_map.items():
        k_norm = str(key or "").strip().lower()
        v_raw = str(val or "").strip()
        k_lid = k_norm[:-4].split(":", 1)[0] if k_norm.endswith("@lid") else k_norm
        if k_lid == lid_base and v_raw:
            return canonicalize_whatsapp_identity(v_raw, None)
        v_low = v_raw.lower()
        v_lid = v_low[:-4].split(":", 1)[0] if v_low.endswith("@lid") else ""
        if v_lid and v_lid == lid_base and key:
            return canonicalize_whatsapp_identity(key, None)
    return None


def validate_channel_open_policy(
    channel: str,
    *,
    dm_policy: str = "pairing",
    group_policy: str = "allowlist",
    allow_all_users: bool = False,
    network_exposed: bool = True,
) -> None:
    """Refuse ``open`` DM or group policies on network-exposed channels without explicit opt-in."""
    dm = str(dm_policy or "pairing").strip().lower()
    grp = str(group_policy or "allowlist").strip().lower()
    if dm not in DM_POLICIES:
        raise ChannelPolicyError(f"invalid_dm_policy:{dm}", channel)
    if grp not in GROUP_POLICIES:
        raise ChannelPolicyError(f"invalid_group_policy:{grp}", channel)
    if not network_exposed:
        return
    acknowledged = bool(allow_all_users) or channel_open_acknowledged()
    if (dm == "open" or grp == "open") and not acknowledged:
        raise ChannelPolicyError("open_policy_requires_allow_all_users", channel)


@dataclass(frozen=True)
class FeishuGroupRule:
    """Per-chat or wildcard Feishu group rule (tier 1: chat_id, tier 2: ``*``)."""

    enabled: bool = True
    require_mention: bool | None = None
    allow_from: frozenset[str] = frozenset()
    observe_mode: bool | None = None


def _env_val(environ: Mapping[str, str] | None, key: str, default: str | None = "") -> str | None:
    if environ is not None:
        val = environ.get(key)
        return default if val is None else val
    return env_str(key, default)  # type: ignore[arg-type]


@dataclass(frozen=True)
class GroupPolicy:
    """Inbound DM & room authorization policy across chat platforms (H059, H111)."""

    require_mention: bool = True
    allowed_chat_ids: frozenset[str] = frozenset()
    observe_mode: bool = False
    # H059 / H111 — DM & sender controls
    platform: str = ""
    dm_policy: str = "pairing"
    group_policy: str = "allowlist"
    unauthorized_dm_behavior: str = "pair"
    disable_dms: bool = False
    ignore_root_dm: bool = False
    allow_from: frozenset[str] = frozenset()
    group_allow_from: frozenset[str] = frozenset()
    allow_all_users: bool = False
    allow_bots: bool = False
    own_sender_ids: frozenset[str] = frozenset()
    # H111 — Room / topic / thread / guest / observe scoping
    allowed_topics: frozenset[str] = frozenset()
    ignored_channels: frozenset[str] = frozenset()
    ignored_threads: frozenset[str] = frozenset()
    free_response_chats: frozenset[str] = frozenset()
    free_response_topics: frozenset[str] = frozenset()
    guest_mode: bool = False
    attribute_observed_sender: bool = False
    # H111 — Mention, wake-word, and multi-bot exclusivity
    exclusive_bot_mentions: bool = False
    other_bot_usernames: frozenset[str] = frozenset()
    mention_patterns: tuple[str, ...] = ()
    # H111 — Platform-specific options
    slack_triggers: frozenset[str] = frozenset({"mention", "dm"})
    slack_keywords: tuple[str, ...] = ()
    slack_prefixes: tuple[str, ...] = ()
    allowed_role_ids: frozenset[str] = frozenset()
    matrix_allowed_rooms: frozenset[str] = frozenset()
    lid_map: Mapping[str, str] = field(default_factory=dict)
    feishu_group_rules: Mapping[str, FeishuGroupRule] = field(default_factory=dict)
    wecom_dm_policy: str | None = None
    wecom_group_policy: str | None = None

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        prefix: str = "TELEGRAM",
    ) -> GroupPolicy:
        """Build a channel policy from *environ* (or ``env_config`` when None)."""
        p = (prefix or "TELEGRAM").strip().upper()
        req_raw = _env_val(environ, f"{p}_GROUP_REQUIRE_MENTION", None)
        chats_raw = _env_val(environ, f"{p}_ALLOWED_CHAT_IDS", "")
        obs_raw = _env_val(environ, f"{p}_GROUP_OBSERVE", None)
        users_raw = _env_val(environ, f"{p}_ALLOWED_USERS", "") or _env_val(environ, f"{p}_ALLOWED_USER_IDS", "")
        grp_users_raw = _env_val(environ, f"{p}_GROUP_ALLOWED_USERS", "")
        allow_all_raw = _env_val(environ, f"{p}_ALLOW_ALL_USERS", None)
        dm_behav_raw = _env_val(environ, f"{p}_UNAUTHORIZED_DM_BEHAVIOR", "pair")
        ignored_raw = _env_val(environ, f"{p}_IGNORED_CHANNELS", "")
        free_raw = _env_val(environ, f"{p}_FREE_RESPONSE_CHATS", "")
        behav = str(dm_behav_raw or "pair").strip().lower()
        default_open = env_flag("JARVIS_CHANNEL_OPEN", False) if environ is None else _flag(environ.get("JARVIS_CHANNEL_OPEN"), default=False)
        return cls(
            platform=p.lower(),
            require_mention=_flag(req_raw, default=True),
            allowed_chat_ids=frozenset(_csv(chats_raw)),
            observe_mode=_flag(obs_raw, default=False),
            allow_from=frozenset(_csv(users_raw)),
            group_allow_from=frozenset(_csv(grp_users_raw)),
            allow_all_users=_flag(allow_all_raw, default=default_open),
            unauthorized_dm_behavior=behav if behav in UNAUTHORIZED_DM_BEHAVIORS else "pair",
            ignored_channels=frozenset(_csv(ignored_raw)),
            free_response_chats=frozenset(_csv(free_raw)),
        )

    def validate_open_guard(self, *, network_exposed: bool = True) -> None:
        validate_channel_open_policy(
            self.platform or "channel",
            dm_policy=self.wecom_dm_policy or self.dm_policy,
            group_policy=self.wecom_group_policy or self.group_policy,
            allow_all_users=self.allow_all_users,
            network_exposed=network_exposed,
        )

    def is_ignored(self, chat_id: Any, thread_id: Any = None) -> bool:
        chat = str(chat_id or "").strip()
        thread = str(thread_id or "").strip()
        if chat and chat in self.ignored_channels:
            return True
        if thread and (thread in self.ignored_threads or f"{chat}:{thread}" in self.ignored_threads):
            return True
        return False

    def chat_allowed(self, chat_id: Any, thread_id: Any = None) -> bool:
        chat = str(chat_id or "").strip()
        if self.matrix_allowed_rooms and chat not in self.matrix_allowed_rooms:
            return False
        if self.allowed_topics:
            topic = str(thread_id or "").strip()
            if not topic or (topic not in self.allowed_topics
                             and f"{chat}:{topic}" not in self.allowed_topics):
                return False
        if not self.allowed_chat_ids:
            return True
        if thread_id is not None and f"{chat}:{thread_id}" in self.allowed_chat_ids:
            return True
        return chat in self.allowed_chat_ids

    def canonical_sender(self, sender: Any, *, channel: str = "") -> str:
        plat = (channel or self.platform or "").strip().lower()
        if plat == "whatsapp" or self.lid_map:
            return canonicalize_whatsapp_identity(sender, self.lid_map)
        return str(sender or "").strip()

    def _sender_in_set(self, sender: str, allowed: frozenset[str], *, channel: str = "") -> bool:
        if not sender or not allowed:
            return False
        plat = (channel or self.platform or "").strip().lower()
        if plat == "whatsapp" or self.lid_map:
            canon = canonicalize_whatsapp_identity(sender, self.lid_map)
            canon_set = {canonicalize_whatsapp_identity(item, self.lid_map) for item in allowed}
            return canon in canon_set
        return sender in allowed


@dataclass(frozen=True)
class GateDecision:
    action: str
    reason: str
    text: str


def _pre_side_effect_drop(
    policy: GroupPolicy,
    *,
    chat_id: Any,
    thread_id: Any,
    sender_id: str,
    is_bot: bool,
    text: str,
) -> GateDecision | None:
    """Checks that MUST fire before pairing, rate-limiting, or inbox persistence."""
    if policy.is_ignored(chat_id, thread_id):
        return GateDecision(DROP, "ignored_channel", text)
    if sender_id and sender_id in policy.own_sender_ids:
        return GateDecision(DROP, "own_message", text)
    if is_bot and not policy.allow_bots:
        return GateDecision(DROP, "bot_sender_blocked", text)
    return None


def _gate_private_chat(
    policy: GroupPolicy,
    *,
    sender_id: str,
    thread_id: Any,
    text: str,
    channel: str,
) -> GateDecision:
    dm_mode = (policy.wecom_dm_policy if (channel == "wecom" and policy.wecom_dm_policy)
               else policy.dm_policy).strip().lower()
    if policy.disable_dms or dm_mode == "disabled":
        return GateDecision(DROP, "dms_disabled", text)
    if policy.ignore_root_dm and not thread_id:
        return GateDecision(DROP, "root_dm_ignored", text)
    if not sender_id:
        # Backward-compatible path when gate_message is called without sender context.
        return GateDecision(ANSWER, "private_chat", text)
    if policy.allow_all_users or dm_mode == "open":
        return GateDecision(ANSWER, "private_chat", text)
    if policy._sender_in_set(sender_id, policy.allow_from, channel=channel):
        return GateDecision(ANSWER, "private_allowlisted", text)
    if dm_mode == "allowlist" or policy.unauthorized_dm_behavior == "ignore":
        return GateDecision(DROP, "unauthorized_dm_ignored", text)
    return GateDecision(PAIR, "dm_pairing_required", text)


def _feishu_effective(
    policy: GroupPolicy,
    chat_id: Any,
) -> tuple[bool, bool, frozenset[str], bool]:
    """Feishu 3-tier resolution: exact chat rule -> ``*`` wildcard rule -> policy defaults."""
    chat = str(chat_id or "").strip()
    rule = policy.feishu_group_rules.get(chat) or policy.feishu_group_rules.get("*")
    if rule is None:
        return True, policy.require_mention, policy.group_allow_from, policy.observe_mode
    req = policy.require_mention if rule.require_mention is None else rule.require_mention
    obs = policy.observe_mode if rule.observe_mode is None else rule.observe_mode
    allow = rule.allow_from or policy.group_allow_from
    return rule.enabled, req, allow, obs


def _group_sender_permitted(
    policy: GroupPolicy,
    *,
    sender_id: str,
    group_allow: frozenset[str],
    member_roles: Iterable[Any],
    channel: str,
) -> tuple[bool, bool]:
    """Return ``(allowed_member, guest_candidate)`` for group sender checks."""
    if policy.allowed_role_ids:
        roles = _fset(member_roles)
        if not (roles & policy.allowed_role_ids):
            return False, policy.guest_mode
    if not sender_id or policy.allow_all_users:
        return True, False
    effective_allow = group_allow or policy.allow_from
    if not effective_allow:
        return True, False
    if policy._sender_in_set(sender_id, effective_allow, channel=channel):
        return True, False
    return False, policy.guest_mode


def _addressed_other_bot(
    text: str,
    entities: Iterable[Any],
    *,
    our_addressed: bool,
    bot_username: str | None,
    other_bots: frozenset[str],
) -> bool:
    """True when another bot is explicitly @mentioned and our bot is NOT."""
    if our_addressed:
        return False
    ours = (bot_username or "").strip().lstrip("@").lower()
    known_others = {b.lstrip("@").lower() for b in other_bots if b.strip()}
    for match in _OTHER_BOT_RE.finditer(text or ""):
        handle = match.group(1).lower()
        if handle != ours:
            return True
    if known_others:
        for token in re.findall(r"(?<![\w@])@([A-Za-z0-9_.-]{2,64})\b", text or ""):
            if token.lower() in known_others and token.lower() != ours:
                return True
    for entity in entities or ():
        if isinstance(entity, Mapping) and entity.get("type") == "mention":
            handle = str(entity.get("username") or "").lstrip("@").lower()
            if handle and handle != ours and (handle in known_others or handle.endswith("bot")):
                return True
    return False


def _match_wake_patterns(text: str, patterns: tuple[str, ...]) -> tuple[bool, str]:
    for raw in patterns:
        if not raw:
            continue
        pat = re.compile(raw, re.IGNORECASE)
        m = pat.search(text)
        if m:
            cleaned = (text[: m.start()] + " " + text[m.end() :]).strip()
            cleaned = " ".join(cleaned.split())
            return True, cleaned or text
    return False, text


def _slack_triggered(
    policy: GroupPolicy,
    *,
    addressed: bool,
    stripped: str,
    text: str,
    in_bot_thread: bool,
    is_reaction: bool,
) -> tuple[bool, str]:
    triggers = policy.slack_triggers
    if "mention" in triggers and addressed:
        return True, stripped
    if "thread_reply" in triggers and in_bot_thread:
        return True, text
    if "reaction" in triggers and is_reaction:
        return True, text
    if "prefix" in triggers:
        for pref in policy.slack_prefixes:
            if pref and text.startswith(pref):
                rest = text[len(pref) :].strip()
                return True, rest or text
    if "keyword" in triggers:
        lowered = text.lower()
        if any(kw.lower() in lowered for kw in policy.slack_keywords if kw):
            return True, text
    return False, text


def _free_response_room(policy: GroupPolicy, chat_id: Any, thread_id: Any) -> bool:
    chat = str(chat_id or "").strip()
    thread = str(thread_id or "").strip()
    if chat and chat in policy.free_response_chats:
        return True
    if thread and (thread in policy.free_response_topics
                   or f"{chat}:{thread}" in policy.free_response_topics):
        return True
    return False


def gate_message(
    policy: GroupPolicy,
    *,
    chat_type: Any,
    chat_id: Any,
    text: str,
    thread_id: Any = None,
    entities: Iterable[Any] = (),
    reply_to_from_id: Any = None,
    bot_id: Any = None,
    bot_username: str | None = None,
    sender: Any = None,
    channel: str = "",
    is_bot: bool = False,
    member_roles: Iterable[Any] = (),
    in_bot_thread: bool = False,
    is_reaction: bool = False,
) -> GateDecision:
    """Decide whether an inbound message is answered, paired, observed, or dropped."""
    plat = (channel or policy.platform or "").strip().lower()
    sender_id = policy.canonical_sender(sender, channel=plat)
    early = _pre_side_effect_drop(
        policy, chat_id=chat_id, thread_id=thread_id,
        sender_id=sender_id, is_bot=is_bot, text=text,
    )
    if early is not None:
        return early

    kind = str(chat_type or "").strip().lower()
    if kind in PRIVATE_CHAT_TYPES:
        if plat == "slack" and "dm" not in policy.slack_triggers:
            return GateDecision(DROP, "slack_dm_trigger_disabled", text)
        return _gate_private_chat(
            policy, sender_id=sender_id, thread_id=thread_id, text=text, channel=plat,
        )
    if kind not in GROUP_CHAT_TYPES:
        return GateDecision(DROP, "unknown_chat_type", text)

    return _gate_group_chat(
        policy, plat=plat, chat_id=chat_id, thread_id=thread_id, text=text,
        entities=entities, reply_to_from_id=reply_to_from_id, bot_id=bot_id,
        bot_username=bot_username, sender_id=sender_id, member_roles=member_roles,
        in_bot_thread=in_bot_thread, is_reaction=is_reaction,
    )


def _gate_group_chat(
    policy: GroupPolicy,
    *,
    plat: str,
    chat_id: Any,
    thread_id: Any,
    text: str,
    entities: Iterable[Any],
    reply_to_from_id: Any,
    bot_id: Any,
    bot_username: str | None,
    sender_id: str,
    member_roles: Iterable[Any],
    in_bot_thread: bool,
    is_reaction: bool,
) -> GateDecision:
    grp_mode = (policy.wecom_group_policy if (plat == "wecom" and policy.wecom_group_policy)
                else policy.group_policy).strip().lower()
    if grp_mode == "disabled":
        return GateDecision(DROP, "groups_disabled", text)
    if not policy.chat_allowed(chat_id, thread_id):
        return GateDecision(DROP, "chat_not_allowed", text)

    enabled, req_mention, grp_allow, obs_mode = (
        _feishu_effective(policy, chat_id)
        if plat in {"feishu", "lark"} and policy.feishu_group_rules
        else (True, policy.require_mention, policy.group_allow_from, policy.observe_mode)
    )
    if not enabled:
        return GateDecision(DROP, "group_rule_disabled", text)

    member_ok, guest_only = _group_sender_permitted(
        policy, sender_id=sender_id, group_allow=grp_allow,
        member_roles=member_roles, channel=plat,
    )
    if not member_ok and not guest_only:
        return GateDecision(DROP, "sender_not_allowed_in_group", text)

    addressed, stripped = _addressed(
        text, entities, reply_to_from_id=reply_to_from_id,
        bot_id=bot_id, bot_username=bot_username,
    )
    if not addressed and policy.mention_patterns:
        addressed, stripped = _match_wake_patterns(text, policy.mention_patterns)
    if policy.exclusive_bot_mentions and _addressed_other_bot(
        text, entities, our_addressed=addressed,
        bot_username=bot_username, other_bots=policy.other_bot_usernames,
    ):
        return GateDecision(DROP, "addressed_other_bot", text)

    return _finalize_group_decision(
        policy, plat=plat, addressed=addressed, stripped=stripped, text=text,
        chat_id=chat_id, thread_id=thread_id, req_mention=req_mention,
        obs_mode=obs_mode, guest_only=guest_only, sender_id=sender_id,
        in_bot_thread=in_bot_thread, is_reaction=is_reaction,
    )


def _finalize_group_decision(
    policy: GroupPolicy,
    *,
    plat: str,
    addressed: bool,
    stripped: str,
    text: str,
    chat_id: Any,
    thread_id: Any,
    req_mention: bool,
    obs_mode: bool,
    guest_only: bool,
    sender_id: str,
    in_bot_thread: bool,
    is_reaction: bool,
) -> GateDecision:
    if plat == "slack":
        triggered, slack_text = _slack_triggered(
            policy, addressed=addressed, stripped=stripped, text=text,
            in_bot_thread=in_bot_thread, is_reaction=is_reaction,
        )
        if triggered:
            return GateDecision(ANSWER, "guest_addressed" if guest_only else "addressed", slack_text)
    elif addressed:
        return GateDecision(ANSWER, "guest_addressed" if guest_only else "addressed", stripped)

    if guest_only:
        return GateDecision(DROP, "guest_requires_mention", text)
    if plat != "photon" and (_free_response_room(policy, chat_id, thread_id) or not req_mention):
        return GateDecision(ANSWER, "mention_not_required", text)
    if obs_mode:
        observed = f"[{sender_id}]: {text}" if (policy.attribute_observed_sender and sender_id) else text
        return GateDecision(OBSERVE, "observe", observed)
    return GateDecision(DROP, "not_addressed", text)


def _addressed(
    text: str,
    entities: Iterable[Any],
    *,
    reply_to_from_id: Any,
    bot_id: Any,
    bot_username: str | None,
) -> tuple[bool, str]:
    addressed = False
    if bot_id is not None and reply_to_from_id is not None and str(reply_to_from_id) == str(bot_id):
        addressed = True
    stripped = text
    username = (bot_username or "").strip().lstrip("@")
    if username:
        command = re.compile(rf"^(/\w+)@{re.escape(username)}\b", re.IGNORECASE)
        if command.match(stripped):
            addressed = True
            stripped = command.sub(r"\1", stripped)
        mention = re.compile(rf"(?<![\w@])@{re.escape(username)}\b", re.IGNORECASE)
        if mention.search(stripped):
            addressed = True
            stripped = mention.sub("", stripped)
    if bot_id is not None:
        slack_tag = re.compile(rf"<@{re.escape(str(bot_id))}(?:\|[^>]+)?>")
        if slack_tag.search(stripped):
            addressed = True
            stripped = slack_tag.sub("", stripped)
        for entity in entities or ():
            if not isinstance(entity, Mapping) or entity.get("type") != "text_mention":
                continue
            user = entity.get("user")
            if isinstance(user, Mapping) and str(user.get("id")) == str(bot_id):
                addressed = True
    cleaned = " ".join(stripped.split())
    return addressed, cleaned or text
