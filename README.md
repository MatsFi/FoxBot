# FFS (Multi-Economy Discord Bot)

A Discord bot that provides a modular framework for connecting multiple Drip economies within a meta-gaming environment.
This enables existing Drip economies to expand their project audience by connecting diverse points economies within a 
single gaming platform. 

The reference target audiance is Thesis (t*) users broadly and Mezo and Acre specifically, as both already integrate Drip 
within their respective Discord servers. Forward looking, additional Drip-enabled ecosystems may be easily integrated to 
expand the userbase and circulate tokens between economies.

## Usage for Players (games)

### Token Mixer Lottery
The initial game is a token mixer/lottery where players from any connected Drip points economy may add their points into
the Mixer for a change to win a share of the pot of tokens when the drawing is held. It is expected ecosystem managers
will _donate_ points into the mixer so it becomes a faucet for points distribution. 
0. `/mixer_init [ duration ]` in minutes (admin only)
1. `/mixer_add [ amount ] [ token ] [ is_donation ]` players add tokens from any connected points economy and receive a ticket
2. `/mixer_status` display details about the current drawing
3. `/mixer_results [ drawingID ]` see the results of recent drawings, or details of a specific ID

### Local Economy (Example: Thesis)
A local database stores transaction records to ensure points move 1:1 between disparate connected Drip points economies
using the proper `..._deposit` or `..._withdraw` commands (see Economies below). 
`/local_balance` displays balance of local points
`/local_leaderboard` who is king of t* points

### Hackathon Economy (example: Mezo MATS points)
`/hackathon_deposit [ amount ]` debits MATS balance and credits LOCAL balance
`/hackathon_withdraw [ amount ]` debits LOCAL balance and credits MATS balance 

### FFS Economy (example: Acre BEES points)
`/ffs_deposit [ amount ]` debits BEES balance and credits LOCAL balance
`/ffs_withdraw [ amount ]` debits LOCAL balance and credits BEES balance 

# Developer Details

## Project Structure

```
discord_bot/
├── cogs/
│   ├── __init__.py                 # Cog package initialization
│   ├── economy_cog_template.py     # Base class for economy cogs
│   ├── local_economy.py            # Local Economy commands
│   ├── ffs_economy.py              # FFS Economy commands
│   ├── hackathon_economy.py        # Hackathon Economy commands
│   └── mixer_economy.py            # Mixer/Lottery commands
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
│   ├── mixer_service.py                # Mixer economy service
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

1. **Separation of Concerns**
   - Each economy is managed by its own cog and service
     - Local economy is operated by this bot
     - FFS economy is an external Drip environment
     - Hackathon economy is the external Drip Hackathon environment
   - Transfer logic is centralized in the transfer service proving deposit/withdraw for external<>local
   - Database operations are isolated in the database layer and persist Local economy Player activities

2. **Interface-Based Design**
   - External economies implement a common interface
   - Adapters provide consistent interaction with external APIs
   - Standard transfer result format across all operations

3. **Fail-Safe Operations**
   - Transactions are verified before and after execution
   - Rollback mechanisms for failed operations
   - Comprehensive error handling and logging

4. **Extensibility**
   - Easy addition of new economies through the adapter pattern
   - Common base classes for economy cogs
   - Centralized configuration management

## Core Components

### Services Layer

1. **TransferInterface (`transfer_interface.py`)**
   - Defines `ExternalEconomyInterface` for external economies
   - Provides `TransferResult` dataclass for operation results

2. **ExternalServiceAdapters (`external_service_adapters.py`)**
   - Base adapter for external economy services
   - Specific adapters for FFS and Hackathon economies
   - Implements the external economy interface

3. **TransferService (`transfer_service.py`)**
   - Manages cross-economy transfers
   - Handles transaction verification and rollback
   - Provides consistent error handling

### Cogs Layer

1. **Economy Cog Template (`economy_cog_template.py`)**
   - Base class for economy cogs
   - Common command implementations
   - Standardized error handling

2. **Economy Cogs**
   - **Local Economy**: Database-backed point system
   - **FFS Economy**: External API integration
   - **Hackathon Economy**: External API integration

## Key Features

1. **Point Management**
   - Balance checking
   - Point transfers between users
   - Cross-economy deposits and withdrawals
   - Leaderboard functionality

2. **Administrative Tools**
   - Point minting (admin only)
   - User balance management
   - Debug commands

3. **Security**
   - Transaction verification
   - Automatic rollback on failure
   - Admin command restrictions

4. **Error Handling**
   - Comprehensive logging
   - User-friendly error messages
   - Transaction rollback on failure

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