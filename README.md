# Name: PM (Prediction Market)

## Project Structure

```
discord_bot/
├── cogs/
│   ├── __init__.py                 # Cog package initialization
│   ├── economy_cog_template.py     # Base class for economy cogs
│   ├── local_economy.py            # Local Economy commands
│   ├── ffs_economy.py              # FFS Economy commands
│   ├── hackathon_economy.py        # Hackathon Economy commands
│   └── prediction_market.py        # Prediction Market commands
│
├── config/
│   ├── __init__.py
│   └── settings.py                 # Configuration management
│
├── database/
│   ├── __init__.py
│   ├── models.py                   # SQLAlchemy models
│   └── database.py                 # Database connection handling
│
├── services/
│   ├── __init__.py                     # Services package initialization
│   ├── external_service_adapters.py    # External economy adapters
│   ├── ffs_points_service.py           # FFS economy service
│   ├── hackathon_points_service.py     # Hackathon economy service
│   ├── local_points_service.py         # Local economy service
│   ├── prediction_market_service.py    # Prediction Market service
│   ├── transfer_interface.py           # Interface definitions
│   └── transfer_service.py             # Cross-economy transfer logic
│
├── utils/
│   ├── __init__.py
│   ├── decorators.py               # Custom decorators
│   └── exceptions.py               # Custom exceptions
│
├── __init__.py                     # Root package initialization
├── bot.py                          # Main bot file
└── requirements.txt                # Project dependencies
```

## Design Principles

## Core Components

### Services Layer

### Cogs Layer

## Setup Order

1. Local Economy must be loaded first to initialize the transfer service
2. External economies can be loaded in any order thereafter
3. Each external economy registers with the transfer service on load
4. Load additional games which interact with an economy thereafter

## Deployment

```bash
# Set up environment variables
cp .env.example .env
# Edit .env with your configuration

# Install dependencies
pip install -r requirements.txt

# Run the bot
python bot.py
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

MIT

