import test from "node:test";
import assert from "node:assert/strict";
import { assertSafeBind, isLoopbackHost } from "../src/config.js";

// AUD-4 — the API must refuse to boot network-exposed with authentication disabled.

test("isLoopbackHost recognizes loopback addresses only", () => {
  for (const h of ["127.0.0.1", "localhost", "::1"]) {
    assert.equal(isLoopbackHost(h), true);
  }
  for (const h of ["0.0.0.0", "10.0.0.5", "192.168.1.2", "example.com"]) {
    assert.equal(isLoopbackHost(h), false);
  }
});

test("assertSafeBind refuses a network-exposed bind with empty authSecret", () => {
  assert.throws(
    () => assertSafeBind({ host: "0.0.0.0", authSecret: "" }),
    /Refusing to start/,
  );
});

test("assertSafeBind allows a network-exposed bind once authSecret is set", () => {
  assert.doesNotThrow(() => assertSafeBind({ host: "0.0.0.0", authSecret: "a-real-secret" }));
});

test("assertSafeBind allows a loopback bind with empty authSecret (local dev)", () => {
  assert.doesNotThrow(() => assertSafeBind({ host: "127.0.0.1", authSecret: "" }));
  assert.doesNotThrow(() => assertSafeBind({ host: "localhost", authSecret: "" }));
});
