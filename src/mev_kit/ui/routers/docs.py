"""Documentation and guides endpoints."""

from __future__ import annotations

from pathlib import Path

import markdown
from fastapi import APIRouter

router = APIRouter()

GUIDES_DIR = Path(__file__).parent.parent / "guides"


@router.get("/guides")
async def list_guides() -> list[dict[str, str]]:
    if not GUIDES_DIR.exists():
        return []
    guides = []
    for p in sorted(GUIDES_DIR.glob("*.md")):
        first_line = p.read_text().split("\n")[0].lstrip("# ").strip()
        title = first_line if first_line else p.stem.split("-", 1)[-1].replace("-", " ").title()
        guides.append({"slug": p.stem, "title": title})
    return guides


@router.get("/guides/{slug}")
async def get_guide(slug: str) -> dict[str, str]:
    path = GUIDES_DIR / f"{slug}.md"
    if not path.exists():
        return {"error": f"Guide not found: {slug}"}
    raw = path.read_text()
    html = markdown.markdown(raw, extensions=["fenced_code", "tables", "codehilite"])
    return {"slug": slug, "markdown": raw, "html": html}
