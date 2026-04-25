from __future__ import annotations

import datetime as dt
import html
import shutil
import subprocess
import textwrap
from pathlib import Path


def wrap_text(text: str, width: int, max_lines: int = 6):
    return textwrap.wrap(" ".join(text.split()), width=width)[:max_lines]


def render_svg(thought: dict, svg_path: Path) -> None:
    width,height=1200,850; path=thought["path"][:6]; esc=html.escape; y0,x0,gap=220,120,170
    colors={"project":"#60a5fa","person":"#f472b6","finance":"#34d399","event":"#fbbf24","observation":"#fb7185","date":"#a78bfa","wikilink":"#c084fc","note":"#22d3ee"}
    parts=[f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<defs><filter id="shadow"><feDropShadow dx="0" dy="8" stdDeviation="10" flood-color="#000" flood-opacity="0.35"/></filter><marker id="arrow" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#64748b"/></marker></defs>
<rect width="100%" height="100%" fill="#070b14"/>
<rect x="40" y="40" width="1120" height="770" rx="36" fill="#101827" stroke="#243044" filter="url(#shadow)"/>
<text x="90" y="110" fill="#94a3b8" font-family="Inter,Arial,sans-serif" font-size="28">MNEME / AGENT MEMORY PATH</text>
<text x="90" y="165" fill="#f8fafc" font-family="Inter,Arial,sans-serif" font-size="48" font-weight="700">{esc(thought['title'])}</text>''']
    for i,node in enumerate(path):
        x=x0+i*gap; color=colors.get(node.get("type"),"#94a3b8")
        if i>0: parts.append(f'<path d="M {x-95} {y0} C {x-65} {y0-20}, {x-45} {y0-20}, {x-25} {y0}" stroke="#64748b" stroke-width="4" fill="none" marker-end="url(#arrow)"/>')
        parts.append(f'<circle cx="{x}" cy="{y0}" r="44" fill="{color}" opacity="0.95"/>')
        parts.append(f'<text x="{x}" y="{y0+8}" text-anchor="middle" fill="#07111f" font-family="Inter,Arial" font-size="24" font-weight="800">{i+1}</text>')
        for j,line in enumerate(wrap_text(node.get("name","?"),16,3)): parts.append(f'<text x="{x}" y="{y0+75+j*24}" text-anchor="middle" fill="#e2e8f0" font-family="Inter,Arial" font-size="20">{esc(line)}</text>')
        parts.append(f'<text x="{x}" y="{y0+155}" text-anchor="middle" fill="#64748b" font-family="Inter,Arial" font-size="17">{esc(node.get("type","node"))}</text>')
    parts.append('<rect x="90" y="500" width="1020" height="120" rx="22" fill="#0f2537" stroke="#1e3a5f"/>')
    parts.append('<text x="120" y="545" fill="#38bdf8" font-family="Inter,Arial" font-size="24" font-weight="700">Insight</text>')
    for j,line in enumerate(wrap_text(thought["insight"],82,3)): parts.append(f'<text x="120" y="{580+j*30}" fill="#e5e7eb" font-family="Inter,Arial" font-size="25">{esc(line)}</text>')
    parts.append('<rect x="90" y="650" width="1020" height="105" rx="22" fill="#1f1b10" stroke="#5b4315"/>')
    parts.append('<text x="120" y="692" fill="#fbbf24" font-family="Inter,Arial" font-size="24" font-weight="700">Possible next move</text>')
    for j,line in enumerate(wrap_text(thought["action"],88,2)): parts.append(f'<text x="120" y="{728+j*28}" fill="#fef3c7" font-family="Inter,Arial" font-size="23">{esc(line)}</text>')
    generated=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    parts.append(f'<text x="90" y="790" fill="#475569" font-family="Inter,Arial" font-size="18">Generated {esc(generated)} from a local Markdown-derived SQLite graph.</text>')
    parts.append('</svg>'); svg_path.parent.mkdir(parents=True, exist_ok=True); svg_path.write_text("\n".join(parts), encoding="utf-8")


def render_card(thought: dict, out_dir: Path, basename: str | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True); stamp=basename or dt.datetime.now().strftime("%Y%m%d_%H%M%S"); svg_path=out_dir/f"thought_{stamp}.svg"; png_path=out_dir/f"thought_{stamp}.png"
    render_svg(thought, svg_path); convert=shutil.which("convert") or shutil.which("magick")
    if convert:
        subprocess.run([convert,str(svg_path),str(png_path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30); return png_path
    return svg_path
