# Security Policy

## Reporting a Vulnerability

If you find a security vulnerability in BACH, please report it responsibly:

1. **Do NOT open a public issue**
2. **Use GitHub's [private vulnerability reporting](https://github.com/ellmos-ai/bach/security/advisories/new)**
3. Include: description, steps to reproduce, potential impact

### How to Report

1. Go to: https://github.com/ellmos-ai/bach/security/advisories/new
2. Fill out the form (title, description, severity, affected versions)
3. Submit privately (not visible to public until disclosed)

We will respond as soon as possible.

## Scope

BACH runs locally. The main attack surface is:
- Bridge/Connector endpoints (Telegram, Discord, etc.)
- GUI web server (FastAPI, localhost only by default)
- File system access (bach.db, user data)
- MCP server (localhost only)

## GUI device authentication

Private API routes require a device token, including requests from localhost
and installations with no registered devices. Browser API requests must come
from the GUI's own origin. Send tokens in an `Authorization: Bearer` header;
query-string tokens are not accepted. Chat-Control keeps its separate credential.

For a new installation, provision the first device locally from the `system/`
directory using the existing library API:

```python
from gui.device_auth import create_device
token = create_device("first-device")
```

Transfer the one-time token privately to `/token-dashboard`. Do not put it in
URLs, source files, logs, or shell history. Further devices can be registered
through the authenticated dashboard. A previously exposed token must be revoked
and replaced; removing it from source does not revoke it.

## Response

As a solo project, response times may vary. Critical issues will be
prioritized. Please allow reasonable time before public disclosure.
