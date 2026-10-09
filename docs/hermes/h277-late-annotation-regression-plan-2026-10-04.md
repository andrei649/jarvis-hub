# H277 direct late-annotation regression

Generated 2026-10-04. Goal: all 697 pinned Hermes capabilities. Base/head:
`8c0d8677`. This unit covers the direct action-queue API coverage gap found by
the original 49 prepared mutation campaign; it changes no execution behavior.

Before editing: add the proposed regression to `tests/`, assert a decided
action cannot acquire a late judge annotation and its durable bytes stay
unchanged, then run it with the existing judge regressions. Recheck the same
single fault in a disposable snapshot: baseline must pass, removing only the
decided-item guard must fail an assertion, then restore the source byte-for-byte.
Update the generated backend count and the separate supplemental handoff record;
the original campaign remains 41 assertion kills, 6 behavioral exceptions and
2 survivors. The earlier 22,395-case full run does not include this new test.

Paths: the new test, this plan, H277 handoff records and generated status files.
No production changes, provider calls, publication or parity credit. Rollback:
revert the test/record unit and regenerate status counts. Next action: add and
run the direct regression; a later integrated source milestone runs the full suite.


Verification:178 integrated cases passed. The isolated single fault failed the
new returned-verdict assertion and all3,003 snapshot inputs were restored. The
tracked count was regenerated as22,396; it is collection evidence, not a new
full-suite result. Final record checks and exact selected-index scan precede
local delivery.
