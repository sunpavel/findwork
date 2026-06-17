# Архитектура системы findwork

Схемы ниже рендерятся прямо на GitHub. Картинка-обзор: `docs/architecture.svg`.

## 1. Как работает система (поток данных)

```mermaid
flowchart TD
    subgraph SRC["📥 Источники вакансий"]
        S1["Trudvsem API<br/>(офиц., бесплатно) ✅"]
        S2["HH<br/>(эмуляция приложения)"]
        S3["Хабр Карьера / getmatch"]
        S4["Telegram-каналы вакансий"]
    end

    SRC --> COLLECT["🧲 Сборщик<br/>нормализация в единую схему"]
    COLLECT --> DEDUP["🔁 Дедуп<br/>state/seen.json"]
    DEDUP --> SCORE["🎯 Скоринг релевантности<br/>relevance.py + profile.json"]
    SCORE --> LLM["🤖 LLM-доскоринг<br/>(опц., Claude API)"]
    LLM --> RANK["📊 Ранжирование + порог"]

    RANK -->|"скор ≥ 55"| DIGEST["🗞 Утренний дайджест"]
    DIGEST --> TG["📨 Telegram-бот"]

    TG -->|"кнопка: Резюме"| TAILOR["📝 Адаптация резюме<br/>+ сопроводительное<br/>master_cco.md + LLM"]
    TG -->|"кнопка: Отклик"| CONFIRM{"✅ Подтверждение<br/>кандидата"}
    TG -->|"кнопка: Пропустить"| SKIP["✖ skip"]

    TAILOR --> CONFIRM
    CONFIRM -->|"OK"| APPLY["📤 Отклик на вакансию<br/>(полу-авто, с лимитами)"]
    APPLY --> HH["🌐 HH / площадка"]

    classDef done fill:#d4edda,stroke:#28a745,color:#000;
    classDef grey fill:#fff3cd,stroke:#ffc107,color:#000;
    class S1,SCORE,DEDUP,DIGEST,TG done;
    class S2,APPLY,CONFIRM grey;
```

🟢 зелёное — готово/легально и безопасно · 🟡 жёлтое — «серый» путь с риском бана (под подтверждением).

## 2. Что крутится на VPS (инфраструктура)

```mermaid
flowchart LR
    subgraph VPS["🖥 VPS в РФ (резидентный IP)"]
        TIMER["⏰ systemd-timer<br/>каждое утро 09:00"]
        TIMER --> PIPE["pipeline.py"]
        ENV[".env<br/>токены (вне git)"] -.-> PIPE
        PIPE --> STATE["state/seen.json"]
        BOT["🤖 Telegram-бот<br/>(long polling)"]
    end
    PIPE -->|"дайджест"| TGAPI["Telegram API"]
    BOT <-->|"кнопки/команды"| TGAPI
    TGAPI <--> USER["📱 Павел"]
```

## 3. Компоненты и файлы

| Слой | Файл | Статус |
|------|------|--------|
| Профиль и веса навыков | `profile/profile.json` | ✅ |
| Эталонное резюме | `resume/master_cco.md` | ✅ |
| Скоринг релевантности | `src/relevance.py` | ✅ |
| Источники вакансий | `src/sources.py` (`sample`, `trudvsem`, `hh`) | 🚧 |
| Пайплайн дайджеста | `src/pipeline.py` | ✅ |
| Отправка в Telegram | `src/notify.py` | ✅ |
| Интерактивный бот (кнопки) | `src/bot.py` | ⏳ Фаза 2 |
| Адаптация резюме/письма | `src/tailor.py` | ⏳ Фаза 2 |
| Отклик с подтверждением | `src/apply.py` | ⏳ Фаза 2 |

## 4. Принципы

- **Human-in-the-loop:** отклик — только после подтверждения (выбранный режим). Это и
  качество, и снижение риска бана HH.
- **Легальное в приоритете:** Trudvsem API — официальный и бесплатный; HH-путь — серый,
  включается осознанно и с вежливыми лимитами/паузами.
- **Без vendor-lock:** источники за единым интерфейсом, секреты в `.env`, состояние в файле/БД.
- **Антиробот:** LLM-тексты с «шероховатостями», чтобы не выглядеть шаблонными (практика 2026).
