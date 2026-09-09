"""The front door refuses by default (Hermes absorption 5b).

Before this wave the inbound pairing gate was opt-in: a fresh install with a bot
token answered whoever found the bot, and Discord never even told the gateway who
was writing, so pairing could not have held a Discord stranger had it been on.
What changes, each pinned here:

* ``pairing_enabled()`` is on unless ``JARVIS_CHANNEL_PAIRING=0``; a typo in that
  flag (or in ``JARVIS_CHANNEL_OPEN``) refuses the boot instead of being guessed.
* ``boot_guards.assert_guarded_channels`` refuses to start a configured inbound
  channel that nothing guards — pairing off, no allowlist — unless the operator
  wrote down ``JARVIS_CHANNEL_OPEN=1``, which is honoured with a ``[SECURITY]``
  console line. The refusal names the channel and the remedies, never the token.
  The guard reads everything — tokens, allowlist and both flags — from ONE mapping,
  so a caller holding a loaded ``.env`` gets that environment's verdict.
  ``assert_front_door`` is the same check for a caller that runs after ``.env`` is
  loaded, because the lifespan's early pass runs before it.
* The owner's own allowlisted ids compose with pairing instead of being held by it,
  so an install that upgrades with ``TELEGRAM_ALLOWED_USER_IDS`` set keeps its bot.
* Wrong pairing-code guesses are throttled store-wide, because sender ids on a
  webhook or an HTTP request are attacker-chosen and a per-sender bucket never binds.
* The gateway counts holds per channel (a tally, no identities) so /status can say
  "someone is knocking".
* Discord and Slack thread the sender's stable id so pairing can hold them.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import boot_guards  # noqa: E402
from agents.core.channels import discord as discord_mod  # noqa: E402
from agents.core.channels import pairing as pairing_mod  # noqa: E402
from agents.core.channels.discord import DiscordChannel  # noqa: E402
from agents.core.channels.gateway import Gateway  # noqa: E402
from agents.core.channels.pairing import SenderPairing  # noqa: E402
from agents.core.channels.slack import SlackChannel  # noqa: E402

TOKEN = "123456:secret-bot-token-value"
PAIRING_OFF = {"JARVIS_CHANNEL_PAIRING": "0"}

_FRONT_DOOR_VARS = (
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USER_IDS", "DISCORD_BOT_TOKEN",
    "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "JARVIS_WEBHOOK_CHANNELS", "IMAP_HOST", "SMTP_HOST",
    "JARVIS_CHANNEL_PAIRING", "JARVIS_CHANNEL_OPEN",
    "JARVIS_HOST", "JARVIS_HARDENED", "NERVA_PUBLIC_PROFILE", "JARVIS_TASK_MEDIATION",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in _FRONT_DOOR_VARS:
        monkeypatch.delenv(var, raising=False)


# ── pairing_enabled: default-on ──────────────────────────────────────────────

def test_pairing_is_on_when_the_flag_is_unset(tmp_path):
    assert pairing_mod.pairing_enabled() is True
    store = SenderPairing(path=str(tmp_path / "p.json"))
    assert store.is_allowed("telegram", "stranger") is False
    assert store.summary()["enabled"] is True


def test_pairing_flag_zero_turns_it_off(monkeypatch, tmp_path):
    # the knob is a named constant now, so the boot guard and the gate cannot drift
    assert pairing_mod.PAIRING_ENV == "JARVIS_CHANNEL_PAIRING"
    assert pairing_mod.CHANNEL_OPEN_ENV == "JARVIS_CHANNEL_OPEN"
    monkeypatch.setenv(pairing_mod.PAIRING_ENV, "0")
    assert pairing_mod.pairing_enabled() is False
    assert SenderPairing(path=str(tmp_path / "p.json")).is_allowed("telegram", "x") is True


def test_channel_open_is_off_unless_written_down(monkeypatch):
    assert pairing_mod.channel_open_acknowledged() is False
    monkeypatch.setenv("JARVIS_CHANNEL_OPEN", "1")
    assert pairing_mod.channel_open_acknowledged() is True


@pytest.mark.parametrize("flag", ["JARVIS_CHANNEL_PAIRING", "JARVIS_CHANNEL_OPEN"])
def test_pairing_flag_typo_refuses_boot(monkeypatch, flag):
    monkeypatch.setenv(flag, "fasle")
    with pytest.raises(SystemExit) as excinfo:
        boot_guards.assert_parseable_posture_flags()
    message = str(excinfo.value)
    assert flag in message
    assert "fasle" not in message


@pytest.mark.parametrize("flag", ["JARVIS_CHANNEL_PAIRING", "JARVIS_CHANNEL_OPEN"])
def test_parse_check_reads_the_mapping_it_is_given(flag):
    """A typo in a captured environment refuses even when the process env is clean,
    and a clean mapping passes even when the process env would not — one source."""
    with pytest.raises(SystemExit) as excinfo:
        boot_guards.assert_parseable_posture_flags({flag: "fasle"})
    assert flag in str(excinfo.value) and "fasle" not in str(excinfo.value)
    boot_guards.assert_parseable_posture_flags({flag: "0"})


# ── assert_guarded_channels ──────────────────────────────────────────────────

def test_no_token_no_guard(capsys):
    boot_guards.assert_guarded_channels({})  # nothing configured → nothing to guard
    boot_guards.assert_guarded_channels({**PAIRING_OFF})
    assert "[SECURITY]" not in capsys.readouterr().out


def test_slack_socket_ingress_requires_pairing_or_explicit_open_ack(capsys):
    env = {"SLACK_BOT_TOKEN": TOKEN, "SLACK_APP_TOKEN": "app-secret"}
    boot_guards.assert_front_door(env)
    assert "[SECURITY]" not in capsys.readouterr().out
    with pytest.raises(SystemExit) as refused:
        boot_guards.assert_front_door({**env, **PAIRING_OFF})
    assert "slack bot would answer any sender" in str(refused.value)
    assert TOKEN not in str(refused.value) and "app-secret" not in str(refused.value)
    boot_guards.assert_front_door({**env, **PAIRING_OFF, "JARVIS_CHANNEL_OPEN": "1"})
    assert "[SECURITY] slack bot answers any sender" in capsys.readouterr().out


@pytest.mark.parametrize("tokens", [
    {"SLACK_BOT_TOKEN": TOKEN},
    {"SLACK_APP_TOKEN": "app-secret"},
    {"SLACK_BOT_TOKEN": TOKEN, "SLACK_APP_TOKEN": "   "},
])
def test_slack_without_both_tokens_does_not_add_a_live_front_door(tokens, capsys):
    boot_guards.assert_front_door({**tokens, **PAIRING_OFF})
    assert "[SECURITY]" not in capsys.readouterr().out


def test_telegram_token_without_allowlist_and_pairing_off_refuses_boot():
    with pytest.raises(SystemExit) as excinfo:
        boot_guards.assert_guarded_channels({"TELEGRAM_BOT_TOKEN": TOKEN, **PAIRING_OFF})
    assert "telegram bot would answer any sender" in str(excinfo.value)


def test_telegram_token_with_pairing_on_boots(capsys):
    boot_guards.assert_guarded_channels({"TELEGRAM_BOT_TOKEN": TOKEN})  # default-on pairing
    boot_guards.assert_guarded_channels({"TELEGRAM_BOT_TOKEN": TOKEN, "JARVIS_CHANNEL_PAIRING": "1"})
    assert "[SECURITY]" not in capsys.readouterr().out
    # the same configuration with the gate switched off is what refuses
    with pytest.raises(SystemExit):
        boot_guards.assert_guarded_channels({"TELEGRAM_BOT_TOKEN": TOKEN, **PAIRING_OFF})


def test_telegram_token_with_allowlist_and_pairing_off_boots(capsys):
    env = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_ALLOWED_USER_IDS": " 42, oops ,7", **PAIRING_OFF}
    boot_guards.assert_guarded_channels(env)
    assert "[SECURITY]" not in capsys.readouterr().out
    # it is the allowlist that guards: take it away and the same call refuses
    with pytest.raises(SystemExit):
        boot_guards.assert_guarded_channels({k: v for k, v in env.items() if "ALLOWED" not in k})


def test_an_allowlist_with_no_usable_id_is_not_a_guard():
    with pytest.raises(SystemExit):
        boot_guards.assert_guarded_channels(
            {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_ALLOWED_USER_IDS": "oops, ,", **PAIRING_OFF}
        )


def test_discord_token_with_pairing_off_refuses_boot_unless_channel_open(capsys):
    with pytest.raises(SystemExit) as excinfo:
        boot_guards.assert_guarded_channels({"DISCORD_BOT_TOKEN": TOKEN, **PAIRING_OFF})
    message = str(excinfo.value)
    assert "the discord bot would answer any sender" in message
    # no allowlist knob exists for discord, so none is offered as a remedy
    assert "ALLOWED_USER_IDS" not in message
    assert "JARVIS_CHANNEL_OPEN=1" in message
    boot_guards.assert_guarded_channels(
        {"DISCORD_BOT_TOKEN": TOKEN, "JARVIS_CHANNEL_OPEN": "1", **PAIRING_OFF}
    )
    assert "[SECURITY] discord bot answers any sender" in capsys.readouterr().out


@pytest.mark.parametrize("config, label", [
    ({"JARVIS_WEBHOOK_CHANNELS": '{"whatsapp": {"token": "t", "phone_id": "1"}}'},
     "webhook channel"),
    ({"IMAP_HOST": "imap.example.test", "SMTP_HOST": "smtp.example.test"}, "email channel"),
])
def test_webhook_and_email_inboxes_are_front_doors_too(config, label, capsys):
    """Every wired inbound path threads a sender into the gateway, so with pairing
    off each is a door anyone can knock on — the guard covers them all."""
    with pytest.raises(SystemExit) as excinfo:
        boot_guards.assert_guarded_channels({**config, **PAIRING_OFF})
    message = str(excinfo.value)
    assert f"the {label} would answer any sender" in message
    assert "ALLOWED_USER_IDS" not in message and "JARVIS_CHANNEL_OPEN=1" in message
    for value in config.values():
        assert value not in message
    boot_guards.assert_guarded_channels({**config})  # pairing on → guarded
    boot_guards.assert_guarded_channels({**config, "JARVIS_CHANNEL_OPEN": "1", **PAIRING_OFF})
    assert f"[SECURITY] {label} answers any sender" in capsys.readouterr().out


def test_a_webhook_map_that_wires_nothing_is_not_a_front_door():
    # mirrors env_json_object: empty / invalid / non-object wire no adapter
    for raw in ("{}", "   ", "not json", "[1, 2]", '"str"'):
        boot_guards.assert_guarded_channels({"JARVIS_WEBHOOK_CHANNELS": raw, **PAIRING_OFF})
    # email needs both halves before the app wires the adapter
    boot_guards.assert_guarded_channels({"IMAP_HOST": "imap.example.test", **PAIRING_OFF})


def test_a_slack_token_alone_is_not_a_front_door(capsys):
    """Automatic Slack ingress requires the additional app-level Socket Mode token."""
    boot_guards.assert_guarded_channels({"SLACK_BOT_TOKEN": "xoxb-outbound-only", **PAIRING_OFF})
    assert "[SECURITY]" not in capsys.readouterr().out


def test_channel_open_ack_prints_the_security_line_and_boots(capsys):
    boot_guards.assert_guarded_channels(
        {"TELEGRAM_BOT_TOKEN": TOKEN, "JARVIS_CHANNEL_OPEN": "1", **PAIRING_OFF}
    )
    out = capsys.readouterr().out
    assert "[SECURITY] telegram bot answers any sender (JARVIS_CHANNEL_OPEN acknowledged)." in out
    assert TOKEN not in out


def test_refusal_message_names_remedies_never_the_token():
    with pytest.raises(SystemExit) as excinfo:
        boot_guards.assert_guarded_channels({"TELEGRAM_BOT_TOKEN": TOKEN, **PAIRING_OFF})
    message = str(excinfo.value)
    assert TOKEN not in message and "secret-bot-token" not in message
    assert "TELEGRAM_ALLOWED_USER_IDS" in message
    assert "JARVIS_CHANNEL_PAIRING" in message
    assert "JARVIS_CHANNEL_OPEN=1" in message


def test_a_blank_token_is_not_a_configured_bot():
    boot_guards.assert_guarded_channels(
        {"TELEGRAM_BOT_TOKEN": "   ", "DISCORD_BOT_TOKEN": "", **PAIRING_OFF}
    )


def test_the_guard_reads_the_flags_from_the_mapping_it_is_given(monkeypatch):
    """Tokens from the mapping and flags from the process env would give a captured
    environment (a loaded .env, a container config) the wrong verdict."""
    # process env says off; the mapping says nothing → the mapping's default (on) rules
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "0")
    boot_guards.assert_guarded_channels({"TELEGRAM_BOT_TOKEN": TOKEN})
    # process env clean; the mapping says off → refused on the mapping's word
    monkeypatch.delenv("JARVIS_CHANNEL_PAIRING")
    with pytest.raises(SystemExit):
        boot_guards.assert_guarded_channels({"TELEGRAM_BOT_TOKEN": TOKEN, **PAIRING_OFF})
    # and the acknowledgement is the mapping's too, not the process's
    monkeypatch.setenv("JARVIS_CHANNEL_OPEN", "1")
    with pytest.raises(SystemExit):
        boot_guards.assert_guarded_channels({"TELEGRAM_BOT_TOKEN": TOKEN, **PAIRING_OFF})


def test_the_default_mapping_is_the_process_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "0")
    with pytest.raises(SystemExit):
        boot_guards.assert_guarded_channels()
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "42")
    boot_guards.assert_guarded_channels()


def test_enforce_boot_posture_runs_the_channel_guard(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "0")
    with pytest.raises(SystemExit) as excinfo:
        boot_guards.enforce_boot_posture()
    assert "discord bot would answer any sender" in str(excinfo.value)
    assert "assert_guarded_channels" in inspect.getsource(boot_guards.enforce_boot_posture)


def test_the_channel_flags_are_parse_critical():
    assert "JARVIS_CHANNEL_PAIRING" in boot_guards._PARSE_CRITICAL_BOOL_FLAGS
    assert "JARVIS_CHANNEL_OPEN" in boot_guards._PARSE_CRITICAL_BOOL_FLAGS


# ── assert_front_door: the pass that runs after .env is loaded ───────────────

def test_front_door_guard_sees_a_dotenv_only_configuration():
    """The lifespan's early pass runs before the .env files load, so a bot token that
    lives only there boots open; the late pass over the loaded mapping refuses it."""
    dotenv = {"TELEGRAM_BOT_TOKEN": TOKEN, **PAIRING_OFF}
    boot_guards.enforce_boot_posture()  # the process env is empty: nothing to see
    with pytest.raises(SystemExit) as excinfo:
        boot_guards.assert_front_door(dotenv)
    assert "telegram bot would answer any sender" in str(excinfo.value)
    assert TOKEN not in str(excinfo.value)


def test_front_door_guard_refuses_a_typo_in_the_loaded_flags():
    with pytest.raises(SystemExit) as excinfo:
        boot_guards.assert_front_door({"TELEGRAM_BOT_TOKEN": TOKEN, "JARVIS_CHANNEL_OPEN": "fasle"})
    message = str(excinfo.value)
    assert "JARVIS_CHANNEL_OPEN" in message and "fasle" not in message and TOKEN not in message


def test_front_door_guard_boots_a_guarded_or_empty_environment(capsys):
    boot_guards.assert_front_door({})
    boot_guards.assert_front_door({"TELEGRAM_BOT_TOKEN": TOKEN})
    boot_guards.assert_front_door(
        {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_ALLOWED_USER_IDS": "42", **PAIRING_OFF}
    )
    assert "[SECURITY]" not in capsys.readouterr().out


# ── the allowlist composes with pairing ──────────────────────────────────────

def test_allowlisted_owner_passes_the_gate_without_a_pairing_record(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "42, oops , 7")
    store = SenderPairing(path=str(tmp_path / "p.json"))
    assert pairing_mod.sender_allowlisted("telegram", "42") is True
    assert pairing_mod.sender_allowlisted("telegram", "43") is False
    assert store.is_allowed("telegram", "42") is True
    assert store.gate_inbound("telegram", "7")["allowed"] is True
    assert store.status("telegram", "42") == pairing_mod.UNKNOWN  # nothing was written
    # a stranger on the same channel is still held
    assert store.is_allowed("telegram", "43") is False
    assert store.gate_inbound("telegram", "43")["status"] == pairing_mod.PENDING


def test_the_allowlist_is_per_channel(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "42")
    store = SenderPairing(path=str(tmp_path / "p.json"))
    assert pairing_mod.sender_allowlisted("discord", "42") is False
    assert store.is_allowed("discord", "42") is False
    assert pairing_mod.CHANNEL_ALLOWLIST_ENVS == {"telegram": "TELEGRAM_ALLOWED_USER_IDS"}


def test_an_empty_allowlist_names_nobody(tmp_path):
    store = SenderPairing(path=str(tmp_path / "p.json"))
    assert pairing_mod.allowlisted_sender_ids("telegram") == frozenset()
    assert pairing_mod.allowlisted_sender_ids("telegram", {"TELEGRAM_ALLOWED_USER_IDS": " , x"}) == frozenset()
    assert store.is_allowed("telegram", "") is False


@pytest.mark.asyncio
async def test_gateway_routes_the_allowlisted_owner_and_holds_the_stranger(monkeypatch, tmp_path):
    """The upgrade path: an install with TELEGRAM_ALLOWED_USER_IDS set and the pairing
    flag never written must not lock the owner out of their own bot."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "42")
    store = SenderPairing(path=str(tmp_path / "p.json"))
    reached = []

    async def handler(text, channel="web", **kw):
        reached.append((text, kw.get("sender")))
        return "routed"

    gw = Gateway(handler=handler, pairing=store)
    assert await gw.route("it is me", channel="telegram", sender="42") == "routed"
    held = await gw.route("let me in", channel="telegram", sender="43")
    assert held and "approval" in held.lower()
    assert reached == [("it is me", "42")]
    assert gw.get_channel_info("telegram")["held_senders"] == 1


def test_the_guard_and_the_gate_share_one_allowlist_parse():
    assert pairing_mod.parse_sender_allowlist(" 42, oops ,7,,") == ("42", "7")
    assert boot_guards._count_allowlisted_ids(" 42, oops ,7,,") == 2
    assert boot_guards._count_allowlisted_ids(None) == 0


# ── code guesses are throttled store-wide ────────────────────────────────────

def test_rotating_sender_ids_cannot_brute_force_the_pairing_code(tmp_path):
    store = SenderPairing(path=str(tmp_path / "p.json"))
    store.set_code("hunter2")
    budget = pairing_mod._MAX_CODE_GUESSES_PER_WINDOW
    assert 0 < budget < pairing_mod._MAX_PENDING
    outcomes = [store.request("telegram", f"guess-{i}", code="nope")["status"] for i in range(50)]
    assert outcomes.count("rate_limited") == 50 - budget
    assert outcomes[:budget] == [pairing_mod.PENDING] * budget
    # the budget is spent: even the right code is refused for this window, and the
    # sender is held like anyone else rather than admitted
    late = store.request("telegram", "late-comer", code="hunter2")
    assert late == {"status": "rate_limited", "allowed": False}
    assert store.is_allowed("telegram", "late-comer") is False
    assert store.gate_inbound("telegram", "late-comer", code="hunter2")["message"]


def test_the_code_guess_budget_only_charges_code_guesses(tmp_path):
    store = SenderPairing(path=str(tmp_path / "p.json"))
    store.set_code("hunter2")
    for i in range(pairing_mod._MAX_CODE_GUESSES_PER_WINDOW):
        store.request("telegram", f"guess-{i}", code="nope")
    # plain first contact without a code is still held normally, never rate-limited
    assert store.request("telegram", "plain")["status"] == pairing_mod.PENDING
    # and with no code set there is nothing to guess, so nothing is charged
    store.set_code(None)
    assert store.request("telegram", "another", code="hunter2")["status"] == pairing_mod.PENDING
    assert store.request("telegram", "yet-another", code="hunter2")["status"] == pairing_mod.PENDING


def test_a_correct_code_within_budget_still_pairs(tmp_path):
    store = SenderPairing(path=str(tmp_path / "p.json"))
    store.set_code("hunter2")
    assert store.request("telegram", "phone", code="hunter2")["paired_by"] == "code"


# ── gateway: a tally of held senders, no identities ─────────────────────────

@pytest.mark.asyncio
async def test_gateway_counts_held_senders(tmp_path):
    store = SenderPairing(path=str(tmp_path / "pairing.json"))
    reached = []

    async def handler(text, channel="web", **kw):
        reached.append(text)
        return "routed"

    gw = Gateway(handler=handler, pairing=store)
    gw.register_channel("telegram")
    for text in ("hello?", "anyone there?"):
        out = await gw.route(text, channel="telegram", sender="777")
        assert out and "approval" in out.lower()

    info = gw.get_channel_info("telegram")
    assert info["held_senders"] == 2
    assert info["message_count"] == 0
    assert reached == []
    assert gw.get_summary()["total_held"] == 2
    assert gw.get_summary()["total_messages"] == 0
    # the tally is a number: neither the gateway nor the store keeps who knocked. The
    # two timestamps are left out of the check — a wall-clock float can spell any digits.
    identity_free = {k: v for k, v in info.items() if k not in {"registered_at", "last_activity"}}
    assert "777" not in str(identity_free)
    assert "hello?" not in (tmp_path / "pairing.json").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_status_channel_rows_carry_the_held_count(tmp_path, monkeypatch):
    """The tally is only useful if the owner can see it: /status channel rows carry
    held_senders from the live gateway, 0 when no gateway is running."""
    from agents.core.routers import status as status_router

    store = SenderPairing(path=str(tmp_path / "pairing.json"))

    async def handler(text, channel="web", **kw):
        return "routed"

    gw = Gateway(handler=handler, pairing=store)
    gw.register_channel("telegram")
    await gw.route("hello?", channel="telegram", sender="777")
    orch = SimpleNamespace(channels={"telegram": SimpleNamespace(_running=True)})

    monkeypatch.setattr(status_router, "get_gateway", lambda: gw)
    rows = status_router._channel_rows(orch)
    assert rows == [{"id": "telegram", "running": True, "ready": True, "held_senders": 1}]
    assert "777" not in str(rows)

    monkeypatch.setattr(status_router, "get_gateway", lambda: None)
    assert status_router._channel_rows(orch)[0]["held_senders"] == 0


def test_email_sender_is_the_bare_address_never_the_display_name():
    """Pairing on the email door keys on the parsed address: a display name, a comment
    or a change of case must not mint a new stranger, and a header with no address is
    no sender at all (held, never routed as the owner)."""
    from agents.core.channels.email import _sender_address

    assert _sender_address('"Andrei" <A@Example.com>') == "a@example.com"
    assert _sender_address("a@example.com") == "a@example.com"
    assert _sender_address("Owner (home) <Owner@Example.COM>") == "owner@example.com"
    assert _sender_address("not an address") == ""
    assert _sender_address("") == "" and _sender_address(None) == ""


@pytest.mark.asyncio
async def test_a_fresh_channel_starts_with_no_held_senders():
    gw = Gateway(handler=None)
    gw.register_channel("discord")
    assert gw.get_channel_info("discord")["held_senders"] == 0
    assert gw.get_summary()["total_held"] == 0


# ── discord / slack thread the sender ───────────────────────────────────────

class _Sink:
    def __init__(self):
        self.id = 123
        self.sent: list[str] = []

    async def send(self, text):
        self.sent.append(text)


def _discord_message(author_id: int, content: str, author=None):
    return SimpleNamespace(
        author=author or SimpleNamespace(id=author_id, name="Mallory"),
        content=content,
        channel=_Sink(),
    )


class _FakeClient:
    """Enough of a Discord client to register the event closures and be started."""

    def __init__(self, *, intents):
        self.intents = intents
        self.events: dict[str, object] = {}
        self.user = SimpleNamespace(id=1, name="the-bot")
        self.started_with = None

    def event(self, fn):
        self.events[fn.__name__] = fn
        return fn

    async def start(self, token):
        self.started_with = token

    async def close(self):
        pass

    def is_ready(self):
        return False


class _FakeIntents:
    @staticmethod
    def default():
        return SimpleNamespace(message_content=False)


@pytest.fixture
def fake_discord(monkeypatch):
    monkeypatch.setattr(discord_mod, "DISCORD_AVAILABLE", True)
    monkeypatch.setattr(
        discord_mod, "discord", SimpleNamespace(Client=_FakeClient, Intents=_FakeIntents),
        raising=False,
    )


@pytest.mark.asyncio
async def test_discord_threads_its_sender_so_pairing_holds_a_stranger(tmp_path):
    store = SenderPairing(path=str(tmp_path / "pairing.json"))
    reached = []

    async def inner(text, channel="web", **kw):
        reached.append((text, kw.get("sender")))
        return "routed"

    gw = Gateway(handler=inner, pairing=store)
    ch = DiscordChannel(token="tok", handler=gw.route)
    msg = _discord_message(424242, "let me in")

    await ch._handle_message(msg)
    assert reached == []                                  # held at the gate
    assert msg.channel.sent == []  # the adapter cannot publish the gateway's return value
    assert store.status("discord", "424242") == pairing_mod.PENDING

    store.approve("discord", "424242")
    msg2 = _discord_message(424242, "again")
    await ch._handle_message(msg2)
    assert reached == [("again", "424242")]              # sender is str(author.id)
    assert msg2.channel.sent == []  # only the governed reply executor may deliver


@pytest.mark.asyncio
async def test_discord_handler_receives_sender_as_the_author_id_string():
    seen = {}

    async def handler(text, channel="web", **kw):
        seen.update(kw, text=text, channel=channel)
        return None

    ch = DiscordChannel(token="tok", handler=handler)
    await ch._handle_message(_discord_message(99, "hi"))
    assert seen == {"text": "hi", "channel": "discord", "sender": "99", "channel_id": "123"}


@pytest.mark.asyncio
async def test_discord_on_message_delegates_to_the_method(fake_discord):
    """Drive the real ``on_message`` closure the client would call, not its source
    text: the handler must see the sender through it, and the bot's own messages
    must be skipped before any handler runs."""
    seen = []

    async def handler(text, channel="web", **kw):
        seen.append((text, channel, kw))
        return "pong"

    ch = DiscordChannel(token="tok", handler=handler)
    await ch.start()
    try:
        client = ch._client
        assert isinstance(client, _FakeClient) and client.intents.message_content is True
        await asyncio.sleep(0)  # let the start task run
        assert client.started_with == "tok"
        on_message = client.events["on_message"]

        stranger = _discord_message(7, "yo")
        await on_message(stranger)
        assert seen == [("yo", "discord", {"sender": "7", "channel_id": "123"})]
        assert stranger.channel.sent == []

        own = _discord_message(1, "echo?", author=client.user)
        await on_message(own)
        assert seen == [("yo", "discord", {"sender": "7", "channel_id": "123"})] and own.channel.sent == []
    finally:
        await ch.stop()


@pytest.mark.asyncio
async def test_slack_threads_its_user_as_sender_and_drops_the_anonymous(tmp_path):
    store = SenderPairing(path=str(tmp_path / "pairing.json"))
    reached = []

    async def inner(text, channel="web", **kw):
        reached.append((text, kw.get("sender")))
        return "routed"

    gw = Gateway(handler=inner, pairing=store)
    ch = SlackChannel(token="tok", handler=gw.route)

    held = await ch.receive_event("let me in", "C123", user="U777")
    assert reached == [] and held and "approval" in held.lower()
    store.approve("slack", "U777")
    assert await ch.receive_event("again", "C123", user="U777") == "routed"
    assert reached == [("again", "U777")]

    # no user id → nothing for pairing to hold → dropped, never routed
    assert await ch.receive_event("anon", "C123") is None
    assert await ch.receive_event("anon", "C123", user="  ") is None
    assert reached == [("again", "U777")]


@pytest.mark.asyncio
async def test_slack_member_id_wins_over_a_forwarded_sender_kwarg():
    """An adapter forwarding raw event kwargs must not make the handler raise, and
    the payload's member id — the identity pairing holds — is the one that counts."""
    seen = []

    async def handler(text, channel="web", **kw):
        seen.append(kw.get("sender"))
        return "ok"

    ch = SlackChannel(token="tok", handler=Gateway(handler=handler).route)
    assert await ch.receive_event("hi", "C1", user="U1", sender="U2") == "ok"
    assert seen == ["U1"]
