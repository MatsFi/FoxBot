discord_bot/
│
├── cogs/
│   ├── __init__.py
│   └── local_economy.py           # Local Economy commands
│
├── config/
│   ├── __init__.py
│   └── settings.py          # Configuration management
│
├── data/                    # Created automatically, stores database
│
├── database/
│   ├── __init__.py
│   ├── models.py            # SQLAlchemy models
│   └── database.py          # Database connection handling
│
├── logs/                    # Created automatically, stores logs
│
├── services/
│   ├── __init__.py
│   └── points_service.py    # Business logic layer
│
├── utils/
│   ├── __init__.py
│   ├── decorators.py        # Custom decorators
│   └── exceptions.py        # Custom exceptions
│
├── __init__.py              # Root package initialization
├── bot.py                   # Main bot file
└── requirements.txt         # Project dependencies

