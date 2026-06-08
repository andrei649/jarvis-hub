import test from "node:test";
import assert from "node:assert/strict";
import type { Pool } from "pg";
import {
  addComment,
  addItem,
  addMember,
  createCase,
  getCase,
  listCases,
  listComments,
  listItems,
  listMembers,
  removeMember,
  updateCaseStatus,
} from "../src/repositories/cases.js";

// Repository SQL-shape tests for the collaborative case file layer (ticket H19.4.5). Capturing mock
// pool: the case CRUD uses pool.query directly; the audit append (recordAction) runs INSIDE A
// TRANSACTION via pool.connect()->client (BEGIN / advisory lock / read tip+id / INSERT ... RETURNING /
// COMMIT). So the mock exposes BOTH a top-level query() and a connect() returning a capturing client,
// and every (sql, params) is recorded so a test can assert the case INSERT binds AND that an audit
// recordAction was emitted. No live Postgres — matches the repo's no-DB test style.
interface Captured {
  calls: { sql: string; params: unknown[] }[];
}

function mockPool(cap: Captured, rowsFor: (sql: string) => Record<string, unknown>[]): Pool {
  // The client used inside recordAction's transaction. Returns the reserved id/ts + a persisted audit
  // row, so the chain append completes; everything else (BEGIN/lock/COMMIT) returns empty.
  const clientQuery = async (sql: string, params: unknown[] = []) => {
    cap.calls.push({ sql, params });
    if (/nextval\('ontology_actions_id_seq'\)/.test(sql)) {
      return { rows: [{ id: 1, ts: 1717795200, tip_hash: null }], rowCount: 1 };
    }
    if (/INSERT INTO ontology_actions/.test(sql)) {
      return {
        rows: [
          {
            id: 1,
            ts: 1717795200,
            actor: "alice",
            object_type: "Case",
            object_id: "1",
            action: "case.create",
            params: {},
            result: null,
            source: "api",
            prev_hash: null,
            entry_hash: "h",
          },
        ],
        rowCount: 1,
      };
    }
    return { rows: [], rowCount: 0 };
  };
  return {
    query: async (sql: string, params: unknown[] = []) => {
      cap.calls.push({ sql, params });
      const rows = rowsFor(sql);
      return { rows, rowCount: rows.length };
    },
    connect: async () => ({ query: clientQuery, release: () => {} }),
  } as unknown as Pool;
}

// Did a transaction-bound audit append happen? (an INSERT INTO ontology_actions among the calls)
function auditedAction(cap: Captured): { sql: string; params: unknown[] } | undefined {
  return cap.calls.find((c) => /INSERT INTO ontology_actions/.test(c.sql));
}

function caseRow(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 1,
    title: "Strait incident",
    description: "two dark vessels",
    status: "open",
    created_by: "alice",
    created_at: 1717795200,
    updated_at: 1717795200,
    ...over,
  };
}

test("createCase: INSERTs title/description/created_by, adds the creator as owner member, emits a case.create audit", async () => {
  const cap: Captured = { calls: [] };
  const pool = mockPool(cap, (sql) => {
    if (/INSERT INTO cases/.test(sql)) return [caseRow()];
    if (/INSERT INTO case_members/.test(sql)) return [];
    return [];
  });
  const created = await createCase(pool, {
    title: "Strait incident",
    description: "two dark vessels",
    actor: "alice",
  });
  const insCase = cap.calls.find((c) => /INSERT INTO cases/.test(c.sql))!;
  assert.ok(insCase, "expected INSERT INTO cases");
  assert.match(insCase.sql, /INSERT INTO cases \(title, description, created_by\)/);
  assert.match(insCase.sql, /VALUES \(\$1, \$2, \$3\)/);
  assert.deepEqual(insCase.params, ["Strait incident", "two dark vessels", "alice"]);

  // Creator auto-added as owner.
  const insMember = cap.calls.find((c) => /INSERT INTO case_members/.test(c.sql))!;
  assert.ok(insMember, "expected the creator to be added as a member");
  assert.match(insMember.sql, /'owner'/);
  assert.deepEqual(insMember.params, [1, "alice"]);

  // Audited: a case.create row appended to the hash chain.
  const audit = auditedAction(cap);
  assert.ok(audit, "createCase must emit an audit recordAction");
  assert.equal(audit!.params[3], "Case"); // object_type bound to 'Case'

  assert.equal(created.id, 1);
  assert.equal(created.status, "open");
  assert.equal(created.createdBy, "alice");
});

test("getCase: selects by id with epoch timestamps; null when absent", async () => {
  const capHit: Captured = { calls: [] };
  const hit = await getCase(mockPool(capHit, () => [caseRow()]), 1);
  const c = capHit.calls[0];
  assert.match(c.sql, /FROM cases/);
  assert.match(c.sql, /WHERE id = \$1/);
  assert.match(c.sql, /extract\(epoch FROM created_at\)/);
  assert.deepEqual(c.params, [1]);
  assert.equal(hit!.id, 1);

  const miss = await getCase(mockPool({ calls: [] }, () => []), 99);
  assert.equal(miss, null);
});

test("listCases: newest-first with a LIMIT, maps epoch ts", async () => {
  const cap: Captured = { calls: [] };
  await listCases(mockPool(cap, () => [caseRow()]), { limit: 10 });
  const c = cap.calls[0];
  assert.match(c.sql, /FROM cases/);
  assert.match(c.sql, /ORDER BY created_at DESC, id DESC/);
  assert.match(c.sql, /LIMIT 10/);
});

test("updateCaseStatus: UPDATEs status + updated_at and emits a case.close audit", async () => {
  const cap: Captured = { calls: [] };
  const pool = mockPool(cap, (sql) =>
    /UPDATE cases/.test(sql) ? [caseRow({ status: "closed" })] : [],
  );
  const updated = await updateCaseStatus(pool, { id: 1, status: "closed", actor: "alice" });
  const upd = cap.calls.find((c) => /UPDATE cases/.test(c.sql))!;
  assert.match(upd.sql, /SET status = \$2, updated_at = now\(\)/);
  assert.match(upd.sql, /WHERE id = \$1/);
  assert.deepEqual(upd.params, [1, "closed"]);
  const audit = auditedAction(cap);
  assert.ok(audit, "updateCaseStatus must emit an audit recordAction");
  assert.equal(audit!.params[5], "case.close"); // action bound
  assert.equal(updated!.status, "closed");
});

test("updateCaseStatus: null (no audit) when the case doesn't exist", async () => {
  const cap: Captured = { calls: [] };
  const res = await updateCaseStatus(mockPool(cap, () => []), {
    id: 99,
    status: "closed",
    actor: "alice",
  });
  assert.equal(res, null);
  assert.equal(auditedAction(cap), undefined, "no audit row when nothing was updated");
});

test("addMember: upserts (case_id, actor, role) and emits a case.add_member audit", async () => {
  const cap: Captured = { calls: [] };
  const pool = mockPool(cap, (sql) =>
    /INSERT INTO case_members/.test(sql)
      ? [{ case_id: 1, actor: "bob", role: "collaborator", added_at: 1717795300 }]
      : [],
  );
  const member = await addMember(pool, {
    caseId: 1,
    member: "bob",
    role: "collaborator",
    actor: "alice",
  });
  const ins = cap.calls.find((c) => /INSERT INTO case_members/.test(c.sql))!;
  assert.match(ins.sql, /INSERT INTO case_members \(case_id, actor, role\)/);
  assert.match(ins.sql, /ON CONFLICT \(case_id, actor\) DO UPDATE SET role = EXCLUDED\.role/);
  assert.deepEqual(ins.params, [1, "bob", "collaborator"]);
  const audit = auditedAction(cap);
  assert.ok(audit, "addMember must emit an audit recordAction");
  assert.equal(audit!.params[5], "case.add_member");
  assert.equal(member.actor, "bob");
});

test("listMembers: by case, earliest first", async () => {
  const cap: Captured = { calls: [] };
  await listMembers(mockPool(cap, () => []), 1);
  const c = cap.calls[0];
  assert.match(c.sql, /FROM case_members/);
  assert.match(c.sql, /WHERE case_id = \$1/);
  assert.match(c.sql, /ORDER BY added_at ASC/);
  assert.deepEqual(c.params, [1]);
});

test("removeMember: DELETEs and emits case.remove_member only when a row was removed", async () => {
  const cap: Captured = { calls: [] };
  // rowCount 1 ⇒ removed ⇒ audited.
  const pool = {
    query: async (sql: string, params: unknown[] = []) => {
      cap.calls.push({ sql, params });
      return { rows: [], rowCount: /DELETE FROM case_members/.test(sql) ? 1 : 0 };
    },
    connect: async () => ({
      query: async (sql: string, params: unknown[] = []) => {
        cap.calls.push({ sql, params });
        if (/nextval/.test(sql)) return { rows: [{ id: 1, ts: 1, tip_hash: null }], rowCount: 1 };
        if (/INSERT INTO ontology_actions/.test(sql)) {
          return { rows: [{ id: 1, ts: 1, actor: "alice", object_type: "Case", object_id: "1", action: "case.remove_member", params: {}, result: null, source: "api", prev_hash: null, entry_hash: "h" }], rowCount: 1 };
        }
        return { rows: [], rowCount: 0 };
      },
      release: () => {},
    }),
  } as unknown as Pool;
  const removed = await removeMember(pool, { caseId: 1, member: "bob", actor: "alice" });
  const del = cap.calls.find((c) => /DELETE FROM case_members/.test(c.sql))!;
  assert.match(del.sql, /WHERE case_id = \$1 AND actor = \$2/);
  assert.deepEqual(del.params, [1, "bob"]);
  assert.equal(removed, true);
  assert.ok(auditedAction(cap), "removeMember must audit when a row was removed");
});

test("addItem: INSERTs object_type/object_id/note/added_by and emits a case.add_item audit", async () => {
  const cap: Captured = { calls: [] };
  const pool = mockPool(cap, (sql) =>
    /INSERT INTO case_items/.test(sql)
      ? [
          {
            id: 5,
            case_id: 1,
            object_type: "DarkVesselEvent",
            object_id: "123:456",
            note: "primary",
            added_by: "alice",
            added_at: 1717795400,
          },
        ]
      : [],
  );
  const item = await addItem(pool, {
    caseId: 1,
    objectType: "DarkVesselEvent",
    objectId: "123:456",
    note: "primary",
    actor: "alice",
  });
  const ins = cap.calls.find((c) => /INSERT INTO case_items/.test(c.sql))!;
  assert.match(ins.sql, /INSERT INTO case_items \(case_id, object_type, object_id, note, added_by\)/);
  assert.match(ins.sql, /VALUES \(\$1, \$2, \$3, \$4, \$5\)/);
  assert.deepEqual(ins.params, [1, "DarkVesselEvent", "123:456", "primary", "alice"]);
  const audit = auditedAction(cap);
  assert.ok(audit, "addItem must emit an audit recordAction");
  assert.equal(audit!.params[5], "case.add_item");
  assert.equal(item.objectId, "123:456");
});

test("listItems: by case, newest first", async () => {
  const cap: Captured = { calls: [] };
  await listItems(mockPool(cap, () => []), 1);
  const c = cap.calls[0];
  assert.match(c.sql, /FROM case_items/);
  assert.match(c.sql, /WHERE case_id = \$1/);
  assert.match(c.sql, /ORDER BY added_at DESC/);
});

test("addComment: INSERTs case_id/actor/body and emits a case.comment audit", async () => {
  const cap: Captured = { calls: [] };
  const pool = mockPool(cap, (sql) =>
    /INSERT INTO case_comments/.test(sql)
      ? [{ id: 7, case_id: 1, actor: "bob", body: "I concur", created_at: 1717795500 }]
      : [],
  );
  const comment = await addComment(pool, { caseId: 1, body: "I concur", actor: "bob" });
  const ins = cap.calls.find((c) => /INSERT INTO case_comments/.test(c.sql))!;
  assert.match(ins.sql, /INSERT INTO case_comments \(case_id, actor, body\)/);
  assert.match(ins.sql, /VALUES \(\$1, \$2, \$3\)/);
  assert.deepEqual(ins.params, [1, "bob", "I concur"]);
  const audit = auditedAction(cap);
  assert.ok(audit, "addComment must emit an audit recordAction");
  assert.equal(audit!.params[5], "case.comment");
  assert.equal(comment.actor, "bob");
});

test("listComments: by case, oldest first (thread order)", async () => {
  const cap: Captured = { calls: [] };
  await listComments(mockPool(cap, () => []), 1);
  const c = cap.calls[0];
  assert.match(c.sql, /FROM case_comments/);
  assert.match(c.sql, /WHERE case_id = \$1/);
  assert.match(c.sql, /ORDER BY created_at ASC/);
});

test("read paths degrade to []/null on undefined_table (42P01)", async () => {
  const fail = {
    query: async () => {
      throw Object.assign(new Error("relation does not exist"), { code: "42P01" });
    },
  } as unknown as Pool;
  assert.deepEqual(await listCases(fail, {}), []);
  assert.equal(await getCase(fail, 1), null);
  assert.deepEqual(await listMembers(fail, 1), []);
  assert.deepEqual(await listItems(fail, 1), []);
  assert.deepEqual(await listComments(fail, 1), []);
});
