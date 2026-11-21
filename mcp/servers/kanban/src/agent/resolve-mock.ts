/**
 * Mocked Pi resolution session for tests (Slice 3c) — no network, no model.
 *
 * File-backed like the grooming mock: transcripts persist to the stable
 * session file path (JSON), so resume-after-restart (SessionManager.open
 * semantics) is exercised the same way the real SessionManager would behave.
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import { mockAssistantMsg, mockUserMsg } from "./grooming-mock.js";
import type { UsageSample } from "./sessions.js";
import type {
  ResolveSessionCreateOptions,
  ResolveSessionFactory,
  ResolveSessionLike,
} from "./resolve.js";

export type ResolveResponder = (prompt: string) => string;

/**
 * Default mock responder: chat turns echo the prompt; the FINALIZE prompt
 * returns a plain-text resolution plan. Tests override for specific cases.
 */
export function defaultResolveResponder(prompt: string): string {
  if (prompt.startsWith("ACCEPTED.")) {
    return "1) what went wrong: the deploy push failed on auth.\n2) steps: fix the token, re-run the deploy step.\n3) verify: the branch is pushed and the task is done.";
  }
  return `mock resolution reply to: ${prompt.slice(0, 40)}`;
}

export class MockResolveSession implements ResolveSessionLike {
  readonly prompts: string[] = [];
  disposed = false;
  private _messages: AgentMessage[];

  constructor(
    readonly sessionFile: string,
    private readonly responder: ResolveResponder,
    private onUsage?: (u: UsageSample) => void,
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
    const reply = this.responder(text);
    this._messages.push(mockAssistantMsg(reply));
    // Persist (the real session file is JSONL; the mock stores JSON).
    writeFileSync(this.sessionFile, JSON.stringify(this._messages));
    this.onUsage?.({
      role: "resolve",
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
}

export interface MockResolution {
  factory: ResolveSessionFactory;
  sessions: MockResolveSession[];
  /** Factory options of each session creation (in order). */
  created: ResolveSessionCreateOptions[];
  setResponder(fn: ResolveResponder): void;
}

export function createMockResolution(responder: ResolveResponder = defaultResolveResponder): MockResolution {
  let current = responder;
  const sessions: MockResolveSession[] = [];
  const created: ResolveSessionCreateOptions[] = [];
  const factory: ResolveSessionFactory = (opts: ResolveSessionCreateOptions) => {
    created.push(opts);
    // Resolve the responder lazily so setResponder() applies to future turns.
    const s = new MockResolveSession(opts.sessionFile, (prompt) => current(prompt), opts.onUsage);
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
  };
}
