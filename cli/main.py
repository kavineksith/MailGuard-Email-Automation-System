"""
cli.main
==========
Dual-mode command line interface for MailGuard.

* ``mailguard send ...``       - scripted/automation mode (argparse)
* ``mailguard interactive``    - REPL with readline history
* ``mailguard init-config``    - create a new encrypted configuration
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from typing import List, Optional

try:
    import readline  # noqa: F401  (enables arrow-key history on POSIX)
except ImportError:  # pragma: no cover - not available on some platforms
    pass

from core.config import ConfigManager
from core.exceptions import MailGuardError
from core.logger import get_logger, log_exception
from models.message import EmailMessage
from services.scheduler import EmailScheduler
from services.sender import EmailSender

logger = get_logger()


def _split_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


async def cmd_init_config(args: argparse.Namespace) -> int:
    manager = ConfigManager(args.config_path, args.salt_path)
    passphrase = os.getenv("MAILGUARD_PASSPHRASE") or getpass.getpass("Set MAILGUARD_PASSPHRASE: ")
    os.environ["MAILGUARD_PASSPHRASE"] = passphrase

    data = {
        "smtp_server": input("SMTP server: ").strip(),
        "smtp_port": int(input("SMTP port [587]: ").strip() or "587"),
        "smtp_username": input("SMTP username: ").strip(),
        "smtp_password": getpass.getpass("SMTP password: "),
        "default_sender": input("Default sender address: ").strip(),
        "smtp_ssl": input("Use implicit SSL? (y/N): ").strip().lower() == "y",
    }
    await manager.save(data)
    print(f"Encrypted configuration written to {manager.config_path}")
    return 0


async def cmd_send(args: argparse.Namespace) -> int:
    manager = ConfigManager(args.config_path, args.salt_path)
    sender = EmailSender(manager)
    await sender.initialize()

    message = EmailMessage(
        subject=args.subject,
        body=args.body or "",
        recipients=_split_list(args.to),
        sender=args.sender or sender.config_manager.config.default_sender,
        cc=_split_list(args.cc),
        bcc=_split_list(args.bcc),
        attachments=args.attachment or [],
        template_name=args.template,
        template_context=json.loads(args.template_context) if args.template_context else {},
        is_html=args.html,
    )

    if args.schedule:
        scheduler = EmailScheduler(sender)
        job_id = await scheduler.schedule(message, args.schedule)
        print(f"Scheduled job {job_id} for {args.schedule}")
        await scheduler.wait_all()
        return 0

    await sender.send(message)
    print(f"Message {message.message_id} sent successfully.")
    return 0


async def _interactive() -> int:
    print("MailGuard interactive mode. Type 'help' for commands, 'quit' to exit.\n")
    config_path = input("Config path [config.json.enc]: ").strip() or "config.json.enc"
    salt_path = input("Salt path [config.salt]: ").strip() or "config.salt"
    manager = ConfigManager(config_path, salt_path)
    sender = EmailSender(manager)
    await sender.initialize()
    scheduler = EmailScheduler(sender)

    while True:
        try:
            command = input("mailguard> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if command in ("quit", "exit"):
            await scheduler.wait_all()
            break
        elif command == "help":
            print("Commands: send, schedule, status, quit")
        elif command == "send":
            await _interactive_send(sender)
        elif command == "schedule":
            await _interactive_schedule(sender, scheduler)
        elif command == "status":
            print(f"Pending scheduled jobs: {len(scheduler)}")
        elif command:
            print("Unknown command. Type 'help' for a list of commands.")
    return 0


async def _interactive_send(sender: EmailSender) -> None:
    message = EmailMessage(
        subject=input("Subject: ").strip(),
        body=input("Body: ").strip(),
        recipients=_split_list(input("Recipients (comma separated): ")),
        sender=input(f"Sender [{sender.config_manager.config.default_sender}]: ").strip()
        or sender.config_manager.config.default_sender,
    )
    try:
        await sender.send(message)
        print("Sent successfully.")
    except MailGuardError as exc:
        log_exception(logger, exc)
        print(f"Failed: {exc}")


async def _interactive_schedule(sender: EmailSender, scheduler: EmailScheduler) -> None:
    message = EmailMessage(
        subject=input("Subject: ").strip(),
        body=input("Body: ").strip(),
        recipients=_split_list(input("Recipients (comma separated): ")),
        sender=input(f"Sender [{sender.config_manager.config.default_sender}]: ").strip()
        or sender.config_manager.config.default_sender,
    )
    schedule_time = input("Schedule time (HH:MM, 24h): ").strip()
    try:
        job_id = await scheduler.schedule(message, schedule_time)
        print(f"Scheduled as job {job_id}.")
    except MailGuardError as exc:
        log_exception(logger, exc)
        print(f"Failed: {exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mailguard", description="Secure async email sending CLI")
    parser.add_argument("--config-path", default="config.json.enc", dest="config_path")
    parser.add_argument("--salt-path", default="config.salt", dest="salt_path")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-config", help="Create a new encrypted configuration").set_defaults(func=cmd_init_config)
    sub.add_parser("interactive", help="Launch the interactive REPL").set_defaults(
        func=lambda args: _interactive()
    )

    send_parser = sub.add_parser("send", help="Send or schedule an email")
    send_parser.add_argument("--to", required=True, help="Comma-separated recipients")
    send_parser.add_argument("--subject", required=True)
    send_parser.add_argument("--body", default="")
    send_parser.add_argument("--sender")
    send_parser.add_argument("--cc")
    send_parser.add_argument("--bcc")
    send_parser.add_argument("--attachment", action="append")
    send_parser.add_argument("--template")
    send_parser.add_argument("--template-context", help="JSON object of template variables")
    send_parser.add_argument("--html", action="store_true")
    send_parser.add_argument("--schedule", help="HH:MM 24-hour time to send at")
    send_parser.set_defaults(func=cmd_send)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(args.func(args))
    except MailGuardError as exc:
        log_exception(logger, exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
