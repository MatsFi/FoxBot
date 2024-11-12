# Name: FFS (Multi-Economy Discord Bot)

## Description
A Discord bot that provides a modular framework for connecting multiple Drip economies within a meta-gaming environment.
This enables existing Drip economies to expand their project audience by connecting diverse points economies within a 
single gaming platform. 

## Target Group
The reference target audience is Thesis (t*) users broadly and Mezo and Acre specifically, as both already integrate Drip 
within their respective Discord servers. Forward looking, additional Drip-enabled ecosystems may be easily integrated to 
expand the userbase and circulate tokens between economies. Drip may use this to enable multi-currency economies.

## Features

### Token Mixer Lottery (mostly working, playable)
The initial proof of concept game is a token mixer/lottery where players from any connected Drip points economy may add their 
points into the Mixer for a change to win a share of the pot of tokens when the drawing is held. It is expected ecosystem 
managers will _donate_ points into the mixer so it becomes a faucet for points distribution for players. 
0. `/mixer_init [ duration ]` in minutes (<5 for testing)
1. `/mixer_add [ amount ] [ token ] [ is_donation ]` multiple players add tokens from any connected points economy and receive a ticket. Setting the __is_donation__ flag will not provide a ticket for the drawing.
2. `/mixer_status` display details about the current drawing
3. `/mixer_results [ drawingID ]` see the results of recent drawings, or details of a specific ID

### Staminah Mining (code provided, but not running)
The flagship game is Staminah, an ecosystem of virtual miners and DeFi degens. Players deposit their MATS, BEES and other 
external connected Drip tokens into Staminah at a rate of 1 external point for 10,000 STAM tokens. STAM enables players
to purchase in-game items and power them up. Foremost is procuring a Miner from the Marketplace. Miners consume STAM tokens at
a user-configured rate per minute and convert these tokens into Work. The Staminah blockchain rewards the single Miner with the
most Work produced in the previous 1 minute with the block reward of 5 CORN. Each week the block reward reduces by 53/69 until 
all 210,000 CORN have been issued. Each Miner continues to accumulate Work until they produce a block, then their Work is reset 
to zero. Even a low STAM consumption rate will yield a block at some point. These coveted CORN tokens can be used within Staminah
DeFi games, or converted to external tokens.

1. `staminah_deposit [ amount]` Deposit external 1 token, receive 10,000 STAM
2. `staminah_withdraw [ amount ]` Withdraw 10,000 STAM, receive 1 external token
3. `buy_miner [ type ]` Select between Basic, Beige or Boujee miners and get ready
4. `configure_miner [ rate ]` Configure your miner's STAM consumption rate to convert into Work
5. `add_stam [ amount ]` Your miner needs STAM to get them CORN, so fill it up
6. `toggle_miner` Turn your miner _on_ to raise your Total Work or _off_ (hfsp)
7. `miner_status` Check your miner's status and its current stats
8. `game_stats` View current game stats such as average Work in recent blocks and how much CORN remains
9. `leaderboard` Where do you stand in the Miner arms race?

### Corn Staking (conceptual design, no code)
So, you've got a bunch of CORN from mining, you'll want to plant those into a DeFi app so you can harvest MATS and Bees.
Lots of opportunities for mini-games here, from staking, to AMM, to loans and much more. Get your Degen on!

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

## Unique Value Proposition
FFS Multi-Economy Discord Bot provides community scaling opportunities for Drip-enabled Discord servers. Thesis is
already using Drip with Mezo and Acre, as are some of their partner projects. Combining communities within a fun
and engaging environment should provide more opportunities to cultivate a thriving t* ecosystem.

## Next Steps & Milestones
- Week 1: debug mixer logic for random drawings, refactor commands into abstracts rather than specific to each economy
- Week 2: test mixer, debug Staminah mining, develop corn staking
- Week 3: test Staminah mining + corn staking/harvesting
- Week 4: deploy to t* Discord servers, launch Staminah mining

## Requirements/Expectations from Mezo & Drip for implementation
- Guidance on product market fit
- Support with external points into Local economy, mining and mixer
- Assistance designing proper engagement analytics into the games

## Team Information
Ryan R. Fox
Peteya2
Sonny Monroe

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

