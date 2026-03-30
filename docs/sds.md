SDS.md
Markdown# TeleExam AI Telegram Bot - Software Design Specification (SDS)

**Document Version**: 1.0  
**Author**: Senior Backend & Bot Architect (12+ years experience)  
**Date**: March 30, 2026  
**Project**: TeleExam AI - Telegram Bot Frontend  
**Status**: Final Design - Ready for Implementation

---

## 1. Introduction & Design Philosophy

### 1.1 Purpose
This SDS provides a complete, low-level technical blueprint for the **TeleExam AI Telegram Bot** — a pure presentation layer that translates between Telegram users and the FastAPI backend.

The bot is deliberately designed as a **thin client** with **zero business logic**, ensuring maximum scalability, security, and maintainability.

### 1.2 Core Design Principles (Non-Negotiable)

1. **Statelessness**  
   - No local database (not even SQLite)  
   - All persistent state lives in the FastAPI backend  
   - Temporary conversation flow managed exclusively via `aiogram.fsm` (RedisStorage recommended in production)

2. **Separation of Concerns**  
   - Bot = UI Rendering + Translation Layer only  
   - Backend = All educational logic, scoring, AI orchestration, user progress, etc.

3. **High Concurrency & Scalability**  
   - Designed to handle 1,000+ concurrent users  
   - Long-polling **strictly forbidden** in production  
   - Webhook mode using `aiohttp.web` + proper connection pooling

4. **Security First**  
   - Backend secrets never exposed in logs or code  
   - Every request to backend includes `X-Telegram-Secret` and `X-Telegram-Id` headers  
   - Zero trust on Telegram data — always validate through backend

5. **Production Readiness**  
   - Optimized for free hosting tiers (Render Web Service, PythonAnywhere)  
   - Proper logging, error handling, graceful degradation  
   - Clean shutdown of resources (ClientSession)

---

## 2. System Architecture

### 2.1 High-Level Architecture

```mermaid
flowchart TD
    A[Telegram Users] --> B[Telegram Bot API]
    B --> C[aiogram 3.x Dispatcher]
    C --> D[Middleware Layer]
    D --> E[FSM Storage (Redis)]
    D --> F[API Client Service]
    F <--> G[FastAPI Backend\n(Stateless Monolith)]
    C --> H[Keyboards & Message Renderers]
    H --> I[Telegram Response]
2.2 Component Breakdown
2.2.1 Middleware Layer

Auto User Upsert Middleware (middlewares/auto_upsert.py)
Runs on every incoming Update
Extracts telegram_id, username, first_name, last_name
Detects referral codes from start parameter (ref_XXXX)
Calls POST /api/users/upsert synchronously before routing
Ensures user always exists in backend


2.2.2 Services Layer

API Client (services/api_client.py)
Singleton aiohttp.ClientSession with proper lifecycle management
Base URL + default headers injection (X-Telegram-Secret, X-Telegram-Id)
Typed async methods for every backend endpoint
Centralized error handling, timeouts (15s), retry logic (optional)
Proper JSON serialization/deserialization with Pydantic models (recommended)


2.2.3 State Management

Uses aiogram.fsm with MemoryStorage (development) → RedisStorage (production)
Defined in states/session_states.py

Pythonclass ExamSession(StatesGroup):
    active = State()                    # Session in progress
    waiting_for_answer = State()        # After question sent
    reviewing = State()                 # After answer submitted (practice mode)

class AIInteraction(StatesGroup):
    chatting = State()                  # Dynamic AI tutor conversation
2.2.4 Keyboards Module

Reply Keyboards (keyboards/reply.py)
Persistent main menu (always visible)

Inline Keyboards (keyboards/inline.py)
Dynamic question choices (A, B, C, D)
Action buttons: "Explain with AI", "Next Question", "End Session"


2.2.5 Routers (Handlers)
Organized by domain:

routers/onboarding.py
/start command
Deep link handling (?start=ref_xxx)
Welcome message + main menu

routers/sessions.py
Starting sessions (exam, practice, quiz)
Question delivery
Answer processing (CallbackQuery)
Next question flow
Session completion & scoring

routers/ai_tutor.py
AI explanation requests
Study plan generation
Dynamic AI chat (follow-up questions)



3. Detailed Component Design
3.1 Configuration Management (config.py)
Uses pydantic-settings for strong typing and validation.
Pythonclass Settings(BaseSettings):
    BOT_TOKEN: str
    BACKEND_URL: HttpUrl
    BACKEND_SECRET: str
    WEBHOOK_PATH: str = "/webhook"
    WEBHOOK_SECRET: str = Field(default_factory=lambda: secrets.token_hex(32))
    HOST: str = "0.0.0.0"
    PORT: int = 8080

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
3.2 API Client Design
Critical Security Rules:

Every request must include:httpX-Telegram-Secret: {BACKEND_SECRET}
X-Telegram-Id: {telegram_id}
telegram_id is injected dynamically per request from current user context
Timeout: 15 seconds
ClientSession created once at startup and closed on shutdown

3.3 Data Flow - Exam Session (Detailed)

User clicks "Take Exam" → POST /api/sessions/start
Backend returns session_id → stored in FSM
Bot calls GET /api/sessions/{session_id}/question
Renders prompt + inline keyboard with choices + qtoken stored in state
User selects answer → CallbackQuery → POST /api/sessions/{session_id}/answer
Backend returns result
Bot calls POST /api/sessions/{session_id}/next
If has_next: true → repeat from step 3
If false → POST /api/sessions/{session_id}/submit → show final score

Anti-Cheat: qtoken must be sent with answer. Backend validates it.
3.4 Error Handling Strategy

Telegram Errors: Use aiogram.exceptions with proper retry/backoff
Backend Errors:
4xx → User-friendly message
402 Payment Required → "Complete at least one mock exam to unlock study plan"
5xx → "Service temporarily unavailable. Please try again later."

Always call answer_callback_query() to remove loading state
Log errors with context (user_id, session_id) but never sensitive data

3.5 Performance Considerations

Reuse single ClientSession across all requests
Use asyncio efficiently — avoid blocking calls
Keep message text under Telegram limits (4096 chars)
Use HTML parsing mode for rich formatting when needed
Compress study plan output using clean Markdown tables


4. Deployment Architecture
Target Platforms: Render Web Service (Free) or PythonAnywhere
Webhook Setup:
Python# run.py
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

async def on_startup(bot: Bot, base_url: str):
    await bot.set_webhook(f"{base_url}{WEBHOOK_PATH}", secret_token=WEBHOOK_SECRET)

app = web.Application()
setup_application(app, dp, bot=bot)
Environment Variables (.env.example):
envBOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
BACKEND_URL=https://teleexam-backend.onrender.com
BACKEND_SECRET=super_long_random_secret_key_2026

5. Security Design

Secret Management
All secrets in .env (never committed)
.gitignore strictly enforced

Header-Based Authentication
Bot never trusts Telegram user data blindly
Backend is the single source of truth

Rate Limiting
Recommended: Let backend handle rate limiting
Bot can add soft client-side throttling if needed



6. Testing Strategy

Unit tests for keyboard builders and message formatters
Integration tests with mocked backend responses
Manual testing scenarios:
Full exam flow
Practice mode with AI explain
Study plan generation
Referral flow
Error cases (no internet, backend down, 402)



7. Future Extensibility

Easy addition of new session modes
Support for media questions (images, voice)
Multi-language support (Amharic + English)
Analytics events forwarding to backend
Admin commands for monitoring