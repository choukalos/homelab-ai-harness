/**
 * Mocked Pi grooming session for tests (Slice 2) — no network, no model.
 *
 * The mock session factory is file-backed: transcripts persist to the
 * stable session file path (JSON), so resume-after-restart
 * (SessionManager.open semantics) and cancel/re-groom file deletion are
 * exercised the same way the real SessionManager would behave.
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { UsageSample } from "./sessions.js";
import type {
  GroomSessionCreateOptions,
  GroomSessionFactory,
  GroomSessionLike,
} from "./grooming.js";

export function mockUserMsg(text: string): AgentMessage {
  return { role: "user", content: text, timestamp: Date.now() } as AgentMessage;
}

export function mockAssistantMsg(text: string): AgentMessage {
  return {
    role: "assistant",
    content: [{ type: "text", text }],
    api: "openai-completions",
    provider: "litellm",
    model: "test-model",
    usage: {
      input: 10,
      output: 5,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 15,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0.01 },
    },
    stopReason: "stop",
    timestamp: Date.now(),
  } as AgentMessage;
}

export type GroomResponder = (prompt: string) => string;

/**
 * Default mock responder: chat turns echo the prompt; the FINALIZE prompt
 * returns a valid spec JSON (no deps). Tests override for specific cases.
 */
export function defaultGroomResponder(prompt: string): string {
  if (prompt.startsWith("FINALIZE")) {
    return JSON.stringify({
      goal: "Mock goal",
      steps: ["step 1", "step 2"],
      acceptance: ["acceptance 1"],
      kind: "code",
      publish_targets: null,
      notes: null,
      depends_on: [],
    });
  }
  return `mock reply to: ${prompt.slice(0, 40)}`;
}

export class MockGroomSession implements GroomSessionLike {
  readonly prompts: string[] = [];
  disposed = false;
  aborted = false;
  private _messages: AgentMessage[];

  constructor(
    readonly sessionFile: string,
    private readonly responder: GroomResponder,
    private onUsage?: (u: UsageSample) => void,
    private readonly slowMs: number | (() => number) = 0,
    private readonly activityMs?: number | (() => number | undefined),
    private onActivity?: (kind: string) => void,
  ) {
    // SessionManager.open semantics: resume the transcript if the file exists.
    this._messages = existsSync(sessionFile)
      ? (JSON.parse(readFileSync(sessionFile, "utf8")) as AgentMessage[])
      : [];
  }

  get messages(): AgentMessage[] {
    return this._messages;
  }

  async prompt(text: string): Promise<void> {
    this.prompts.push(text);
    this._messages.push(mockUserMsg(text));
    // Persist the user message immediately (the real session file grows per
    // message, so an aborted turn still leaves the user message behind).
    writeFileSync(this.sessionFile, JSON.stringify(this._messages));
    const delay = typeof this.slowMs === "function" ? this.slowMs() : this.slowMs;
    if (delay > 0) {
      // Wait in small slices so abort() can interrupt, emitting activity
      // events every `activityMs` (default: a couple of ticks) to simulate
      // live streaming (turn watchdog input).
      const step = 25;
      const cadence = typeof this.activityMs === "function" ? this.activityMs() : this.activityMs;
      const every = Math.max(cadence ?? 50, step);
      for (let waited = 0; waited < delay; waited += step) {
        if (this.aborted) throw new Error("mock grooming turn aborted");
        if (waited % every === 0) this.onActivity?.("message_update");
        await new Promise((r) => setTimeout(r, step));
      }
      if (this.aborted) throw new Error("mock grooming turn aborted");
    }
    const reply = this.responder(text);
    this._messages.push(mockAssistantMsg(reply));
    // Persist (the real session file is JSONL; the mock stores JSON).
    writeFileSync(this.sessionFile, JSON.stringify(this._messages));
    this.onUsage?.({
      role: "groom",
      model: "test-model",
      thinking: "xhigh",
      input: 10,
      output: 5,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 15,
      cost: 0.01,
    });
  }

  dispose(): void {
    this.disposed = true;
  }

  abort(): void {
    this.aborted = true;
  }
}

export interface MockGrooming {
  factory: GroomSessionFactory;
  sessions: MockGroomSession[];
  /** Factory options of each session creation (in order). */
  created: GroomSessionCreateOptions[];
  setResponder(fn: GroomResponder): void;
  /** Change the prompt delay for future turns (e.g. unstick after a watchdog test). */
  setSlowMs(ms: number): void;
  /** Change the activity cadence for future turns (Infinity = no activity). */
  setActivityMs(ms: number): void;
}

export interface MockGroomingOptions {
  /** Delay each prompt by this many ms (simulate a slow LLM turn). */
  slowMs?: number;
  /**
   * Emit a mock activity event every N ms while a slow prompt is in flight
   * (simulate live streaming for the turn watchdog). Default 50ms when
   * slowMs > 0; set to Infinity to simulate a stuck turn (no activity).
   */
  activityMs?: number;
}

export function createMockGrooming(
  responder: GroomResponder = defaultGroomResponder,
  opts: MockGroomingOptions = {},
): MockGrooming {
  let current = responder;
  let slowMs = opts.slowMs ?? 0;
  let activityMs = opts.activityMs;
  const sessions: MockGroomSession[] = [];
  const created: GroomSessionCreateOptions[] = [];
  const factory: GroomSessionFactory = (o: GroomSessionCreateOptions) => {
    created.push(o);
    // Resolve the responder/slowMs/activityMs lazily so setResponder() /
    // setSlowMs() / setActivityMs() apply to future turns.
    const s = new MockGroomSession(
      o.sessionFile,
      (prompt) => current(prompt),
      o.onUsage,
      () => slowMs,
      () => activityMs,
      o.onActivity,
    );
    sessions.push(s);
    return Promise.resolve(s);
  };
  return {
    factory,
    sessions,
    created,
    setResponder: (fn) => {
      current = fn;
    },
    setSlowMs: (ms) => {
      slowMs = ms;
    },
    setActivityMs: (ms) => {
      activityMs = ms;
    },
  };
}
