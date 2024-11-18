# FoxBot Discord Bot

A Discord bot featuring a prediction market system using cross-economy points.

## Prediction Market System

The prediction market allows users to create predictions, place bets, and earn points based on correct predictions.

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
├── cogs/
│   └── prediction_market.py     # Main prediction market commands
├── database/
│   ├── models.py                # Database models
│   └── database.py              # Database connection handling
├── services/
│   ├── prediction_market_service.py  # Business logic
│   └── points_service.py        # Points management
└── main.py                      # Bot initialization
```

### Key Components

- **Prediction Market Cog**: Handles Discord commands and UI
- **Database Models**: Defines prediction and bet data structures
- **Services**: Manages business logic and data operations
- **Utils**: Helper functions and utilities

## Setup

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