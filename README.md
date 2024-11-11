# Multi-Economy Discord Bot

A Discord bot that manages multiple point economies with secure transfer capabilities between them.

## Project Structure

```
discord_bot/
├── cogs/
│   ├── __init__.py                 # Cog package initialization
│   ├── economy_cog_template.py     # Base class for economy cogs
│   ├── ffs_economy.py              # FFS Economy commands
│   ├── hackathon_economy.py        # Hackathon Economy commands
│   └── local_economy.py            # Local Economy commands
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
   - Transfer logic is centralized in the transfer service
   - Database operations are isolated in the database layer

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
2. External economies can be loaded in any order after
3. Each external economy registers with the transfer service on load

## Usage

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

[Your License Here]