# Security Policy

## Supported versions

ORBIT AI is pre-alpha. Only the latest `main` is supported; no security backports are provided
for older commits.

## Reporting a vulnerability

**Do not open a public issue for security problems.**

Report privately through GitHub Security Advisories
(<https://github.com/allandcnarciso/orbit-ai/security/advisories/new>) or by contacting the
maintainer listed on the repository profile. Include:

- affected version/commit,
- reproduction steps or proof of concept,
- impact assessment (data exposure, privilege escalation, RCE, …),
- any suggested fix.

You will receive an acknowledgement within 72 hours. Please allow reasonable time for a fix
before public disclosure.

## Security model (current)

- The server binds to `127.0.0.1` by default and must not be exposed publicly; there is no
  authentication layer yet.
- All model, web and tool content is treated as untrusted input.
- Credentials are read from environment variables or `.env` (git-ignored) and held as
  `SecretStr`; log output is redacted. OS keyring storage is planned.
- Shell execution, arbitrary code execution and unrestricted filesystem access are disabled by
  default; tools will require explicit permission grants and, for protected actions, human
  approval.
- Installed skills are untrusted code/instructions and require explicit activation.

## Out of scope (for now)

- Vulnerabilities requiring an already-compromised host or root access.
- Issues in third-party providers (OpenRouter, Ollama) themselves.
- Denial of service from deliberately huge local inputs in a single-user installation.

## Handling secrets

If you accidentally commit a credential: revoke it immediately at the provider, then report it
privately so history can be cleaned up. Never paste keys into issues, pull requests or logs.
