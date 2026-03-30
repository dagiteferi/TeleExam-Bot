# TeleExam AI Telegram Bot - Coding Standards

**Version**: 1.0 — March 30, 2026

This document outlines the mandatory coding standards for the TeleExam AI Telegram Bot project. Strict adherence to these guidelines is required to ensure code quality, maintainability, and consistency.

### 1. Core Philosophy
- Code must be **production-ready from day one**.
- Zero tolerance for technical debt.
- Fast to write, fast to run, cheap to host (Render Free Tier).
- Self-documenting code > comments.
- Comments only when you explain **why**, never **what**. One short line max.

### 2. Python & Style Rules
- Python 3.11+
- **Black** formatting (line-length=100)
- **ruff** + **isort** (Google style)
- Type hints **everywhere** (no `Any`)
- Async-first: every handler, every service call
- No synchronous blocking code

```python
```python
# Good
async def handle_answer(callback: CallbackQuery) -> None:
    ...

# Never
def handle_answer(...):  # sync
```
3. Project-Specific Rules (Non-Negotiable)

Stateless: Never use files, SQLite, or in-memory globals for data. Only aiogram.fsm (Redis in prod).
No business logic in bot. Bot = UI + translation layer only.
Single aiohttp.ClientSession (singleton in services/api_client.py). Never create new sessions.
Security:
Every backend call must have headers: X-Telegram-Secret + X-Telegram-Id
Never log secrets, tokens, or full payloads
Never hardcode anything

Webhooks only in production. No polling.
Minimal imports: import exactly what you use.

4. File & Folder Rules

One router = one responsibility
Keep files under 200 lines when possible
__init__.py only for exports
All code in bot/ package

### 5. Code Style (Google Lead Standard)
```python
# 1. Constants at top
BACKEND_TIMEOUT = 15

# 2. Clear, short function names
async def send_question(...) -> None:        # not process_current_question
async def handle_explain_callback(...) -> None:

# 3. Minimal comments - only "why"
await bot.answer_callback_query(callback.id)  # remove loading spinner instantly

# 4. Early returns, flat structure
if error:
    await send_error_message(...)
    return

# 5. Type everything
async def start_session(mode: Literal["exam", "practice", "quiz"]) -> str:
```

### 6. Error Handling

Catch only what you can handle
Always await callback.answer() on inline buttons
User-facing messages: short, friendly, no tech jargon
Backend 4xx/5xx → graceful message, never crash

### 7. Performance & Free Hosting Rules

Reuse ClientSession (lifecycle in main.py)
Keep messages < 4000 chars
No heavy computation in handlers
Designed to run on Render Free Tier (512 MB, 0.5 CPU)

### 8. Development Speed Rules

Write clean code directly (no "todo" comments)
Copy-paste is allowed only for similar keyboard patterns
Zero over-engineering

### 9. Final Rule
Prioritize simplicity and clarity over cleverness. This approach fosters reliable and maintainable systems.
Adherence to these standards is crucial for developing a secure, fast, maintainable, and production-ready bot.