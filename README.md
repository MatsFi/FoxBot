# FoxBot Discord Bot

A Discord bot featuring a prediction market system that works with multiple external economies.

## Core Design Principles

### Economy System Architecture
- **Local Economy**: Core economy that cannot participate in prediction markets
- **External Economies**: Multiple external economies (e.g., Hackathon, FFS) can be connected
- **Transfer Service**: Central service that handles all token movements between economies
- **Initialization Order**: Critical for proper system setup
  1. Local Economy (initializes transfer service)
  2. External Economies (register with transfer service)
  3. Prediction Market (uses registered external economies)
### Service Design
- All token movements must go through the Transfer Service
- Services should not directly interact with each other
- External economies register themselves with the Transfer Service
- Prediction Market only works with registered external economies

### Implementation Patterns
- Use SQLAlchemy 2.0 best practices for database operations
- Maintain timezone-safe datetime handling throughout
- Use Discord's standard time formatting in all UI elements
- Display Discord usernames consistently in all modals
- Follow established patterns in `bot.py` for initialization
- Use `/database/models.py` as the source of truth for data structures
### User Commands

#### Creating Predictions
```
/create_prediction question:"Who will win?" options:"Team A,Team B" end_time:"2h"
```
- `question`: The prediction question (required)
- `options`: Comma-separated list of possible outcomes (required)
- `end_time`: When the prediction ends (e.g., "2h", "1d", "30m") (required)
- `category`: Optional category for the prediction

#### Viewing Predictions
```
/predictions [show_all:True/False]
```
- Shows active predictions by default
- Use `show_all:True` to see resolved predictions too
- Displays:
  - Prediction questions
  - Current pool sizes
  - Time remaining
  - Available options

#### Placing Bets
```
/bet
```
Interactive command that guides you through:
1. Selecting a prediction
2. Choosing your predicted outcome
3. Selecting point type (local/external economies)
4. Entering bet amount

#### Resolving Predictions
```
/resolve
```
For prediction creators only:
1. Select your prediction to resolve
2. Choose the winning option
3. Confirm to process payouts

#### Refunding Predictions
```
/refund
```
For prediction creators only:
- Refunds all bets for a prediction
- Useful for cancelled events or errors

### Point System

- Users can bet points from different economies
- Winning bets earn proportional shares of the total pool
- Payouts are automatically processed on resolution
- Points are returned for refunded predictions

### Examples

1. Creating a prediction:
```
/create_prediction question:"Will it rain tomorrow?" options:"Yes,No" end_time:"24h"
```

2. Viewing active predictions:
```
/predictions
```

3. Placing a bet:
```
/bet
[Select prediction from dropdown]
[Select your prediction]
[Choose point type]
[Enter amount]
```

4. Resolving a prediction:
```
/resolve
[Select prediction]
[Choose winning option]
[Confirm]
```

## Project Structure
```
FoxBot/
├── bot.py                    # Main entry point and initialization
├── cogs/
│   ├── local_economy.py      # Core economy & transfer service init
│   ├── hackathon_economy.py  # External economy implementation
│   └── prediction_market.py  # Prediction market commands & UI
├── services/
│   ├── transfer_service.py   # Central token movement handling
│   ├── local_points.py       # Local economy service
│   └── prediction_market.py  # Prediction market logic
└── database/
    ├── models.py             # SQLAlchemy models
    └── database.py           # Database connection handling
```

## Development Guidelines

### Adding New External Economies
1. Create new economy service implementing standard interface
2. Create new economy cog that registers with Transfer Service
3. Add to cog_load_order in bot.py (after local_economy, before prediction_market)
4. Economy automatically becomes available for prediction markets

### Shutdown Sequence
- Services and cogs are shut down in reverse order of initialization
- Ensures proper cleanup of resources and database connections
- Follows pattern established in bot.py close() method

1. Clone the repository
2. Install dependencies:
```
pip install -r requirements.txt
```
3. Set up environment variables:
```
DISCORD_TOKEN=your_bot_token
DATABASE_URL=your_database_url
```
4. Run the bot:
```
python main.py
```

## Permissions Required

The bot needs these Discord permissions:
- Send Messages
- Embed Links
- Add Reactions
- Use External Emojis
- Use Slash Commands

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

[Your License Here]