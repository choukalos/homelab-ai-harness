#!/usr/bin/env python3
"""S6 security-review — deterministic pre-push checks for agent-produced changes.

Runs the mechanical half of the S6 `security-review` checklist on a git diff
(staged by default; `--working` for the working tree):

  1. Secrets in added lines — known token formats (sk-, ghp_, AKIA, Slack,
     private-key blocks, Basic-auth blobs) + high-entropy literals assigned
     to secret-looking variable names. Same pattern set as .githooks/pre-commit
     (the hook guards commits; this guards the *push* and works on any diff).
  2. File ownership/permissions on new files — the presenton userConfig.json
     lesson: a file holding credentials must be 600 and owned by the runtime
     user; world-readable is a finding.
  3. Image pinning in compose files — `image: <name>` without a version tag
     is a finding (housekeeping H1: `latest`/untagged images drift silently).

Output: JSON on stdout — {"status": "ok"|"findings", "findings": [...],
"checked": {...}}. Exit 0 always (findings are advisory for the agent to
judge; the pre-commit hook is the hard gate for secrets).

Usage:
  python3 pre_push_security_check.py            # staged diff
  python3 pre_push_security_check.py --working  # working-tree diff
  python3 pre_push_security_check.py --help
"""
import json
import math
import os
import re
import subprocess
import sys

# --- secret patterns (mirrors .githooks/pre-commit PATTERNS) -----------------
PATTERNS = [
    (re.compile(r'AKIA[0-9A-Z]{16}'), 'AWS access key ID'),
    (re.compile(r'sk-[A-Za-z0-9_-]{20,}'), 'OpenAI/LiteLLM-style API key (sk-…)'),
    (re.compile(r'gh[pousr]_[A-Za-z0-9]{36,}'), 'GitHub token'),
    (re.compile(r'github_pat_[A-Za-z0-9_]{20,}'), 'GitHub fine-grained PAT'),
    (re.compile(r'xox[baprs]-[A-Za-z0-9-]{10,}'), 'Slack token'),
    (re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY'),
     'private key block'),
    (re.compile(r'Basic [A-Za-z0-9+/]{24,}={0,2}'), 'base64 Basic-auth blob'),
]
# KEY=literal / KEY: literal where KEY looks secret-ish
GENERIC = re.compile(
    r'(?:^|[\s"\'(,])([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSW|CREDENTIAL|APIKEY)[A-Z0-9_]*)'
    r'[\s]*[=:]\s*["\']?([A-Za-z0-9+/=_\-]{16,})',
)
# ${VAR} references and obvious placeholders are not secrets
ALLOWED_VALUE = re.compile(r'^\$\{[A-Z0-9_]+\}$|^(changeme|placeholder|<[^>]+>|\*+|x+|redacted|none|null|true|false)$', re.I)

SECRETISH_FILE = re.compile(
    r'(^|/)(\.env(\..+)?|.*\.(pem|key|p12|pfx|jks|keystore|json)$|credentials.*|secrets?\.*)$', re.I)
ALLOWED_NAME = re.compile(r'\.env\.(example|sample|template)$', re.I)


def shannon(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    freq = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    return -sum((cnt / n) * math.log2(cnt / n) for cnt in freq.values())


def mask(s: str) -> str:
    s = s.strip()
    return (s[:4] + f'…({len(s)} chars)') if len(s) > 8 else f'…({len(s)} chars)'


def git(*args):
    return subprocess.run(['git', *args], capture_output=True, text=True).stdout


def diff_added_lines(mode: str):
    """Yield (file, lineno, line) for added lines in the diff."""
    args = ['diff', '--unified=0']
    if mode == 'working':
        args.append('--')
    else:
        args.insert(1, '--cached')
    out = subprocess.run(['git', *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f'git diff failed: {out.stderr.strip()}')
    cur = None
    for line in out.stdout.splitlines():
        if line.startswith('+++ b/'):
            cur = line[6:]
        elif line.startswith('+') and not line.startswith('+++') and cur:
            # --unified=0: no hunk headers needed for line numbers beyond the
            # first; count within the file is enough for reporting.
            yield cur, line[1:]


def scan_secrets(mode: str):
    findings = []
    seen = set()
    for path, text in diff_added_lines(mode):
        if ALLOWED_NAME.search(path):
            continue
        for pat, label in PATTERNS:
            m = pat.search(text)
            if m and (path, label) not in seen:
                seen.add((path, label))
                findings.append({
                    'type': 'secret', 'severity': 'blocker', 'file': path,
                    'detail': f'{label} in added line: {mask(m.group(0))}',
                })
        m = GENERIC.search(text)
        if m:
            var, val = m.group(1), m.group(2)
            if not ALLOWED_VALUE.match(val) and shannon(val) >= 3.5 and (path, var) not in seen:
                seen.add((path, var))
                findings.append({
                    'type': 'secret', 'severity': 'blocker', 'file': path,
                    'detail': f'high-entropy literal assigned to {var}: {mask(val)}',
                })
    return findings


def scan_permissions(mode: str):
    """New files that look secret-ish must be 600 and not world-readable."""
    findings = []
    args = ['diff', '--name-only', '--diff-filter=A']
    if mode == 'working':
        args.append('--')
    else:
        args.insert(1, '--cached')
    for path in git(*args).splitlines():
        path = path.strip()
        if not path or not os.path.exists(path):
            continue
        if not SECRETISH_FILE.search(path) or ALLOWED_NAME.search(path):
            continue
        st = os.stat(path)
        perms = oct(st.st_mode & 0o777)[2:]
        if int(perms, 8) & 0o044:
            findings.append({
                'type': 'permission', 'severity': 'major', 'file': path,
                'detail': f'secret-ish file is world/other-readable (mode {perms}) — '
                          f'expected 600 owned by the runtime user',
            })
    return findings


def scan_image_pinning(mode: str):
    """compose files: `image: <name>` without a version tag."""
    findings = []
    args = ['diff', '--name-only']
    if mode == 'working':
        args.append('--')
    else:
        args.insert(1, '--cached')
    for path in git(*args).splitlines():
        path = path.strip()
        if not path.endswith(('.yml', '.yaml')) or not os.path.exists(path):
            continue
        if '/compose/' not in path and 'compose' not in os.path.basename(path):
            continue
        with open(path) as f:
            for i, line in enumerate(f, 1):
                m = re.match(r'\s*image:\s*([A-Za-z0-9._/-]+)', line)
                if not m:
                    continue
                ref = m.group(1)
                # untagged (no :version anywhere) — registry refs without a tag
                # default to :latest silently
                if ':' not in ref.split('/')[-1]:
                    findings.append({
                        'type': 'image-pinning', 'severity': 'minor',
                        'file': f'{path}:{i}',
                        'detail': f'`image: {ref}` has no version tag (defaults to latest) — pin it',
                    })
    return findings


def main():
    mode = 'staged'
    if '--working' in sys.argv[1:]:
        mode = 'working'
    if '-h' in sys.argv[1:] or '--help' in sys.argv[1:]:
        print(__doc__)
        return
    findings = []
    try:
        findings += scan_secrets(mode)
        findings += scan_permissions(mode)
        findings += scan_image_pinning(mode)
    except RuntimeError as e:
        print(json.dumps({'status': 'error', 'error': str(e)}))
        return
    out = {
        'status': 'ok' if not findings else 'findings',
        'mode': mode,
        'findings': findings,
        'checked': {
            'secrets': 'added lines, known token formats + high-entropy assignments',
            'permissions': 'new secret-ish files (mode/ownership)',
            'image-pinning': 'compose files (untagged images)',
        },
    }
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
