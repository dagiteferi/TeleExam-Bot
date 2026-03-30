# TeleExam AI Telegram Bot - Software Requirements Specification (SRS)

**Document Version**: 1.1  
**Author**: Dagmawi Teferi 
**Date**: March 30, 2026  
**Project**: TeleExam AI - Telegram Bot Frontend  
**Status**: Final - Approved for Development

---

## 1. Introduction

### 1.1 Purpose
This SRS document specifies all functional and non-functional requirements for the **TeleExam AI Telegram Bot** — the official user interface for Ethiopian students to access mock exams, practice questions, and AI-powered tutoring directly inside Telegram.

The bot is designed as a **pure presentation layer**. It performs **no educational logic**, **no scoring**, **no AI processing**, and **no data persistence**. Its sole responsibility is to accept Telegram Updates, securely communicate with the FastAPI backend via REST, and render responses into rich, interactive Telegram messages and keyboards.

### 1.2 Scope
**In Scope**:
- User onboarding and automatic registration
- Main navigation menu
- Exam, Practice, and Quiz session flows
- AI explanation requests and dynamic tutoring chat
- Personalized study plan display
- Referral system with deep links
- Beautiful, responsive Telegram UI using Reply and Inline keyboards

**Out of Scope**:
- Any business logic (scoring, question generation, AI orchestration, progress tracking)
- Persistent storage (database)
- Long-polling (forbidden in production)
- Direct interaction with LLMs (all AI calls go through backend)

### 1.3 Target Users
- Ethiopian high school and university students
- Teachers and parents (limited access)
- Users with basic smartphone and Telegram usage

### 1.4 System Context
**Backend**: FastAPI Stateless Monolith (PostgreSQL + Redis + Groq LLMs via LangGraph)

---

## 2. Functional Requirements

### 2.1 Onboarding & Authentication (FR-01)

- The bot must automatically register or update user profile on every interaction.
- On `/start` command, parse Telegram user data (`id`, `username`, `first_name`, `last_name`).
- Support referral deep links in format: `t.me/BotUsername?start=ref_XXXX`
- If referral code is present, include `invite_code` in the upsert payload.
- Middleware must ensure user exists in backend before any other handler executes.

**Priority**: Must-Have

### 2.2 Main Navigation Menu (FR-02)

- Provide a persistent **ReplyKeyboardMarkup** as the main menu.
  - Menu buttons (in Amharic + English where appropriate):
    - Take Mock Exam
    - Practice Questions
    - My Study Plan
    - AI Tutor
    - Refer & Earn

**Priority**: Must-Have

### 2.3 Session Management (FR-03)

The bot must support three distinct session modes:

| Mode       | Description                          | Explanations | AI Access | Strict Timing | Scoring |
|------------|--------------------------------------|--------------|-----------|---------------|---------|
| `exam`     | Full mock exam simulation            | No           | No        | Yes           | Yes     |
| `practice` | Learning-focused practice            | Yes          | Yes       | No            | Yes     |
| `quiz`     | Quick topic-based testing            | Optional     | Yes       | No            | Yes     |

**Flow**:
- User selects mode → Bot calls `POST /api/sessions/start`
- Backend returns `session_id` (stored temporarily in FSM)
- Sequential question delivery using `GET /api/sessions/{session_id}/question`
- Answer submission via Inline Keyboard callbacks
- Support for `qtoken` anti-cheat mechanism

**Priority**: Must-Have

### 2.4 Question Rendering & Interaction (FR-04)

- Display question prompt clearly (support Markdown/HTML)
- Render multiple-choice options as Inline Keyboard buttons (A, B, C, D)
- Store `qtoken` securely in FSM for anti-cheat validation
- In Practice mode: Show "Explain with AI" inline button
- After answer: Show result (correct/incorrect) in Practice mode only

**Priority**: Must-Have

### 2.5 AI Tutoring Features (FR-05)

- **AI Explanation**: In Practice mode, user can request pedagogical explanation via inline button.
  - Calls `POST /api/ai/explain`
  - Renders rich, structured explanation using Telegram formatting
- **Dynamic AI Chat**: Allow follow-up questions in a dedicated chat state (using FSM)
- **Study Plan**: 
  - Button "My Study Plan" in main menu
  - Calls `POST /api/ai/study-plan`
  - Convert JSON response into beautiful Markdown calendar/table
  - Handle 402 error gracefully ("Complete at least one mock exam first!")

**Priority**: Must-Have

### 2.6 Referral System (FR-06)

- Generate unique referral link using user's telegram_id
- Allow sharing via Telegram's native share button
- Deep link support: `t.me/BotUsername?start=ref_{code}`
- Track successful referrals through backend

**Priority**: Should-Have

### 2.7 Session Completion (FR-07)

- When no more questions: Automatically call `/submit`
- Display final score, percentage, and motivational message
- Option to review answers (in Practice mode)
- Return to main menu

**Priority**: Must-Have

---

## 3. Non-Functional Requirements

### 3.1 Performance & Scalability (NFR-01)
- Support minimum 1,000 concurrent active users
- Response time < 2 seconds for most interactions
- Use Webhooks (aiohttp.web) in production — long-polling **strictly forbidden**

### 3.2 Statelessness (NFR-02)
- Bot must not use any local database
- Only temporary conversation state via `aiogram.fsm`
- All persistent data and logic must reside in the FastAPI backend

### 3.3 Security (NFR-03)
- Never expose `BACKEND_URL`, `BOT_TOKEN`, or `BACKEND_SECRET` in logs or code
- Every backend request must include headers:
    - `X-Telegram-Secret`
    - `X-Telegram-Id`
- Validate all callback data to prevent tampering
- Follow least-privilege principle

### 3.4 Reliability & Error Handling (NFR-04)
- Graceful degradation when backend is unreachable
- User-friendly error messages
- Always acknowledge CallbackQuery to remove loading indicator
- Structured logging without sensitive data

### 3.5 Hosting & Deployment (NFR-05)
- Must run comfortably on **Render Web Service Free Tier** or **PythonAnywhere**
- Proper startup and shutdown hooks for resources
- Support environment-based configuration

### 3.6 Usability (NFR-06)
- Intuitive navigation
- Clean, readable messages with proper formatting
- Support both English and Amharic text where feasible
- Mobile-first design (Telegram constraints respected)

---

## 4. Assumptions & Dependencies

- Backend FastAPI service is fully operational and follows the endpoint contracts defined in the integration guide.
- Telegram Bot Token is obtained from BotFather.
- Shared secret (`BACKEND_SECRET`) is securely configured between bot and backend.
- Users have Telegram app installed on Android/iOS.

---

## 5. Integration Requirements

**Mandatory Backend Endpoints**:

1. `POST /api/users/upsert`
2. `POST /api/sessions/start`
3. `GET /api/sessions/{session_id}/question`
4. `POST /api/sessions/{session_id}/answer`
5. `POST /api/sessions/{session_id}/next`
6. `POST /api/sessions/{session_id}/submit`
7. `POST /api/ai/explain`
8. `POST /api/ai/study-plan`

All requests must include security headers.

---

## 6. Acceptance Criteria

- Bot correctly registers users on first interaction
- Full exam flow completes without errors
- Practice mode shows AI explanations correctly
- Study plan displays nicely formatted (handles 402 case)
- Referral deep links are processed
- Webhook mode works on free hosting
- No secrets are leaked in code or logs

---

**This SRS serves as the single source of truth** for all functional and non-functional requirements of the TeleExam AI Telegram Bot.

Any changes must be documented, versioned, and approved.

**Approved by**: Dagmawi Teferi
**Date**: March 30, 2026