# OWASP Top 10 (2021) — code-level detection checklist

Read this when running the A01–A10 checklist (S11 `security-code-review`
Step 1). Per-category: *look for <pattern> in changed code → verify <context
condition> → if still present, raise <severity> with <CWE>*. Patterns and
false-positive (FP) guardrails from R6
(`docs/research/R6-owasp-llm-detection.md`, Findings Q1/Q2 — OWASP Top 10 2021
category pages fetched + verified 2026-11-23).

Contents: A01 · A02 · A03 · A04 · A05 · A06 · A07 · A08 · A09 · A10 ·
cross-cutting FP rules.

## A01 — Broken Access Control

Look for (in changed code):

- **IDOR** — a query/handler takes an identifier from the request and uses it
  without an ownership/tenant predicate (`WHERE id = ?` but no
  `AND owner_id = current_user`). → BLOCKER (CWE-639).
- **New endpoint missing authorization** — a new route/handler with no
  auth decorator/middleware, or added to a file where sibling handlers all
  carry an auth check. → BLOCKER (CWE-862).
- **Force-browsing** — a new privileged page/endpoint with no role guard. →
  BLOCKER (CWE-862).
- **Client-side-only enforcement** — permission logic in JS/template with no
  corresponding server check in the same diff. → BLOCKER (CWE-602).
- **CORS misconfiguration** — `Access-Control-Allow-Origin` echoed from the
  `Origin` header, or `allow_origins=["*"]` with credentials. → BLOCKER
  (CWE-942).
- **JWT/token trust without validation** — reading `payload["role"]` from a
  decoded JWT without signature verification; trusting a cookie/hidden-field
  value as authority. → BLOCKER (CWE-345).
- **Path traversal / open redirect** — `open(request.args["file"])`,
  `os.path.join(root, user_input)` without normalization/containment; redirect
  target taken from input. → BLOCKER (CWE-22/601).

FP guardrail: a query that *includes* a user-supplied ID is fine when an
ownership/tenant predicate is also enforced. A diff that *adds* a server-side
check alongside UI hiding is not a finding.

## A02 — Cryptographic Failures

Look for:

- **Hardcoded keys/credentials** — `API_KEY = "sk-..."`, hardcoded IVs. →
  BLOCKER (CWE-798/321). (Homelab: real keys live in `.env` — never in code.)
- **Deprecated algorithms** — `hashlib.md5`/`sha1`, DES, RC4, PKCS1v15 in a
  new crypto path. → BLOCKER (CWE-327/328).
- **Insecure modes / IV handling** — ECB mode, fixed/zero IV, IV derived from
  a counter. → BLOCKER (CWE-323/329).
- **Insecure password storage** — `hashlib.sha256(password)`, unsalted fast
  hash — vs. the safe shape `bcrypt`/`argon2`. → BLOCKER (CWE-916).
- **Cleartext transport of sensitive data** — `http://` URL built for a
  credentials/token call. → BLOCKER (CWE-319).
- **Missing certificate validation** — `verify=False`,
  `InsecureSkipVerify: true` in a client. → BLOCKER (CWE-296).
- **Hand-rolled crypto / weak randomness** — `random.Random(42)` for tokens,
  `Math.random()` for session IDs, custom cipher code. → BLOCKER (CWE-330/331).

FP guardrail: standard-library crypto used correctly is not a finding (most
modern APIs need no manual CSPRNG seeding — flag hand-rolled seeding, not
`secrets.token_urlsafe()`). Non-crypto hashes (cache keys, dedup) are not
crypto failures — context matters.

## A03 — Injection

The category OWASP says is best caught by source review. Look for:

- **String-concatenated SQL** — `f"SELECT ... WHERE x = {user_input}"`,
  `"... WHERE id = " + req.param`. → BLOCKER (CWE-89).
- **ORM/query-builder concatenation** — the ORM *query string* built by
  concatenation (HQL shape), even though the ORM is parameterizable. →
  BLOCKER (CWE-89).
- **Unsafe stored procedures** — `EXECUTE IMMEDIATE '... ' || input`,
  `exec(@sql)` with concatenated input. → BLOCKER (CWE-89).
- **User-controlled structure names** — `SELECT {column} FROM t` where
  `column` comes from input (sort columns, report fields). → BLOCKER (CWE-89).
- **OS command injection** — `subprocess.run(f"ping {host}", shell=True)`,
  `os.system("... " + input)`, backtick/`$()` interpolation. → BLOCKER
  (CWE-78).
- **Other interpreter injection** — LDAP, EL/OGNL, XPath, SSTI
  (`template.render_string(user_template)`). → BLOCKER (CWE-94/95).
- **Command argument injection** — user-controlled *first* argument to a CLI
  (leading-dash options, `convert user_input.png ...`). → BLOCKER (CWE-88).

FP guardrail: parameterized queries are the safe shape —
`cursor.execute("SELECT … WHERE id = %s", (id,))` is not a finding. Framework
auto-escaping / ORM parameterization is safe *when the framework does the
binding* — but query-string concatenation through an ORM is still vulnerable.

## A04 — Insecure Design

The hardest category — design flaws "cannot be fixed by a perfect
implementation". Flag as **smells (WARNING) pending human confirmation**:

- **Prohibited credential-recovery design** — knowledge-based Q&A in a
  password-reset flow (prohibited by NIST 800-63b / ASVS / Top 10).
- **Business-logic gaps** — new pricing/discount/booking code with no limit
  checks, no rate limiting, no quantity bounds.
- **Client-side enforcement of server-side security** (CWE-602).
- **Trust-boundary violations** — data from an untrusted tier consumed by a
  trusted tier with no validation/normalization at the boundary (CWE-501).
- **Sensitive data in error messages** — `raise Exception(f"query failed for
  user {user}: {sql}")`, stack traces returned to clients (CWE-209).
- **Security through obscurity** — access gated by an undocumented parameter
  or "hidden" field (CWE-656).

FP guardrail: business limits enforced elsewhere (DB constraint, upstream API)
are not missing controls.

## A05 — Security Misconfiguration

Mostly in config/infra files, Dockerfiles, CI. Flag **with context** (dev vs
prod matters):

- **Default credentials** — `MYSQL_ROOT_PASSWORD: root`, shipped defaults. →
  BLOCKER if prod-shaped (CWE-1393).
- **Debug/diagnostic surface** — `DEBUG=true` in prod config, verbose error
  handlers returning stack traces. → BLOCKER/WARNING by environment (CWE-489).
- **Directory listing / backup files in web root** — `Options +Indexes`,
  `.git`/`*.bak` under a served path (CWE-548).
- **Missing security headers** — new server/proxy config with no
  CSP/HSTS/X-Content-Type-Options (CWE-693) — check whether Caddy/the proxy
  layer sets them first.
- **XML external entities** — XML parser with external entity resolution on
  untrusted input (CWE-611).
- **Permissive cloud storage / IAM** — world-readable bucket, wildcard IAM in
  IaC (CWE-732).
- **Unnecessary features enabled** — extra exposed ports, demo endpoints in
  prod config.

FP guardrail: environment-specific config is not a misconfiguration per se —
`DEBUG=true` in a *dev* compose file is context-dependent. Security headers
set at the reverse-proxy/CDN layer are fine.

## A06 — Vulnerable and Outdated Components

- **Detectable in a diff:** a dependency added at a version with a *known*
  CVE (cite the CVE if you are confident — otherwise defer), adding a
  component from an unofficial source, removing a lockfile or version pin,
  unmaintained components (CWE-1104).
- **Must defer to SCA:** the current CVE state of any version. The LLM's
  training-cutoff knowledge is stale by construction — route to
  Dependency-Check / retire.js / NVD monitoring, list under "Deferred to
  tooling". Never be the authority on "is this version vulnerable".

FP guardrail: an old-but-pinned version with no known CVE is not a finding —
pinned (not floating) is *good* practice.

## A07 — Identification and Authentication Failures

Look for:

- **No rate limiting / lockout on auth endpoints** — new login endpoint with
  no throttle (check surrounding infra/WAF before asserting — WARNING if
  infra may provide it) (CWE-307).
- **Default/weak credentials shipped** — seed data with `admin/admin`. →
  BLOCKER (CWE-1393).
- **Weak password storage/compare** — plaintext compare, `==` on hashes. →
  BLOCKER (CWE-256/916).
- **Weak recovery flow** — knowledge-based answers (same as A04).
- **Missing MFA on sensitive paths** — sensitive action (transfer, delete-all)
  with only a password check where the system elsewhere has MFA (CWE-308).
- **Session ID in URL / session reuse** — `?sid=` in links; session id not
  regenerated after credential change (CWE-384/598).
- **Missing session invalidation** — logout clears client state but not the
  server-side session (CWE-613).
- **Account enumeration** — login returning different messages for
  unknown-user vs. bad-password (CWE-204).

FP guardrail: a login endpoint behind a WAF/rate-limiter is not "unlimited".
Flagging "no password complexity requirement" is itself a false positive
(NIST 800-63 discourages complexity rules).

## A08 — Software and Data Integrity Failures

Look for:

- **Deserialization of untrusted data** — `pickle.loads(request.body)`,
  `ObjectInputStream` on external input, `yaml.load` (unsafe loader) on
  untrusted data. → BLOCKER (CWE-502).
- **Untrusted code sources** — `<script src="https://untrusted-cdn/...">`,
  dynamic `require`/`import` of a user-supplied module path, plugin loading
  from arbitrary paths (CWE-829/830).
- **Unsigned/unverified updates or downloads** — `curl -s $URL | sh`,
  auto-update that fetches and applies without signature/hash check (CWE-494).
- **CI/CD pipeline integrity** — workflow that checks out arbitrary refs,
  executes untrusted code from fork PRs, writes secrets to logs (CWE-508).
- **Tamperable state passed to untrusted clients** — a signed state (JWT)
  carrying security decisions but verified only for expiry, not signature
  (CWE-565/784).

FP guardrail: deserializing *trusted, integrity-checked* data (signed payload
verified before `loads`) is not CWE-502. `yaml.safe_load` on untrusted data is
the safe shape.

## A09 — Security Logging and Monitoring Failures

Look for (smells — WARNING, context-dependent):

- **Unlogged auditable events** — new auth/payment/admin handler with no log
  call at success *and* failure paths (CWE-778).
- **Sensitive data in logs** — passwords/tokens/full card numbers in log
  lines (CWE-532).
- **Log injection** — user input interpolated into a log line without
  newline/control-char sanitization (CWE-117).
- **Missing security-relevant context** — `log.error(e)` without
  user/tenant/request context on a security-relevant failure (CWE-223).
- **Swallowed exceptions on security paths** — `except: pass` where a
  security failure should be visible.

FP guardrail: absence of a log call in the diff is not proof of missing
logging — framework/middleware may cover it. Logging to a local file *is* a
finding, but only when the diff is the app's only logging path.

## A10 — Server-Side Request Forgery (SSRF)

Look for:

- **User-controlled URL fetched server-side** — `requests.get(request.args["url"])`,
  `fetch(userUrl)` in a server handler, webhook/image-preview features. →
  BLOCKER (CWE-918).
- **Denylist/regex "validation"** — `if "169.254" not in url: fetch(url)`.
  This is a *finding* (weak control), not a control: "Do not mitigate SSRF via
  the use of a deny list or regular expression."
- **Missing positive allow list** — URL fetch with no allow list of
  scheme/host/port (the required control).
- **Redirect-following** — `allow_redirects=True` on a user-controlled URL.
- **Raw response returned to client** — proxy-style endpoint echoing the
  fetched body.
- **DNS rebinding / TOCTOU** — validate the URL, then fetch the *string*
  again (re-resolve) instead of the resolved IP.
- **Cloud metadata targets** — any of the above where the runtime is
  cloud-hosted (`169.254.169.254` reachable).

FP guardrail: a URL fetch where the URL is *not* user-controlled (fixed
internal service URL) is not SSRF. An allow list of scheme+host+port *is* the
correct control — flag its *absence*, never its presence.

## Cross-cutting FP rules

1. Always read the surrounding function/file context before asserting — a
   check may live one line above or in a decorator/middleware.
2. Distinguish "control absent" from "control present but weak" (the A10
   denylist case is the canonical weak-control case).
3. Never assert a finding the reviewer cannot point at in the diff — no
   verified `file:line` + quoted snippet, no finding.
4. Cross-file taint claims (is this value *actually* user-controlled across
   12 files?) are marked "needs verification", not asserted.
5. Runtime properties (what is actually deployed/patched/alerting) are routed
   to tooling — never asserted from a diff.
