# 🔥 Phoenix — CricJoin Auto Registration

Automated cricket slot registration system for **Beyond Boundaries — Vile Parle**.

## How it works

1. Users log into the Phoenix web app and set their slot preferences
2. GitHub Actions runs the bot automatically at the configured registration time
3. The bot logs into CricJoin, waits for the slot to open, and registers instantly
4. After each successful registration, the date automatically advances by 7 days

## Structure

```
phoenix-cricket/
├── frontend/          ← Phoenix web app
│   └── index.html
├── bot/               ← Python bot (runs on GitHub Actions)
│   └── phoenix_bot.py
├── configs/           ← User configuration files
│   ├── users_registry.json
│   └── user1.json
├── status/            ← Bot status after each run
│   └── user1_status.json
└── .github/
    └── workflows/     ← GitHub Actions workflows
        └── user1.yml
```

## Setup

See the Phoenix documentation for full setup instructions.

---
*Made with 🔥 for Beyond Boundaries — Vile Parle*
