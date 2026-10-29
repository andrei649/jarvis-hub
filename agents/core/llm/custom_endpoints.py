"""Inert, revisioned H367 endpoint catalog and single-choice metadata.

These SQLite rows are never owner approval. The custom service issues a separate
configuration-bound consent proof after live Kernel and audit decisions; runtime
rejects a raw row or a caller-supplied proof string.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from agents.core import settings_db

from .providers import DATA_POLICIES, selection_gates

_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_MODEL = re.compile(r"[\x21-\x7e]{1,256}\Z")
_PROOF = re.compile(r"[0-9a-f]{64}\Z")


class CustomEndpointInvalid(RuntimeError):
    pass


class CustomEndpointConflict(CustomEndpointInvalid):
    pass


@dataclass(frozen=True, slots=True)
class CustomEndpoint:
    key: str
    name: str
    base_url: str
    model: str
    auth_type: str
    data_policy: str
    revision: int
    config_revision: int
    admission_proof: str = ''

    @property
    def identity(self) -> str:
        return f"custom:{self.key}"

    @property
    def destination_class(self) -> str:
        return classify_url(self.base_url)


@dataclass(frozen=True, slots=True)
class CustomChoice:
    epoch: int
    revision: int
    active_key: str | None
    config_revision: int | None
    credential_generation: int | None
    consent_proof: str | None
    unknown_price_ack: bool
    data_policy_ack: bool


def custom_provider_slug(endpoint: CustomEndpoint) -> str:
    return endpoint.identity


def custom_provider_aliases(endpoint: CustomEndpoint) -> tuple[str, ...]:
    """Current and prior unambiguous names; bare `custom` needs proof recovery."""
    if type(endpoint) is not CustomEndpoint:
        raise CustomEndpointInvalid('endpoint alias unavailable')
    def read(conn):
        current = conn.execute('SELECT key FROM custom_endpoints WHERE key=?',
                               (endpoint.key,)).fetchone()
        if current is None:
            raise CustomEndpointInvalid('endpoint alias unavailable')
        rows = conn.execute('SELECT alias FROM custom_endpoint_aliases WHERE endpoint_key=? '
                            'ORDER BY alias_key', (endpoint.key,)).fetchall()
        return (endpoint.identity, endpoint.key, *(row[0] for row in rows))
    return _with_read(read)


def resolve_custom_provider_alias(alias: str) -> CustomEndpoint | None:
    """Resolve only unique named aliases; the legacy bare spelling is separate."""
    if type(alias) is not str or not 1 <= len(alias) <= 107:
        raise CustomEndpointInvalid('invalid endpoint alias')
    if alias == 'custom':
        return None
    if alias.startswith('custom:'):
        return read_endpoint(alias[7:])
    def read(conn):
        row = conn.execute('SELECT endpoint_key FROM custom_endpoint_aliases WHERE alias_key=?',
                           (alias.casefold(),)).fetchone()
        if row is None:
            return None
        endpoint = conn.execute('SELECT * FROM custom_endpoints WHERE key=?',
                                (row[0],)).fetchone()
        return _endpoint(endpoint) if endpoint is not None else None
    return _with_read(read)


def classify_url(base_url: str) -> str:
    if (type(base_url) is not str or not 1 <= len(base_url) <= 2048
            or any(ord(c) < 33 or ord(c) > 126 for c in base_url)):
        raise CustomEndpointInvalid("invalid endpoint URL")
    try:
        parts = urlsplit(base_url)
        host, port = parts.hostname, parts.port
    except (TypeError, ValueError) as exc:
        raise CustomEndpointInvalid("invalid endpoint URL") from exc
    if (parts.scheme not in {"http", "https"} or not host or len(host) > 253
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or port == 0
            or not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/){0,7}v1/?", parts.path)
            or host.endswith(".")
            or not re.fullmatch(r"[A-Za-z0-9.:-]+", host)):
        raise CustomEndpointInvalid("invalid endpoint URL")
    if host == "localhost":
        kind = "loopback"
    else:
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            kind = "lan" if (host.endswith((".local", ".lan")) or "." not in host) else "public"
        else:
            if ip.is_loopback:
                kind = "loopback"
            elif (isinstance(ip, ipaddress.IPv4Address) and ip.is_private
                  and not ip.is_link_local and not ip.is_reserved):
                kind = "lan"
            elif ip.is_global:
                kind = "public"
            else:
                raise CustomEndpointInvalid("unsafe endpoint address")
    if kind == "public" and parts.scheme != "https":
        raise CustomEndpointInvalid("public endpoint requires HTTPS")
    return kind


def _validate(key, name, base_url, model, auth_type, data_policy) -> str:
    if (type(key) is not str or not _KEY.fullmatch(key) or key in {".", ".."}
            or type(name) is not str or not 1 <= len(name) <= 100
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or name.casefold() == 'custom' or name.casefold().startswith('custom:')
            or type(model) is not str or not _MODEL.fullmatch(model)
            or auth_type not in {"none", "bearer", "api-key"}
            or data_policy not in DATA_POLICIES):
        raise CustomEndpointInvalid("invalid endpoint declaration")
    kind = classify_url(base_url)
    if data_policy == "local" and kind != "loopback":
        raise CustomEndpointInvalid("local policy requires loopback destination")
    return kind


def _endpoint(row) -> CustomEndpoint:
    try:
        item = CustomEndpoint(*tuple(row))
        _validate(item.key, item.name, item.base_url, item.model,
                  item.auth_type, item.data_policy)
        if (type(item.revision) is not int or item.revision < 1
                or type(item.config_revision) is not int or item.config_revision < 1
                or item.config_revision > item.revision
                or type(item.admission_proof) is not str
                or item.admission_proof and not _PROOF.fullmatch(item.admission_proof)):
            raise ValueError
        return item
    except (TypeError, ValueError, CustomEndpointInvalid) as exc:
        raise CustomEndpointInvalid("endpoint metadata unreadable") from exc


def _choice(conn) -> CustomChoice:
    rows = conn.execute("SELECT epoch FROM provider_choice_epoch").fetchall()
    choices = conn.execute("SELECT revision,active_key,config_revision,credential_generation,consent_proof,"
                           "unknown_price_ack,data_policy_ack "
                           "FROM custom_endpoint_choice").fetchall()
    if len(rows) != 1 or len(choices) != 1:
        raise CustomEndpointInvalid("endpoint choice unreadable")
    epoch, = rows[0]
    revision, key, config_revision, generation, proof, price_ack, data_ack = choices[0]
    if (type(epoch) is not int or epoch < 0 or type(revision) is not int or revision < 0
            or price_ack not in (0, 1) or data_ack not in (0, 1)
            or (key is None and (any(v is not None for v in (config_revision, generation, proof))
                                  or price_ack or data_ack))
            or (key is not None and (type(key) is not str or not _KEY.fullmatch(key)
                or type(config_revision) is not int or config_revision < 1
                or type(generation) is not int or generation < 0
                or type(proof) is not str or not _PROOF.fullmatch(proof)))):
        raise CustomEndpointInvalid("endpoint choice unreadable")
    return CustomChoice(epoch, revision, key, config_revision, generation, proof,
                        bool(price_ack), bool(data_ack))


def _with_read(callback):
    settings_db._ensure_init()
    with selection_gates.shared(settings_db.DB_PATH):
        conn = settings_db.get_conn()
        try:
            return callback(conn)
        finally:
            conn.close()


def read_choice() -> CustomChoice:
    return _with_read(_choice)


def read_endpoint(key: str) -> CustomEndpoint | None:
    def read(conn):
        row = conn.execute("SELECT key,name,base_url,model,auth_type,data_policy,revision,config_revision,admission_proof "
                           "FROM custom_endpoints WHERE key=?", (key,)).fetchone()
        return _endpoint(row) if row else None
    return _with_read(read)


def list_endpoints() -> list[CustomEndpoint]:
    def read(conn):
        rows = conn.execute("SELECT key,name,base_url,model,auth_type,data_policy,revision,config_revision,admission_proof "
                            "FROM custom_endpoints ORDER BY key").fetchall()
        return [_endpoint(row) for row in rows]
    return _with_read(read)


def read_active_endpoint() -> CustomEndpoint | None:
    def read(conn):
        choice = _choice(conn)
        if choice.active_key is None:
            return None
        row = conn.execute("SELECT key,name,base_url,model,auth_type,data_policy,revision,config_revision,admission_proof "
                           "FROM custom_endpoints WHERE key=?", (choice.active_key,)).fetchone()
        if row is None:
            raise CustomEndpointInvalid("active endpoint missing")
        endpoint = _endpoint(row)
        if endpoint.config_revision != choice.config_revision:
            raise CustomEndpointInvalid("active endpoint changed")
        return endpoint
    return _with_read(read)


def create_endpoint(key: str, name: str, base_url: str, model: str,
                    auth_type: str, data_policy: str, *, admission_proof: str = '') -> CustomEndpoint:
    _validate(key, name, base_url, model, auth_type, data_policy)
    if type(admission_proof) is not str or admission_proof and not _PROOF.fullmatch(admission_proof):
        raise CustomEndpointInvalid('invalid admission metadata')
    with selection_gates.exclusive(settings_db.DB_PATH, signed=True):
        settings_db._ensure_init()
        conn = settings_db.get_conn()
        try:
            with conn:
                try:
                    conn.execute("INSERT INTO custom_endpoints VALUES (?,?,?,?,?,?,1,1,?)",
                                 (key, name, base_url, model, auth_type, data_policy,
                                  admission_proof))
                    for alias in (key, name):
                        conn.execute('INSERT OR IGNORE INTO custom_endpoint_aliases '
                                     '(alias_key,alias,endpoint_key) VALUES (?,?,?)',
                                     (alias.casefold(), alias, key))
                        owned = conn.execute('SELECT endpoint_key FROM custom_endpoint_aliases '
                                             'WHERE alias_key=?', (alias.casefold(),)).fetchone()
                        if owned[0] != key:
                            raise CustomEndpointInvalid('endpoint alias already exists')
                except Exception as exc:
                    raise CustomEndpointInvalid("endpoint key already exists or store unavailable") from exc
            return _endpoint(conn.execute("SELECT * FROM custom_endpoints WHERE key=?", (key,)).fetchone())
        finally:
            conn.close()


def rename_endpoint(key: str, name: str, *, expected_revision: int) -> CustomEndpoint:
    with selection_gates.exclusive(settings_db.DB_PATH, signed=True):
        settings_db._ensure_init()
        conn = settings_db.get_conn()
        try:
            with conn:
                row = conn.execute("SELECT * FROM custom_endpoints WHERE key=?", (key,)).fetchone()
                if row is None:
                    raise CustomEndpointInvalid("endpoint missing")
                current = _endpoint(row)
                _validate(key, name, current.base_url, current.model,
                          current.auth_type, current.data_policy)
                if current.revision != expected_revision:
                    raise CustomEndpointConflict("endpoint revision changed")
                existing = conn.execute('SELECT endpoint_key FROM custom_endpoint_aliases '
                                        'WHERE alias_key=?', (name.casefold(),)).fetchone()
                if existing is not None and existing[0] != key:
                    raise CustomEndpointInvalid('endpoint alias already exists')
                conn.execute('INSERT OR IGNORE INTO custom_endpoint_aliases '
                             '(alias_key,alias,endpoint_key) VALUES (?,?,?)',
                             (name.casefold(), name, key))
                conn.execute("UPDATE custom_endpoints SET name=?,revision=revision+1 WHERE key=?",
                             (name, key))
            return _endpoint(conn.execute("SELECT * FROM custom_endpoints WHERE key=?", (key,)).fetchone())
        finally:
            conn.close()


def activate_endpoint(key: str, *, expected_revision: int,
                      expected_choice_epoch: int, proof: str,
                      credential_generation: int = 0,
                      unknown_price_ack: bool = False,
                      data_policy_ack: bool = False) -> CustomChoice:
    """Metadata CAS only; neither a caller-supplied proof nor this API grants use."""
    if (type(proof) is not str or not _PROOF.fullmatch(proof)
            or type(credential_generation) is not int or credential_generation < 0
            or type(unknown_price_ack) is not bool or type(data_policy_ack) is not bool):
        raise CustomEndpointInvalid("invalid choice metadata")
    with selection_gates.exclusive(settings_db.DB_PATH, signed=True):
        settings_db._ensure_init()
        conn = settings_db.get_conn()
        try:
            with conn:
                before = _choice(conn)
                if before.epoch != expected_choice_epoch:
                    raise CustomEndpointConflict("effective provider choice changed")
                row = conn.execute("SELECT * FROM custom_endpoints WHERE key=?", (key,)).fetchone()
                if row is None:
                    raise CustomEndpointInvalid("endpoint missing")
                endpoint = _endpoint(row)
                if endpoint.revision != expected_revision:
                    raise CustomEndpointConflict("endpoint revision changed")
                conn.execute("UPDATE signed_provider_selection SET revision=revision+1,"
                             "record_json=NULL,record_hash=NULL WHERE singleton=1")
                conn.execute("UPDATE custom_endpoint_choice SET revision=revision+1,active_key=?,"
                             "config_revision=?,credential_generation=?,consent_proof=?,"
                             "unknown_price_ack=?,data_policy_ack=? WHERE singleton=1",
                             (key, endpoint.config_revision, credential_generation, proof,
                              int(unknown_price_ack), int(data_policy_ack)))
                conn.execute("UPDATE provider_choice_epoch SET epoch=epoch+1 WHERE singleton=1")
            return _choice(conn)
        finally:
            conn.close()


def clear_endpoint_choice(*, expected_choice_epoch: int) -> CustomChoice:
    """Owner service can clear even when the active row is malformed or missing."""
    with selection_gates.exclusive(settings_db.DB_PATH, signed=True):
        settings_db._ensure_init()
        conn = settings_db.get_conn()
        try:
            with conn:
                row = conn.execute("SELECT epoch FROM provider_choice_epoch WHERE singleton=1").fetchone()
                if row is None or row[0] != expected_choice_epoch:
                    raise CustomEndpointConflict("effective provider choice changed")
                conn.execute("UPDATE custom_endpoint_choice SET revision=revision+1,active_key=NULL,"
                             "config_revision=NULL,credential_generation=NULL,consent_proof=NULL,"
                             "unknown_price_ack=0,data_policy_ack=0 WHERE singleton=1")
                conn.execute("UPDATE provider_choice_epoch SET epoch=epoch+1 WHERE singleton=1")
            return _choice(conn)
        finally:
            conn.close()


def delete_endpoint(key: str, *, expected_revision: int) -> None:
    with selection_gates.exclusive(settings_db.DB_PATH, signed=True):
        settings_db._ensure_init()
        conn = settings_db.get_conn()
        try:
            with conn:
                row = conn.execute("SELECT * FROM custom_endpoints WHERE key=?", (key,)).fetchone()
                if row is None:
                    raise CustomEndpointInvalid("endpoint missing")
                endpoint = _endpoint(row)
                if endpoint.revision != expected_revision:
                    raise CustomEndpointConflict("endpoint revision changed")
                active = conn.execute("SELECT active_key FROM custom_endpoint_choice WHERE singleton=1").fetchone()
                if active is None:
                    raise CustomEndpointInvalid("endpoint choice unreadable")
                if active[0] == key:
                    conn.execute("UPDATE custom_endpoint_choice SET revision=revision+1,active_key=NULL,"
                                 "config_revision=NULL,credential_generation=NULL,consent_proof=NULL,"
                                 "unknown_price_ack=0,data_policy_ack=0 WHERE singleton=1")
                    conn.execute("UPDATE provider_choice_epoch SET epoch=epoch+1 WHERE singleton=1")
                conn.execute('DELETE FROM custom_endpoint_aliases WHERE endpoint_key=?', (key,))
                conn.execute("DELETE FROM custom_endpoints WHERE key=?", (key,))
        finally:
            conn.close()
