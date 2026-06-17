#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генерирует docs/architecture.svg — обзорную схему работы системы findwork."""
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1160, 900
OUT = Path(__file__).resolve().parent.parent / "docs" / "architecture.svg"

GREEN = ("#d4edda", "#28a745")
AMBER = ("#fff3cd", "#e0a800")
BLUE = ("#cfe2ff", "#0d6efd")
WHITE = ("#ffffff", "#9aa5b1")
BAND = ("#eef2f7", "#cbd5e1")

parts: list[str] = []


def rect(x, y, w, h, fill, stroke, rx=10, sw=2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')


def text(x, y, s, size=14, weight="normal", fill="#1f2937", anchor="middle"):
    parts.append(f'<text x="{x}" y="{y}" font-family="Segoe UI, Arial, sans-serif" '
                 f'font-size="{size}" font-weight="{weight}" fill="{fill}" '
                 f'text-anchor="{anchor}">{escape(s)}</text>')


def box(x, y, w, h, lines, palette=WHITE, size=14, weight="600"):
    fill, stroke = palette
    rect(x, y, w, h, fill, stroke)
    n = len(lines)
    start = y + h / 2 - (n - 1) * (size + 4) / 2 + size / 2 - 2
    for i, ln in enumerate(lines):
        text(x + w / 2, start + i * (size + 4), ln, size=size,
             weight=weight if i == 0 else "normal")


def arrow(x1, y1, x2, y2):
    parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                 f'stroke="#64748b" stroke-width="2" marker-end="url(#a)"/>')


# --- холст ---
parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}">')
parts.append('<defs><marker id="a" markerWidth="10" markerHeight="10" refX="8" refY="3" '
             'orient="auto" markerUnits="strokeWidth">'
             '<path d="M0,0 L8,3 L0,6 Z" fill="#64748b"/></marker></defs>')
rect(0, 0, W, H, "#f7f9fc", "#f7f9fc", rx=0, sw=0)

text(W / 2, 40, "findwork — схема работы системы", size=24, weight="700")
text(W / 2, 66, "сбор → скоринг релевантности → утренний дайджест в Telegram → отклик с подтверждением",
     size=14, fill="#6b7280")

# --- источники ---
rect(40, 90, 1080, 96, *BAND)
text(60, 112, "Источники вакансий", size=13, weight="700", fill="#475569", anchor="start")
box(60, 122, 240, 50, ["Trudvsem API  ✓", "офиц., бесплатно, легально"], GREEN, size=13)
box(320, 122, 240, 50, ["HH  ⚠", "эмуляция приложения"], AMBER, size=13)
box(580, 122, 240, 50, ["Хабр Карьера / getmatch"], WHITE, size=13)
box(840, 122, 240, 50, ["Telegram-каналы вакансий"], WHITE, size=13)

cx = W / 2
cw = 420
cl = cx - cw / 2

# центральный конвейер
arrow(cx, 186, cx, 206)
box(cl, 206, cw, 48, ["🧲 Сборщик — нормализация в единую схему"], WHITE)
arrow(cx, 254, cx, 274)
box(cl, 274, cw, 48, ["🔁 Дедуп  ·  state/seen.json"], WHITE)
arrow(cx, 322, cx, 342)
box(cl, 342, cw, 56, ["🎯 Скоринг релевантности",
                       "relevance.py + profile.json (стек ↔ требования)"], GREEN)
arrow(cx, 398, cx, 418)
box(cl, 418, cw, 48, ["🤖 LLM-доскоринг (опц., Claude API)"], BLUE)
arrow(cx, 466, cx, 486)
box(cl, 486, cw, 50, ["🗞 Дайджест  →  📨 Telegram-бот"], GREEN)

# ветки действий
arrow(cx, 536, cx, 560)
parts.append(f'<line x1="220" y1="560" x2="940" y2="560" stroke="#64748b" stroke-width="2"/>')
for bx in (220, 580, 940):
    parts.append(f'<line x1="{bx}" y1="560" x2="{bx}" y2="582" stroke="#64748b" '
                 f'stroke-width="2" marker-end="url(#a)"/>')
box(100, 582, 240, 56, ["📝 Резюме под вакансию", "tailor.py + LLM"], WHITE, size=13)
box(460, 582, 240, 56, ["✅ Подтверждение → 📤 Отклик", "полу-авто, лимиты/паузы"], AMBER, size=13)
box(820, 582, 240, 56, ["✖ Пропустить"], WHITE, size=13)

# к площадке
arrow(340, 610, 458, 610)
arrow(580, 638, 580, 662)
box(460, 662, 240, 46, ["🌐 HH / площадка"], AMBER, size=13)
arrow(580, 708, 580, 730)
box(460, 730, 240, 46, ["📱 Павел (Telegram)"], BLUE, size=13)

# инфраструктура (футер-полоса)
rect(40, 800, 1080, 56, *BAND)
text(W / 2, 826, "🖥  Всё на VPS в РФ (резидентный IP)      ⏰  systemd-timer, каждое утро 09:00      "
                 "🔐  секреты в .env (вне git)      🧩  источники за единым интерфейсом",
     size=13, weight="600", fill="#475569")

# легенда
text(60, 786, "🟢 готово / легально и безопасно", size=12, fill="#28a745", anchor="start", weight="600")
text(360, 786, "🟡 «серый» путь — риск бана, только под подтверждением", size=12,
     fill="#b8860b", anchor="start", weight="600")
text(820, 786, "🔵 опционально / интерактив", size=12, fill="#0d6efd", anchor="start", weight="600")

parts.append("</svg>")
OUT.write_text("\n".join(parts), encoding="utf-8")
print(f"written {OUT} ({OUT.stat().st_size} bytes)")
