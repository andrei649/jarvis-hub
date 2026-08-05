# Nerva Innovation Lab — RFC and Knowledge Garden contract v1

Status: **documentation/control-only foundation for #805**. This contract creates
no production runtime, provider, adapter, prototype, capability, or delivery
queue. It grants no delivery or action authority.

The governed sources are:

- `INNOVATION_LAB_V1.schema.json` — the pinned structural contract;
- `KNOWLEDGE_GARDEN_V1.json` — the append-only canonical registry;
- `scripts/check_nerva_innovation_lab.py` — the standard-library trust boundary;
- `tests/_nerva_innovation_lab_checks.py` — a count-neutral hostile matrix;
- `.github/workflows/nerva-roadmap.yml` — immutable-ref CI wiring.

## 1. Outcome and non-goals

The Innovation Lab preserves observations, ideas, alternatives, evidence,
negative results, decisions, and later outcomes without allowing research to
become delivery silently. The inspectable chain is:

```text
OBSERVATION → optional IDEA → optional RFC → EVIDENCE → optional PROTOTYPE
                                      ↓
                                   DECISION → separate EPIC → OUTCOME
```

An observation may remain an observation. An idea must have one or more
motivating observations, but may remain unpromoted with no RFC. This is deliberate:
the control must represent honest early discovery instead of forcing fabricated
progression. Once an idea has RFC revisions, those revisions form one stable,
ordered lineage.

This slice does not:

- write, merge, deploy, route, schedule, or promote implementation;
- change `BACKLOG.md`, `STATUS.md`, or a dependency DAG automatically;
- approve or complete a privileged action;
- execute external code or ingest private owner data;
- treat a prototype, score, CI result, or catalogue row as live proof;
- satisfy the required completed incremental/radical/parked examples in #805.

## 2. One fail-closed validation pipeline

Validation has one order and no alternate permissive path:

```text
strict UTF-8 JSON decode
  → pinned closed schema-profile validation
  → candidate schema evaluation
  → closed graph / evidence / lifecycle semantics
  → accepted Git-baseline comparison
```

The decoder rejects duplicate object keys, `NaN`, infinities, numeric overflow,
invalid UTF-8, and non-object schema/garden roots. The schema file is pinned by
its raw SHA-256 and declares
`x-nerva-schema-profile=nerva.stdlib-schema-profile.v1`.

That profile implements only `$defs`, local JSON-pointer `$ref`, `type`, `const`,
`enum`, `required`, `properties`, `additionalProperties`, `items`, `minItems`,
`maxItems`, `uniqueItems`, `minLength`, `pattern`, `minimum`, `maximum`, `oneOf`,
and `not`. Root metadata is limited to `$schema`, `$id`, and the profile marker.
Remote or cyclic references, `$ref` siblings, unknown keywords, invalid keyword
types, and boolean/integer lookalikes fail. In particular, `false` is not `0`.
The shared non-empty-string definition requires at least one non-whitespace
character, so padded actor roles, claims, rationale, and reconsideration text do
not pass as content.

The schema document is validated before it is allowed to validate the garden.
After bootstrap, accepted baseline schema bytes and semantics are immutable.

## 3. Immutable Git input boundary

The repository checker accepts only:

```powershell
python scripts/check_nerva_innovation_lab.py `
  --baseline-ref <exact-lowercase-40-hex-sha> `
  --candidate-ref <exact-lowercase-40-hex-sha>
```

Both inputs are argv values, never interpolated into a shell command. The
candidate must equal `HEAD`; the baseline must resolve and be an ancestor of the
candidate. A shallow repository, missing commit, malformed SHA, unreachable
baseline, or missing candidate path fails closed. The checker reads the schema
and garden with `git show <sha>:<path>`, never from mutable worktree bytes.

Bootstrap is allowed only when the resolved baseline lacks both governed paths.
If it contains only one, validation fails. Pull requests supply exact
`base.sha`/`head.sha`; pushes supply `before`/`after`; manual dispatch requires
both inputs. Checkout uses full history and `persist-credentials: false`.

## 4. Append-only baseline contract

Once accepted, historical facts do not move:

- prior record IDs and array order remain fixed, while prior objects retain
  exact canonical-JSON/semantic equivalence;
- catalogue and link arrays retain the exact accepted semantic prefix and exact
  string values;
- an RFC core is immutable; only `stage`, `stage_history`, and
  `outcome_history` may advance;
- both histories retain their exact accepted prefix and append legal,
  strictly increasing transitions;
- new revisions are new records and point backward to the exact direct
  predecessor;
- new observations may append `MOTIVATES` edges to a retained idea without
  rewriting that idea or its existing stable-ID lineage;
- non-terminal RFCs may append their required evidence, prototype, and decision
  edges as they progress through valid lifecycle gates, including links to
  retained evidence already owned by the same stable-ID lineage;
- terminal edges freeze, except the narrowly bound reopen lineage and an
  accepted RFC's new post-decision evidence/outcome links.

JSON object member order and lexical whitespace are serialization choices, not
semantic state. Array order, array prefixes, types, numbers, and string contents
remain authoritative.

Changing an old rationale, evidence class, source, decision, link, catalogue,
timestamp, or record order is not a new revision. It is rejected history.

## 5. Closed Knowledge Garden graph

Node kinds are `OBSERVATION`, `IDEA`, `RFC`, `EVIDENCE`, `PROTOTYPE`, `DECISION`,
`EPIC`, and `OUTCOME`. Legal directed edges are:

| Edge | From → to |
|---|---|
| `MOTIVATES` | observation → idea |
| `DEVELOPED_AS` | idea → RFC |
| `SUPPORTED_BY` / `CHALLENGED_BY` | RFC → evidence |
| `TESTED_BY` | RFC → prototype |
| `DECIDED_BY` | RFC → decision |
| `ACCEPTED_AS` | accepted decision → separate epic |
| `PRODUCED` | epic → outcome |
| `SUPERSEDES` | new RFC revision → direct predecessor |
| `REOPENS` | new RFC revision → retained parked/rejected decision |

Every non-observation record must be reachable from an observation. An idea has
one or more motivating observations and may own zero RFCs; once RFCs exist, all
belong to exactly one stable-ID lineage. Evidence has one or more RFC owners,
but every owner must be a revision in that same stable lineage. The same
RFC/evidence pair cannot simultaneously be `SUPPORTED_BY` and `CHALLENGED_BY`.
RFCs, prototypes, decisions, epics, and outcomes each retain one exact owner. A
decision cannot decide two RFCs, and a prototype cannot migrate across chains.
IDs and edges are unique, dangling links fail, and each node is validated
independently even if another node already makes the candidate invalid.

## 6. Evidence integrity and reopening

Every evidence record stores `integrity_sha256`, `observed_at`, class, source,
claim, and limitations. Two identities are calculated:

- artifact fingerprint: the SHA-256 digest;
- semantic fingerprint: SHA-256 over artifact fingerprint plus NFC-normalized,
  whitespace-collapsed claim and limitations.

IDs and source locators do not create new evidence. The same artifact must keep
its class and source, and a semantic fingerprint is unique. This blocks copying
an evidence node under a new ID, relabeling repository evidence as owner-live,
or rewriting whitespace to manufacture novelty.

A later RFC revision must `SUPERSEDES` its exact direct predecessor. If that
predecessor was `PARKED` or `REJECTED`, the revision must also:

1. point with `REOPENS` to that predecessor's exact decision;
2. repeat that decision ID in `reopens_decision_id`;
3. link a genuinely new artifact absent from the prior decision;
4. record that evidence after the prior `decided_at` timestamp.

Every successor's initial `DRAFT` timestamp is strictly after its predecessor's
decision. Accepted history terminates that stable-ID lineage and never reopens.
A failed accepted outcome remains an outcome; follow-on work needs a new idea
and stable ID, without rewriting the old acceptance.

## 7. Lifecycle and decision contract

Lifecycle stages are `DRAFT`, `EVIDENCE_GATHERING`, `READY_FOR_REVIEW`, `DECIDED`,
and `OUTCOME_REVIEWED`. Histories are contiguous and timestamps strictly
increase. Legal transitions are:

```text
∅ → DRAFT
DRAFT → EVIDENCE_GATHERING
DRAFT → DECIDED                         (PARKED/REJECTED only)
EVIDENCE_GATHERING → READY_FOR_REVIEW
EVIDENCE_GATHERING → DECIDED            (PARKED/REJECTED only)
READY_FOR_REVIEW → EVIDENCE_GATHERING
READY_FOR_REVIEW → DECIDED
DECIDED → OUTCOME_REVIEWED              (accepted chain only)
```

Decision status is exactly `ACCEPTED_FOR_EPIC`, `PARKED`, or `REJECTED`, with
`basis=evidence_and_review`. Reviewer and author IDs match exactly
`^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$` and must differ. Advisory scores never
participate in a decision.

An RFC or prototype using `private_data_policy=local_only_fixture` supplies a
non-whitespace `policy_ref`; `null`, empty, and whitespace-only references fail
both schema and semantic validation.

`ACCEPTED_FOR_EPIC` requires `READY_FOR_REVIEW`, strong exact-RFC evidence, no
unresolved requirements, one separate epic, and a `pending` outcome history.
Every epic uses repository `andrei649/jarvis-hub`; its `(repository, issue)` pair
is globally unique and issue #805 is forbidden as a delivery epic.
`PARKED` and `REJECTED` create no epic/outcome and remain `not_applicable`;
parked work names its unresolved requirement. Durable acceptance or rejection
cannot rely only on secondary/simulation evidence.

## 8. Prototype and outcome binding

A required prototype has exactly one owner and its branch begins
`nerva-lab/<exact-rfc-record-id-lower>-`. It is disposable, excludes production
data, names teardown, and either excludes private data or cites a local fixture
policy. It records canonical `tested_at`, no earlier than the owning RFC's
initial `DRAFT`, no later than its first `READY_FOR_REVIEW` transition, and
strictly before its decision. A required prototype may still be absent while
the RFC is earlier than review;
`not_required` forbids a hidden prototype edge.

`OUTCOME_REVIEWED` requires the accepted RFC, its exact decision, its one epic,
and that epic's one outcome. Outcome evidence must be linked to the exact RFC,
must not have supported the original decision, and must be observed after that
decision but no later than the outcome's measured/final transition. Lifecycle,
outcome history, and measured timestamps bind. An
`owner_live` claim additionally requires new `owner_live` evidence.

## 9. Exact authority ceiling

The top-level object and every RFC carry the same complete authority object:

```text
can_commit_main=false
can_merge=false
can_deploy=false
can_change_roadmap=false
can_promote_capability=false
can_authorize_actions=false
can_claim_completion=false
grants_authority=false
privileged_action_authority=nerva.action.v1
```

Unknown fields and boolean lookalikes fail. Ultron / `nerva.action.v1` remains
the sole privileged-action authority outside this control. The Innovation Lab
cannot approve, merge, deploy, promote, or claim completion.

## 10. Versioned precursor catalogue anchors

Catalogue rows remain `reference_only`, `precursor_hypotheses_only`, and satisfy
no #805 checkbox. Each accepted catalogue revision has a distinct immutable
anchor; prior anchors are never relabeled:

| Anchor | PR / issue | Merge | Git blob | Bytes | SHA-256 |
|---|---|---|---|---:|---|
| `CATALOGUE-EXTERNAL-INTEGRATIONS-V1` | #821 | `ccc36e851094976fe8f6c209a8c2f5bf07aaad05` | `9e446b8d7c5fbad954760f665a24de11b9755c59` | 16,965 | `5697cc44824b01efb20cd345e79846b1ecd086a4999e2e75d0984c4b3d1944d3` |
| `CATALOGUE-EXTERNAL-INTEGRATIONS-V2` | #826 / #825 | `72dca7eea42229cca9a55a5bda7276810c376d8e` | `9aee52226fa6e0075023f419a8273332f799ca46` | 19,409 | `8d39336e657424a39fb1e77b4b12460085bd6aa86449267ce0553a5757161dae` |
| `CATALOGUE-EXTERNAL-INTEGRATIONS-V3` | #827 / #824 | `002b30fcdf7077880ad4f42f3c2297e97d26afa9` | `245b0f7e90f414659499bd56bc157ff72c87e340` | 19,681 | `ad211700fd4fc81be3006f31b2d5011e1070b56e2281ee94e5f298fe783972c9` |

V2 supersedes V1 and records the MCP Registry evidence correction. V3
supersedes V2 and records the later drift-policy revision. The V1 object remains
the exact accepted #821 anchor; V2 and V3 are appended records. Git history is
used to verify every blob, byte count, and digest. These are integrity facts,
not signatures, authenticity, acceptance, or implementation authority.

## 11. Existing-stream boundaries and truthful state

- E8 owns accepted capability contracts, acquisition, and promotion paths.
- E9 owns reproducible benchmark and negative-result evidence.
- E12 may supply advisory research methods but cannot decide or authorize.
- #804 owns Hermes/provider work; this control cannot implement it.
- normal security, privacy, architecture, CI, and independent review remain
  external publication gates.

Run the hostile matrix directly:

```powershell
python tests/_nerva_innovation_lab_checks.py
```

It covers schema mutations, nested invalid types, orphans, multiple ownership,
cross-chain decisions, append-only rewrites, backdated histories, evidence
clones/relabels, reopen bypasses, prototype/outcome misbinding, authority drift,
catalogue drift, malformed refs, non-ancestors, and shallow history.

Even after this control passes independent review and exact-head CI, it supplies
only the process/schema foundation. #805 remains open and `DISCOVERY`; it still
needs real, separately evidenced examples before any completion claim.

Rollback is one atomic revert of these six control files. It changes no runtime
state, provider, private data, or authority.
