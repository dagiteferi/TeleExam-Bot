
# TeleExam AI Telegram Bot

![Telegram Bot Logo](https://via.placeholder.com/150/0000FF/FFFFFF?text=TeleExam+AI)

The TeleExam AI Telegram Bot is the official user interface for Ethiopian students to access mock exams, practice questions, and AI-powered tutoring directly inside Telegram. Designed as a **pure presentation layer**, this bot focuses on delivering a seamless and interactive user experience, delegating all complex educational logic, scoring, and AI processing to a robust FastAPI backend.

This project is built with scalability, security, and maintainability in mind, optimized for cost-effective deployment on platforms like Render Free Tier.

## ✨ Features

-   **User Onboarding**: Automatic registration and profile updates for new and returning users.
-   **Referral System**: Support for deep links (`t.me/BotUsername?start=ref_XXXX`) to track referrals.
-   **Main Menu Navigation**: Intuitive persistent menu for easy access to all features.
-   **Session Management**:
    -   **Mock Exams**: Full exam simulations with strict timing and scoring.
    -   **Practice Questions**: Learning-focused practice with explanations and AI access.
    -   **Quick Quizzes**: Topic-based testing with optional explanations.
-   **Interactive Questions**: Displays questions with inline keyboard options (A, B, C, D).
-   **AI Tutoring**:
    -   **AI Explanations**: On-demand pedagogical explanations for practice questions.
    -   **Dynamic AI Chat**: Engage in follow-up conversations with an AI tutor.
    -   **Personalized Study Plans**: Generates and displays study plans based on user performance.
-   **Stateless Design**: No local database; all persistent data and logic reside in the backend.
-   **High Performance**: Built with `aiogram 3.x` and `aiohttp` for asynchronous operations, supporting 1000+ concurrent users.
-   **Secure Communication**: All backend requests include `X-Telegram-Secret` and `X-Telegram-Id` headers.
-   **Webhook-only Deployment**: Optimized for production environments using webhooks (no polling).

## 🚀 Architecture Overview

The bot acts as a thin client, communicating exclusively with a FastAPI backend via REST APIs.

```mermaid
flowchart TD
    A[Telegram Users] --> B[Telegram Bot API]
    B --> C[aiogram 3.x Dispatcher]
    C --> D[Middleware Layer (Auto User Upsert)]
    D --> E[FSM Storage (Memory/Redis)]
    D --> F[API Client Service (aiohttp.ClientSession)]
    F <--> G[FastAPI Backend\n(Stateless Monolith)]
    C --> H[Keyboards & Message Renderers]
    H --> I[Telegram Response]
```

## 🛠️ Getting Started

### Prerequisites

-   Python 3.11+
-   A Telegram Bot Token from [@BotFather](https://t.me/BotFather).
-   A running FastAPI backend for TeleExam AI (URL and shared secret required).

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/teleexam-ai-telegram-bot.git
    cd teleexam-ai-telegram-bot
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python3.11 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

### Configuration

Create a `.env` file in the project root based on `.env.example`:

```bash
cp .env.example .env
```

Edit the `.env` file with your specific values:

```env
BOT_TOKEN=your_telegram_bot_token_here
BACKEND_URL=https://your-teleexam-backend.onrender.com
BACKEND_SECRET=a_long_random_secret_key_for_backend_auth
WEBHOOK_PATH=/webhook
WEBHOOK_SECRET=another_long_random_secret_key_for_webhook_security
HOST=0.0.0.0
PORT=8080
```

-   `BOT_TOKEN`: Your Telegram Bot API token.
-   `BACKEND_URL`: The base URL of your TeleExam AI FastAPI backend.
-   `BACKEND_SECRET`: A secret key shared between your bot and the backend for authentication.
-   `WEBHOOK_PATH`: The path where your bot will listen for Telegram updates (e.g., `/webhook`).
-   `WEBHOOK_SECRET`: A secret token used by Telegram to validate webhook requests.
-   `HOST`: The host address for the aiohttp server (e.g., `0.0.0.0` for all interfaces).
-   `PORT`: The port for the aiohttp server to listen on.

### Running Locally (Polling Mode for Development)

For quick local testing without setting up webhooks, you can run the bot in polling mode:

```bash
python -m bot.main
```

This will start the bot, and it will fetch updates directly from Telegram.

### Running with Webhooks (Production-Ready)

For production deployment, the bot is designed to run using webhooks.

```bash
python run.py
```

This will start an `aiohttp` web server that listens for Telegram updates on the configured `HOST` and `PORT`. It will also automatically set the webhook URL with Telegram on startup.

**Deployment Notes:**
-   Ensure your `BACKEND_URL` is publicly accessible and correctly points to your deployed bot instance.
-   Platforms like Render Web Services can host this bot effectively. Configure your service to run `python run.py` as the start command.
-   For FSM storage in production, consider using `RedisStorage` instead of `MemoryStorage`. Uncomment and configure the `RedisStorage` lines in `bot/main.py`.

## 📂 Project Structure

```
telegram-bot/
├── docs/                          # Project documentation (SRS, SDS, Coding Standards)
├── .env.example                   # Example environment variables
├── .gitignore                     # Git ignore rules
├── requirements.txt               # Python dependencies
├── run.py                         # Webhook server entry point
├── README.md                      # This file
├── CODING_STANDARDS.md            # Detailed coding standards
└── bot/
    ├── __init__.py                # Package initializer
    ├── config.py                  # Application settings (pydantic-settings)
    ├── main.py                    # Bot initialization, dispatcher, middlewares
    ├── middlewares/
    │   ├── __init__.py
    │   └── auto_upsert.py         # Middleware for automatic user upsert to backend
    ├── services/
    │   ├── __init__.py
    │   └── api_client.py          # Singleton aiohttp.ClientSession for backend communication
    ├── states/
    │   ├── __init__.py
    │   └── session_states.py      # aiogram FSM states for conversation flow
    ├── keyboards/
    │   ├── __init__.py
    │   ├── reply.py               # ReplyKeyboards (main menu)
    │   └── inline.py              # InlineKeyboards (question choices, actions)
    └── routers/                   # aiogram Routers for handling different features
        ├── __init__.py
        ├── onboarding.py          # Handles /start command and user onboarding
        ├── sessions.py            # Manages exam, practice, and quiz sessions
        └── ai_tutor.py            # Handles AI explanations, study plans, and AI chat
```

## 📏 Coding Standards

This project adheres to a strict set of coding standards to ensure high quality, maintainability, and consistency. Please refer to [CODING_STANDARDS.md](CODING_STANDARDS.md) for full details. Key principles include:

-   Python 3.11+, Black formatting, Ruff linting, Isort for imports.
-   Extensive type hinting.
-   Async-first approach.
-   Stateless bot logic (except FSM).
-   Clear separation of concerns (UI only).
-   Secure and efficient backend communication.

## 🤝 Contributing

We welcome contributions! Please ensure your code adheres to the [CODING_STANDARDS.md](CODING_STANDARDS.md) and follows the project's architectural principles.

1.  Fork the repository.
2.  Create a new branch (`git checkout -b feature/your-feature-name`).
3.  Make your changes.
4.  Run linters and formatters (`black .`, `ruff check . --fix`, `isort .`).
5.  Commit your changes (`git commit -m 'feat: Add new feature'`).
6.  Push to the branch (`git push origin feature/your-feature-name`).
7.  Open a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
