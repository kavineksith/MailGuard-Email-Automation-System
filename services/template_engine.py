"""
services.template_engine
==========================
Minimal, dependency-free ``{{variable}}`` template renderer with basic
HTML-escaping of injected context values to reduce stored-XSS risk in
generated emails.
"""

from __future__ import annotations

import asyncio
import re
from html import escape
from pathlib import Path
from typing import Any, Dict, Optional

from core.exceptions import TemplateNotFoundError, TemplateRenderError
from core.logger import get_logger

logger = get_logger()

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


class TemplateEngine:
    """Loads templates from disk and renders them with a context dict."""

    def __init__(self, template_dir: str = "templates") -> None:
        self.template_dir = Path(template_dir)
        self.template_dir.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:
        return f"TemplateEngine(template_dir={self.template_dir!s})"

    @staticmethod
    def _sanitize(value: Any) -> str:
        return escape(str(value))

    def _render_sync(self, template_name: str, context: Optional[Dict[str, Any]]) -> str:
        path = self.template_dir / template_name
        if not path.is_file():
            raise TemplateNotFoundError(
                f"Template not found: {template_name}", context={"template": template_name}
            )
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TemplateRenderError(
                f"Failed to read template: {template_name}", cause=exc,
                context={"template": template_name},
            ) from exc

        context = context or {}

        def _substitute(match: "re.Match[str]") -> str:
            key = match.group(1)
            if key not in context:
                return match.group(0)
            return self._sanitize(context[key])

        return _PLACEHOLDER.sub(_substitute, content)

    async def render(self, template_name: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Render a template off the event loop thread."""
        return await asyncio.to_thread(self._render_sync, template_name, context)
