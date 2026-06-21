#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Схема воркфлоу генерации отклика findwork: ссылка на вакансию → резюме+письмо (PDF/DOCX).

Рисует РЕАЛЬНЫЙ поток из кода: bot._handle_assist → webvac.fetch_vacancy →
career_agent.prepare_application (Стратег → Критик → QA/verify) → resume_doc.render_both.
Выход: docs/workflow.svg (+ PNG, если есть cairosvg).
"""
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1240, 1480
DOCS = Path(__file__).resolve().parent.parent / "docs"
OUT = DOCS / "workflow.svg"

GREEN = ("#d4edda", "#28a745")
AMBER = ("#fff3cd", "#e0a800")
BLUE = ("#cfe2ff", "#0d6efd")
PURPLE = ("#ede7ff", "#6f42c1")
WHITE = ("#ffffff", "#9aa5b1")
BAND = ("#eef2f7", "#cbd5e1")
RED = ("#fde2e1", "#dc3545")

parts: list[str] = []


def rect(x, y, w, h, fill, stroke, rx=12, sw=2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')


def text(x, y, s, size=14, weight="normal", fill="#1f2937", anchor="middle"):
    parts.append(f'<text x="{x}" y="{y}" font-family="Segoe UI, Arial, sans-serif" '
                 f'font-size="{size}" font-weight="{weight}" fill="{fill}" '
                 f'text-anchor="{anchor}">{escape(s)}</text>')


def box(x, y, w, h, lines, palette=WHITE, size=14, weight="700", lead=6, sw=2):
    fill, stroke = palette
    rect(x, y, w, h, fill, stroke, sw=sw)
    n = len(lines)
    start = y + h / 2 - (n - 1) * (size + lead) / 2 + size / 2 - 2
    for i, ln in enumerate(lines):
        bold = weight if (i == 0 and not ln.startswith(("·", "—"))) else "normal"
        text(x + w / 2, start + i * (size + lead), ln, size=size, weight=bold)


def lbox(x, y, w, h, lines, palette=WHITE, size=13, weight="700", lead=6, sw=2):
    """Бокс с выравниванием текста по левому краю (для длинных списков)."""
    fill, stroke = palette
    rect(x, y, w, h, fill, stroke, sw=sw)
    n = len(lines)
    start = y + h / 2 - (n - 1) * (size + lead) / 2 + size / 2 - 2
    for i, ln in enumerate(lines):
        bold = weight if (i == 0 and not ln.startswith(("·", "—"))) else "normal"
        text(x + 16, start + i * (size + lead), ln, size=size, weight=bold, anchor="start")


def arrow(x1, y1, x2, y2, label="", color="#475569", dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
                 f'stroke-width="2.5" marker-end="url(#a)"{d}/>')
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        text(mx + 12, my, label, size=12, fill=color, anchor="start", weight="600")


# --- холст ---
parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}">')
parts.append('<defs><marker id="a" markerWidth="11" markerHeight="11" refX="8" refY="3" '
             'orient="auto" markerUnits="strokeWidth">'
             '<path d="M0,0 L8,3 L0,6 Z" fill="#475569"/></marker></defs>')
rect(0, 0, W, H, "#f7f9fc", "#f7f9fc", rx=0, sw=0)

text(W / 2, 46, "findwork — воркфлоу генерации отклика", size=26, weight="800")
text(W / 2, 74, "ссылка на вакансию  →  экспертный анализ  →  адаптированное резюме + письмо (PDF/DOCX)",
     size=14, fill="#6b7280")

cx = W / 2
cw = 560
cl = cx - cw / 2

# 1. вход
box(cl, 100, cw, 56, ["Павел шлёт боту ссылку на вакансию (Telegram)"], BLUE)
arrow(cx, 156, cx, 184)

# 2. парсинг вакансии
box(cl, 184, cw, 64,
    ["webvac.fetch_vacancy(url) — парсит страницу",
     "· название · компания · город · описание · ключевые навыки"],
    WHITE, size=13)
arrow(cx, 248, cx, 280)

# --- мастер-резюме: источник фактов (слева, питает агента) ---
mx, my, mw, mh = 60, 300, 250, 150
lbox(mx, my, mw, mh,
     ["resume/master_cco.md",
      "ЕДИНСТВЕННЫЙ источник",
      "фактов о кандидате.",
      "",
      "Спорные факты помечены *",
      "Ранний опыт (до 2011):",
      "только если релевантно."],
     PURPLE, size=12, lead=5)

# --- контейнер career_agent ---
ax, ay, aw, ah = cl - 30, 290, cw + 60, 760
rect(ax, ay, aw, ah, "#ffffff", "#0d6efd", rx=16, sw=2.5, dash="7 5")
text(ax + 20, ay + 26, "career_agent.prepare_application — двухагентный экспертный цикл",
     size=14, weight="800", fill="#0d6efd", anchor="start")
# стрелка от мастера в контейнер
arrow(mx + mw, my + mh / 2, ax, my + mh / 2, color="#6f42c1")

# ШАГ 1 — Стратег
s1y = 340
lbox(cl, s1y, cw, 150,
     ["① АГЕНТ-СТРАТЕГ  (writer: ChatGPT через n8n / OpenAI / Claude)",
      "Работает как карьерный эксперт, не копирайтер:",
      "· анализ вакансии: реальная роль, бизнес-задача, уровень, must/nice, слова HR;",
      "· карта соответствия: требование → факт / смежное / ПРОБЕЛ (с цифрой и компанией);",
      "· адаптированное резюме (профиль, достижения, опыт) + сопроводительное (JSON).",
      "ГЛАВНЫЙ ЗАКОН: только факты из мастера, без выдумок. Отстройка = акценты под вакансию."],
     BLUE, size=12, lead=6)
arrow(cx, s1y + 150, cx, s1y + 180)

# ШАГ 2 — Критик
s2y = s1y + 180
lbox(cl, s2y, cw, 132,
     ["② АГЕНТ-КРИТИК  (reviewer: Claude → фолбэк gpt-4.1)",
      "Сверяет черновик с вакансией и мастером:",
      "· фактичность (нет ли выдумок) · реалистичность атрибуции (личный вклад vs компания);",
      "· релевантность вакансии · стиль/оформление письма · минимум 3 цифры из мастера.",
      "Вердикт: pass | revise + конкретные правки."],
     BLUE, size=12, lead=6)
# loop revise → стратег
parts.append(f'<path d="M {cl} {s2y+30} H {cl-70} V {s1y+75} H {cl}" fill="none" '
             f'stroke="#dc3545" stroke-width="2.5" stroke-dasharray="6 4" marker-end="url(#a)"/>')
text(cl - 66, (s1y + s2y) / 2 + 20, "revise:", size=11, fill="#dc3545", anchor="start", weight="700")
text(cl - 66, (s1y + s2y) / 2 + 34, "1 правка", size=11, fill="#dc3545", anchor="start", weight="700")
arrow(cx, s2y + 132, cx, s2y + 162)

# ШАГ 3 — QA verify (детерминированно)
s3y = s2y + 162
lbox(cl, s3y, cw, 150,
     ["③ QA-КОНТРОЛЬ  (verify.py — детерминированно, БЕЗ LLM)",
      "· анти-галлюцинация: цифры/компании, которых нет в мастере;",
      "· ATS-дотяжка: навыки из вакансии, подтверждённые мастером, но не отражённые;",
      "· счётчик метрик в письме (цель ≥ 3).",
      "Нашёл проблему → 1 точечный регЕн Стратега.",
      "Что осталось неподтверждённым → ⚠️ warnings «проверь перед отправкой»."],
     AMBER, size=12, lead=6)
# loop регЕн
parts.append(f'<path d="M {cl} {s3y+30} H {cl-70} V {s1y+75} H {cl}" fill="none" '
             f'stroke="#e0a800" stroke-width="2.5" stroke-dasharray="6 4" marker-end="url(#a)"/>')
text(cl - 66, s3y - 6, "регЕн", size=11, fill="#b8860b", anchor="start", weight="700")

arrow(cx, ay + ah, cx, ay + ah + 30)

# 3. рендер
ry = ay + ah + 30
box(cl, ry, cw, 60, ["resume_doc.render_both — PDF + DOCX (шрифты, фото)"], GREEN, size=14)
arrow(cx, ry + 60, cx, ry + 90)

# 4. выход
oy = ry + 90
lbox(cl, oy, cw, 132,
     ["Бот присылает в Telegram:",
      "· роль + акценты под вакансию + % совпадения навыков + вердикт критика;",
      "· сопроводительное письмо;",
      "· warnings (факты на ручную сверку), если есть;",
      "· резюме PDF  +  DOCX."],
     BLUE, size=13, lead=7)

# fallback
fy = oy + 150
box(cl, fy, cw, 48,
    ["Фолбэк: если LLM-пайплайн упал → tailor.tailor() (базовый шаблон), отклик не теряется"],
    RED, size=12)

# легенда
ly = fy + 80
rect(40, ly, W - 80, 70, *BAND)
text(60, ly + 26, "Легенда:", size=13, weight="800", fill="#475569", anchor="start")
_leg = [(BLUE, "LLM / интерактив"), (GREEN, "готовый артефакт"),
        (AMBER, "детерминир. проверка"), (PURPLE, "источник фактов"), (RED, "страховка")]
_lx = 150
for (fill, stroke), lab in _leg:
    rect(_lx, ly + 16, 16, 16, fill, stroke, rx=4, sw=1.5)
    text(_lx + 22, ly + 28, lab, size=12, fill="#475569", anchor="start")
    _lx += 22 + len(lab) * 7.2 + 28
text(60, ly + 50,
     "Второй вход: утренний дайджест (pipeline.py) — сбор вакансий → скоринг релевантности → "
     "топ в Telegram → та же генерация по ссылке.",
     size=12, fill="#6b7280", anchor="start")

parts.append("</svg>")
OUT.write_text("\n".join(parts), encoding="utf-8")
print(f"written {OUT} ({OUT.stat().st_size} bytes)")

try:
    import cairosvg  # noqa: PLC0415
    png = OUT.with_suffix(".png")
    cairosvg.svg2png(url=str(OUT), write_to=str(png), output_width=W, output_height=H)
    print(f"written {png} ({png.stat().st_size} bytes)")
except Exception as e:  # noqa: BLE001
    print(f"PNG пропущен ({e})")
