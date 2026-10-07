/**
 * csl — the common-sense layer, as an OpenClaw plugin.
 *
 * The layer itself is the `csl` CLI (`pip install .` / `uv tool install .`). This file only
 * bridges it to OpenClaw, which loads TypeScript plugins from
 * `~/.openclaw/extensions/<id>/` and calls the default export with the plugin API.
 *
 * Two hooks are registered:
 *
 *   before_tool_call    — ask the layer about every tool call. In `gate` mode an unvalidated
 *                         high-stakes call is blocked; in `audit` mode nothing is blocked and
 *                         the verdict is recorded and queued as a comment.
 *   before_prompt_build — hand the queued comments to the model on the next turn. Without this,
 *                         audit mode computes a verdict and discards it: OpenClaw's
 *                         before_tool_call result has no advisory channel.
 *
 * Every decision is appended to `$CSL_HOME/hook-openclaw.jsonl`, so the ledger shows what
 * actually fired. Every failure path fails open: a wedged agent is worse than a missing guard.
 */

import { execFileSync } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

type CslVerdict = {
  decision?: string;
  action?: string;
  reason?: string;
  message?: string;
  csl?: {
    session?: string;
    decision?: string;
    reason?: string;
    high_stakes?: string[];
    matched_rules?: string[];
    missing?: Array<{ id: string; chk: string; when: string }>;
    mode?: string;
  };
};

/**
 * The layer emits its verdict in two shapes. A block is top-level
 * (`{"decision":"block","action":"block","reason":...}`); an audit note is nested
 * (`{"decision":"allow","csl":{"decision":"advise","reason":...}}`). Read the effective
 * verdict from whichever carries it, so the two never get confused for one another.
 */
function effective(verdict: CslVerdict) {
  const inner = verdict.csl;
  return {
    decision: inner?.decision ?? verdict.decision ?? "allow",
    reason: verdict.reason ?? verdict.message ?? inner?.reason ?? "",
    high_stakes: inner?.high_stakes ?? [],
    matched_rules: inner?.matched_rules ?? [],
    missing: inner?.missing ?? [],
  };
}

type PluginConfig = {
  mode?: "audit" | "gate";
  cslHome?: string;
  timeoutMs?: number;
  comment?: boolean;
};

const DEFAULT_TIMEOUT_MS = 5000;

function layerHome(config: PluginConfig): string {
  if (config.cslHome) return config.cslHome;
  if (process.env.CSL_HOME) return process.env.CSL_HOME;
  return join(homedir(), ".csl");
}

/** Prefer an absolute binary: OpenClaw's own PATH may not contain the tool bin directory. */
function cslBin(): string {
  const explicit = process.env.CSL_BIN;
  if (explicit && existsSync(explicit)) return explicit;
  const local = join(homedir(), ".local", "bin", process.platform === "win32" ? "csl.exe" : "csl");
  if (existsSync(local)) return local;
  return "csl";
}

function safeSessionKey(value: unknown): string {
  return String(value ?? "openclaw-unknown").replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 120);
}

function record(home: string, entry: Record<string, unknown>): void {
  try {
    mkdirSync(home, { recursive: true });
    appendFileSync(join(home, "hook-openclaw.jsonl"), JSON.stringify(entry) + "\n", "utf-8");
  } catch {
    /* never let bookkeeping break a tool call */
  }
}

/** Ask the layer about one tool call. Returns the verdict, or null when the layer failed. */
function askLayer(
  home: string,
  config: PluginConfig,
  toolName: string,
  params: Record<string, unknown>,
  sessionId: string,
): { verdict: CslVerdict; exit: number } | null {
  const mode = config.mode ?? "audit";
  const payload = {
    hook_event_name: "before_tool_call",
    tool_name: toolName,
    tool_input: params ?? {},
    session_id: sessionId,
    cwd: process.cwd(),
  };
  const options = {
    input: JSON.stringify(payload),
    encoding: "utf-8" as const,
    timeout: config.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    env: { ...process.env, CSL_HOOK_MODE: mode, ...(config.cslHome ? { CSL_HOME: home } : {}) },
  };
  try {
    const stdout = execFileSync(cslBin(), ["hook", "--harness", "openclaw"], options);
    return { verdict: parse(stdout), exit: 0 };
  } catch (error: any) {
    // Exit 2 is the layer's block signal and carries its verdict on stdout.
    if (error?.status === 2) return { verdict: parse(error.stdout), exit: 2 };
    // Anything else (missing binary, timeout, crash) fails open, recorded as such.
    record(home, { harness: "openclaw", tool: toolName, session: sessionId, exit: error?.status ?? null,
                   decision: "hook-error", reason: String(error?.message ?? error).slice(0, 200) });
    return null;
  }
}

function parse(raw: unknown): CslVerdict {
  const text = typeof raw === "string" ? raw.trim() : "";
  if (!text) return {};
  try {
    return JSON.parse(text) as CslVerdict;
  } catch {
    return {};
  }
}

function isBlock(result: { verdict: CslVerdict; exit: number }): boolean {
  const decision = effective(result.verdict).decision;
  return result.exit === 2 || decision === "block" || result.verdict.action === "block";
}

/** Queue one comment for the next prompt build. */
function queueComment(home: string, sessionKey: string, text: string): void {
  try {
    const dir = join(home, "pending");
    mkdirSync(dir, { recursive: true });
    appendFileSync(join(dir, sessionKey + ".jsonl"), JSON.stringify({ text }) + "\n", "utf-8");
  } catch {
    /* ledger-only is an acceptable degradation */
  }
}

/** Take every comment queued for this session and empty the queue. */
function drainComments(home: string, sessionKey: string): string[] {
  const file = join(home, "pending", sessionKey + ".jsonl");
  try {
    if (!existsSync(file)) return [];
    const lines = readFileSync(file, "utf-8").split("\n").filter((l) => l.trim());
    const texts = lines.map((l) => { try { return JSON.parse(l).text as string; } catch { return ""; } })
                       .filter((t) => typeof t === "string" && t.trim());
    rmSync(file, { force: true });
    return texts;
  } catch {
    return [];
  }
}

function describe(result: { verdict: CslVerdict; exit: number }): string {
  const v = effective(result.verdict);
  const reason = v.reason || "high-stakes call with no recorded validation";
  const named = v.missing.map((m) => `${m.id} [chk:${m.chk}] ${m.when}`).join(" | ");
  const rules = v.matched_rules.join(", ");
  return [
    `common-sense layer: ${reason}`,
    rules ? `matched rules: ${rules}` : "",
    named ? `unvalidated: ${named}` : "",
    "Record a verdict with `csl record`, or a human verdict with `csl attest`.",
  ].filter(Boolean).join("\n");
}

export default function register(api: any): void {
  const config: PluginConfig = api.config ?? {};
  const home = layerHome(config);
  const mode = config.mode ?? "audit";
  const comment = config.comment !== false;

  if (!existsSync(cslBin()) && cslBin() === "csl") {
    console.warn("[csl] the `csl` binary was not found — the common-sense layer is NOT guarding this agent");
    return;
  }

  api.on(
    "before_tool_call",
    (event: { toolName: string; params: Record<string, unknown> }, ctx: any) => {
      const sessionId = String(ctx?.sessionId ?? ctx?.sessionKey ?? "openclaw-unknown");
      const result = askLayer(home, config, event.toolName ?? "", event.params ?? {}, sessionId);
      if (!result) return;                       // fail open

      const v = effective(result.verdict);
      record(home, {
        harness: "openclaw", mode, tool: event.toolName, session: sessionId, exit: result.exit,
        decision: v.decision,
        reason: v.reason,
        high_stakes: v.high_stakes,
        matched_rules: v.matched_rules,
      });

      if (isBlock(result)) {
        if (mode === "gate") return { block: true, blockReason: `common-sense: ${describe(result)}` };
        // audit mode never blocks; it comments.
        if (comment) queueComment(home, safeSessionKey(ctx?.sessionKey ?? sessionId),
                                  `a high-stakes call was allowed unvalidated — ${describe(result)}`);
        return;
      }

      if (v.decision === "advise" && comment) {
        queueComment(home, safeSessionKey(ctx?.sessionKey ?? sessionId), describe(result));
      }
      return;
    },
    { priority: 50 },
  );

  if (!comment) return;

  // The comment channel. A prompt hook that throws would break the turn, so registration and
  // the handler both degrade quietly to ledger-only.
  try {
    api.on("before_prompt_build", (_event: unknown, ctx: any) => {
      const texts = drainComments(home, safeSessionKey(ctx?.sessionKey ?? ctx?.sessionId));
      if (!texts.length) return;
      return { prependContext: "Common-sense layer notes:\n" + texts.map((t) => "- " + t).join("\n") };
    });
  } catch (error: any) {
    console.warn(`[csl] comment channel unavailable (${String(error?.message ?? error)}); ledger-only`);
  }
}