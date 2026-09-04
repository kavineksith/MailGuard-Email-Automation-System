# MailGuard

**A secure, async, CLI-based email sending system with encrypted configuration, structured audit logging, and bounded-concurrency bulk delivery.**

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-63%20passing-brightgreen)

---

## 1. Problem Statement

Sending email programmatically from a script or internal tool routinely runs into the same set of security and reliability failures:

- Credentials sit in plaintext config files or environment dumps.
- Recipient/sender addresses are trusted without validation, opening the door to header injection and malformed-address bounces.
- Attachments are attached blindly, risking oversized payloads, disallowed file types, or client-side auto-execution.
- A single slow SMTP handshake blocks an entire batch send.
- Failures are swallowed by a bare `except Exception` with a one-line log message, leaving no audit trail for "who sent what, when, and why it failed."
- Scheduled/recurring sends rely on a busy-loop (`while True: sleep(1)`) that wastes a full thread and has no cancellation story.

MailGuard addresses each of these directly:

| Problem | MailGuard's approach |
|---|---|
| Plaintext credentials | Config is encrypted at rest with Fernet, keyed by a PBKDF2-HMAC-SHA256 derivation (100k iterations, random per-install salt) of a passphrase that is **never** stored on disk |
| Untrusted addresses | Every address is validated (RFC-5322 pattern + suspicious-pattern heuristics) before a connection is ever opened |
| Unsafe attachments | Size limit (25MB), MIME allow-list, and anti-execution MIME headers (`X-Content-Type-Options`, `X-Download-Options`) enforced before any file is read |
| Blocking sends | Fully `async`/`await`; SMTP transport uses `aiosmtplib` when available and falls back to a thread-offloaded `smtplib` otherwise, so the event loop is never blocked either way |
| No audit trail | Every event and every raised exception is logged as a structured JSON-lines record (code, severity, timestamp, context) via a non-blocking `QueueHandler`/`QueueListener` pipeline |
| Wasteful scheduling loop | `asyncio.create_task` + `asyncio.sleep(delay)` per job — no polling, and every job is cleanly cancellable |

## 2. Architecture

```
mailguard/
├── core/
│   ├── exceptions.py     # 25+ exception classes, MG-xxxx error codes, severity, context
│   ├── logger.py         # Non-blocking dual-sink logging (console + JSON audit file)
│   └── config.py         # Encrypted configuration load/save (async wrappers)
├── models/
│   └── message.py        # EmailMessage value object, full dunder-method suite
├── validators/
│   └── email_validator.py  # RFC-5322 + heuristic validation, async batch generator
├── services/
│   ├── attachment_handler.py  # Size/type validation, MIME part construction
│   ├── template_engine.py     # {{var}} templating with HTML-escaping
│   ├── smtp_client.py         # Async SMTP transport (aiosmtplib or threaded smtplib)
│   ├── sender.py               # Orchestrator: validate -> render -> attach -> send
│   └── scheduler.py            # Per-job asyncio.Task scheduling, cancellable
├── cli/
│   └── main.py            # argparse subcommands + interactive REPL
├── tests/                  # 63 pytest cases across every layer
├── templates/               # Sample HTML templates
├── setup.py / setup.cfg / requirements.txt
└── run.sh                    # venv bootstrap + launcher
```

**Design principles applied throughout:**

- **Layered separation** — `core` has no knowledge of `services`; `services` has no knowledge of `cli`.
- **Exception hierarchy** — every failure is a typed `MailGuardError` subclass carrying an `MG-xxxx` code, a `Severity`, a UTC timestamp, and a context dict; nothing is caught and re-raised as a bare string.
- **Concurrency control** — bulk sends are bounded by `asyncio.Semaphore(max_concurrent_sends)` and driven with `asyncio.gather`, so throughput scales without overwhelming the SMTP server.
- **Single-writer logging** — a single `QueueListener` thread owns both the console and audit-file handlers, avoiding interleaved/corrupted log lines under concurrent async sends.
- **Dunder completeness** — `EmailMessage` implements `__iter__`, `__len__`, `__contains__`, `__getitem__`, `__bool__`, `__eq__`, `__hash__`, `__lt__`, `__repr__`, `__str__`, and pickle support (`__getstate__`/`__setstate__`), so it behaves correctly in sets, sorted lists, and logging output.

## 3. Installation

**Prerequisites:** Python 3.11+, bash, pip.

```bash
git clone <this-repository>
cd mailguard
chmod +x run.sh
./run.sh --help
```

`run.sh` will automatically:
1. Locate a Python 3.11+ interpreter.
2. Create `.venv/` if it doesn't already exist.
3. Install/upgrade `requirements.txt` and the package itself (editable install).
4. Launch the CLI, forwarding whatever arguments you passed.

You can also install manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## 4. Configuration

MailGuard never stores SMTP credentials in plaintext. Create your encrypted configuration interactively:

```bash
export MAILGUARD_PASSPHRASE="choose-a-strong-passphrase"
./run.sh init-config
```

You'll be prompted for the SMTP server, port, username, password, and default sender. This produces two files:

- `config.json.enc` — the Fernet-encrypted configuration (mode `0600`).
- `config.salt` — the random PBKDF2 salt used to derive the encryption key (mode `0600`).

**`MAILGUARD_PASSPHRASE` must be set in the environment for every subsequent run** — it is never written to disk. Losing it means losing access to the encrypted config; you will need to run `init-config` again.

## 5. Usage

### Send immediately

```bash
export MAILGUARD_PASSPHRASE="choose-a-strong-passphrase"
./run.sh send \
  --to "alice@example.com,bob@example.com" \
  --subject "Deployment complete" \
  --body "The nightly deployment finished successfully." \
  --attachment ./release_notes.pdf
```

### Send with an HTML template

```bash
./run.sh send \
  --to "alice@example.com" \
  --subject "Welcome" \
  --template welcome.html \
  --template-context '{"name": "Alice", "message": "Your account is ready."}'
```

### Schedule a send

```bash
./run.sh send \
  --to "team@example.com" \
  --subject "Standup reminder" \
  --body "Standup starts in 15 minutes." \
  --schedule "09:45"
```

The process stays alive until the scheduled job fires (or is interrupted with `Ctrl+C`), then exits.

### Interactive REPL

```bash
./run.sh interactive
```

Guides you through configuration selection, then accepts `send`, `schedule`, `status`, and `quit` commands with readline history support.

### Using MailGuard as a library

```python
import asyncio
from core.config import ConfigManager
from models.message import EmailMessage
from services.sender import EmailSender

async def main():
    sender = EmailSender(ConfigManager("config.json.enc", "config.salt"))
    await sender.initialize()
    message = EmailMessage(
        subject="Hello",
        body="This is a test.",
        recipients=["someone@example.com"],
        sender=sender.config_manager.config.default_sender,
    )
    await sender.send(message)

asyncio.run(main())
```

## 6. Running Tests

```bash
source .venv/bin/activate
pytest -v
```

The suite covers exceptions, validators, the `EmailMessage` model (including dunder methods and pickle round-tripping), attachment handling, the template engine, the config encryption/decryption round trip, the scheduler's job lifecycle, and the sender's orchestration logic against a mocked SMTP transport — 63 tests, all passing.

## 7. Logging & Accountability

Every run writes to two sinks:

- **Console** — ANSI-colored, human-readable, level-tagged lines.
- **`logs/mailguard_audit.jsonl`** — one JSON object per event (rotating, 5MB x 5 backups), including error codes, severities, and structured context for every exception raised. This file is intended to be shipped to a SIEM or reviewed directly for accountability during an incident.

## 8. Troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| `MG-1104 MissingPassphraseError` | `MAILGUARD_PASSPHRASE` not exported | `export MAILGUARD_PASSPHRASE=...` before running any command |
| `MG-1102 ConfigDecryptionError` | Wrong passphrase, or `config.salt` doesn't match `config.json.enc` | Re-run `init-config` with the correct passphrase; don't mix config/salt pairs from different installs |
| `MG-1101 ConfigNotFoundError` | No configuration created yet | Run `./run.sh init-config` first |
| `MG-1501 SMTPAuthenticationError` | Wrong SMTP username/password, or the provider requires an app-specific password | Verify credentials; for Gmail/Outlook, generate an app password rather than using the account password |
| `MG-1500 SMTPConnectionError` | Firewall, wrong port, or `smtp_ssl` mismatch | Confirm port 465 (implicit SSL) vs 587 (STARTTLS) matches your `smtp_ssl` setting |
| `MG-1201 InvalidEmailError` | Address failed RFC-5322 pattern matching | Double-check for typos, stray whitespace, or missing domain |
| `MG-1302 AttachmentTooLargeError` | File exceeds 25MB | Compress the file or use a file-sharing link instead |
| `MG-1303 UnsupportedAttachmentTypeError` | Extension not in the allow-list | See `services/attachment_handler.py::ALLOWED_MIME_TYPES`; add the extension there if it's genuinely safe for your use case |
| Scheduled job never fires | Process was terminated before the scheduled time | The scheduler only runs while the process is alive; use `cron` + `send` for jobs that must survive a restart |
| No color in console logs | Output is being redirected/piped | Expected — ANSI codes are only emitted when stderr is a TTY |

## 9. Security Notes

- TLS 1.2+ is enforced for every SMTP connection; certificate verification is never disabled.
- The encryption passphrase is read exclusively from the environment, never from a CLI argument (which could leak into shell history or `ps` output).
- Config and salt files are written with `0600` permissions.
- Template context values are HTML-escaped before substitution to reduce stored-XSS risk in rendered emails.
- This tool sends real email through a real SMTP account. Misuse for unsolicited bulk email (spam) is both a violation of most SMTP providers' terms of service and, in many jurisdictions, illegal (e.g., CAN-SPAM, GDPR/PECR). Use only for legitimate, consented communication.

## 10. Disclaimer

This software is provided **"as is"**, without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement. This is a personal portfolio project intended to demonstrate secure software engineering practices; it has not undergone formal third-party security review or penetration testing.

The author is not responsible for:
- Misuse of this software, including unsolicited bulk email or violation of a mail provider's terms of service.
- Email delivery failures occurring beyond the SMTP handoff (e.g., spam filtering, greylisting, provider-side rejection).
- Security incidents resulting from improper configuration, passphrase mismanagement, or deployment in an untrusted environment.
- Any legal consequences arising from the content of emails sent using this system.

Users are solely responsible for correct SMTP configuration, compliance with all applicable laws and regulations (including anti-spam and data-protection law), and the security of their encryption passphrase and credentials.

## License

MIT License — see [LICENSE](LICENSE).
