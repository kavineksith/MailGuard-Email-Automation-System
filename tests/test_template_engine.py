import pytest

from core.exceptions import TemplateNotFoundError
from services.template_engine import TemplateEngine


@pytest.mark.asyncio
async def test_render_substitutes_context(tmp_path):
    (tmp_path / "welcome.html").write_text("Hello {{name}}, you have {{count}} messages.")
    engine = TemplateEngine(str(tmp_path))
    rendered = await engine.render("welcome.html", {"name": "Kavin", "count": 5})
    assert rendered == "Hello Kavin, you have 5 messages."


@pytest.mark.asyncio
async def test_render_escapes_html_in_context(tmp_path):
    (tmp_path / "t.html").write_text("Hi {{name}}")
    engine = TemplateEngine(str(tmp_path))
    rendered = await engine.render("t.html", {"name": "<script>alert(1)</script>"})
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


@pytest.mark.asyncio
async def test_render_missing_template_raises(tmp_path):
    engine = TemplateEngine(str(tmp_path))
    with pytest.raises(TemplateNotFoundError):
        await engine.render("nope.html", {})


@pytest.mark.asyncio
async def test_render_leaves_unknown_placeholder_untouched(tmp_path):
    (tmp_path / "t.html").write_text("Hello {{unknown}}")
    engine = TemplateEngine(str(tmp_path))
    rendered = await engine.render("t.html", {})
    assert rendered == "Hello {{unknown}}"
