/**
 * Harness test for the csl OpenClaw plugin.
 *
 * Loads index.ts (the adapter next to this file), registers it against a stub plugin API, and
 * drives both hooks with real payloads. Proves the plugin's behaviour without a live agent turn:
 * audit never blocks, gate blocks, the ledger is written, the comment is delivered and drained.
 *
 * The whole run uses a throwaway CSL_HOME. A test must not delete the evidence it is testing, so
 * this never touches the real ~/.csl.
 *
 * Needs Node 22.18+ or 23+, which strip TypeScript types natively.
 *
 *   node adapters/openclaw/verify.mjs
 */
import { existsSync, readFileSync, rmSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const PLUGIN = join(dirname(fileURLToPath(import.meta.url)), "index.ts");
const HOME = mkdtempSync(join(tmpdir(), "csl-verify-"));
const LEDGER = join(HOME, "hook-openclaw.jsonl");

// Seed this throwaway layer with the shipped rules, through the layer's own CLI.
const env = { ...process.env, CSL_HOME: HOME };
execFileSync("csl", ["init"], { encoding: "utf-8", env, stdio: "ignore" });

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${name}${detail ? " — " + detail : ""}`);
  ok ? pass++ : fail++;
};

function loadPlugin(config) {
  const handlers = {};
  const api = { config, on: (event, fn) => { handlers[event] = fn; } };
  return { handlers, api };
}

const register = (await import("file:///" + PLUGIN.replace(/\\/g, "/"))).default;

console.log(`layer under test: ${HOME}`);

// ---- 1. audit mode ------------------------------------------------------
console.log("\n== audit mode (the comment layer) ==");
let { handlers, api } = loadPlugin({ mode: "audit", cslHome: HOME });
register(api);
check("registers before_tool_call", typeof handlers["before_tool_call"] === "function");
check("registers before_prompt_build (the comment channel)",
      typeof handlers["before_prompt_build"] === "function");

const event = { toolName: "exec", params: { command: "git push --force origin main" } };
const ctx = { sessionId: "s1", sessionKey: "sess-1" };

const auditResult = handlers["before_tool_call"](event, ctx);
check("audit mode does NOT block", auditResult === undefined, `returned ${JSON.stringify(auditResult)}`);

const readLedger = () =>
  existsSync(LEDGER) ? readFileSync(LEDGER, "utf-8").trim().split("\n").filter(Boolean).map(JSON.parse) : [];
const ledger = readLedger();
check("ledger records the call", ledger.length === 1);
check("ledger names the high-stakes classes",
      (ledger[0]?.high_stakes ?? []).length === 2, JSON.stringify(ledger[0]?.high_stakes));
check("ledger names the matched rules",
      JSON.stringify(ledger[0]?.matched_rules) === '["R-001","R-002"]', JSON.stringify(ledger[0]?.matched_rules));

const comment = handlers["before_prompt_build"]({}, ctx);
check("comment is delivered to the model",
      typeof comment?.prependContext === "string" && comment.prependContext.includes("common-sense layer"),
      JSON.stringify(comment?.prependContext)?.slice(0, 90));
check("comment names the unvalidated rules",
      /R-001/.test(comment?.prependContext ?? "") && /R-002/.test(comment?.prependContext ?? ""));
check("comment queue is drained (no repeat)",
      handlers["before_prompt_build"]({}, ctx) === undefined);

// ---- 2. a benign call ---------------------------------------------------
console.log("\n== a benign call ==");
handlers["before_tool_call"]({ toolName: "read", params: { path: "C:/tmp/a.txt" } }, ctx);
const after = readLedger();
check("benign call is allowed", after[after.length - 1]?.decision === "allow", after[after.length - 1]?.decision);
check("benign call queues no comment", handlers["before_prompt_build"]({}, ctx) === undefined);

// ---- 3. gate mode -------------------------------------------------------
console.log("\n== gate mode ==");
({ handlers, api } = loadPlugin({ mode: "gate", cslHome: HOME }));
register(api);
const gated = handlers["before_tool_call"](event, { sessionId: "s2", sessionKey: "sess-2" });
check("gate mode BLOCKS an unvalidated high-stakes call", gated?.block === true);
check("the block reason names the missing rules",
      /R-001/.test(gated?.blockReason ?? "") && /R-002/.test(gated?.blockReason ?? ""),
      JSON.stringify(gated?.blockReason)?.slice(0, 100));

// ---- 4. the human tier holds -------------------------------------------
console.log("\n== the chk:human tier ==");
for (const rule of ["R-001", "R-002"]) {
  try {
    execFileSync("csl", ["record", "--session", "s3", "--domain",
      "external send, publish or post destructive or irreversible operation",
      "--results", `${rule}=pass:harness test`], { encoding: "utf-8", env, stdio: "ignore" });
    check(`${rule} refused by the agent path`, false, "record accepted a chk:human verdict");
  } catch {
    /* expected: check.py refuses to self-certify a chk:human rule */
  }
}
const s3 = handlers["before_tool_call"](event, { sessionId: "s3", sessionKey: "sess-3" });
check("a chk:human rule cannot be self-recorded, so the gate still blocks", s3?.block === true,
      "only `csl attest` may clear it");

// ---- 5. fail open -------------------------------------------------------
console.log("\n== fail open ==");
const { handlers: h5, api: a5 } = loadPlugin({ mode: "gate", cslHome: HOME, timeoutMs: 1 });
register(a5);
const timedOut = h5["before_tool_call"](event, { sessionId: "s4", sessionKey: "sess-4" });
check("a layer that does not answer in time does NOT block", timedOut === undefined,
      "a wedged hook is worse than a missing guard");

rmSync(HOME, { recursive: true, force: true });
console.log(`\n${pass}/${pass + fail} checks pass`);
process.exit(fail ? 1 : 0);