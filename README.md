# Low Poly Market Discord Bot

A Discord bot featuring a prediction market system that integrates with multiple external token economies.

## Overview

Low Poly Market implements a sophisticated prediction market system allowing users to bet tokens from various external economies on user-created predictions. The system is designed with strict separation of concerns, robust error handling, and follows a service-oriented architecture.

## Core Features

- Prediction Market System with automated resolution
- Real-time Market Updates
- Automated Notifications
- Multiple External Economy Integration
- Interactive Discord UI
- Comprehensive Logging System

## System Architecture

### Component Overview
- **Bot Core**: Central coordinator and service manager
- **Economy System**: Handles token management across economies
- **Prediction Market**: Manages betting markets and resolutions
- **Transfer Service**: Coordinates all token movements
- **Database Layer**: Persistent storage using SQLAlchemy 2.0

### Service Layer
- **Transfer Service**: Central hub for all token movements
- **Local Points Service**: Internal economy management
- **External Economy Services**: External token system interfaces
- **Prediction Market Service**: Market logic and resolution handling

### Cog Layer
- **Local Economy Cog**: Core economy initialization
- **External Economy Cogs**: External economy interfaces
- **Prediction Market Cog**: User interface and command handling

## Initialization Sequence

1. Bot Startup
   - Database connection establishment
   - Service initialization
   - Cog loading in specified order

2. Service Initialization Order
   - Local Economy (initializes transfer service)
   - External Economies (register with transfer service)
   - Prediction Market (uses registered economies)

3. Command Registration
   - Slash command synchronization
   - View registration
   - Event handler setup

## Core Design Principles

### Golden Rules
1. **Transfer Service Sovereignty**
   - All token movements MUST go through the Transfer Service
   - Services never directly modify token balances
   - Always adapt to Transfer Service interfaces, never modify them

2. **Economy Separation**
   - Local economy cannot participate in prediction markets
   - External economies must register with Transfer Service
   - Prediction Market only accepts external economy tokens

3. **Error Handling**
   - Graceful degradation on failures
   - Comprehensive logging at all levels
   - User-friendly error messages

### Best Practices

1. **Service Communication**
   ```python
   # CORRECT: Use Transfer Service interface
   await self.transfer_service.deposit_to_local(...)
   
   # INCORRECT: Direct service-to-service calls
   await external_service.remove_points(...)
   ```

2. **Economy Management**
   ```python
   # Get available economies from transfer service
   external_economies = list(self.bot.transfer_service._external_services.keys())
   ```

3. **Error Handling**
   ```python
   try:
       await self.process_transaction(...)
   except TransferError as e:
       self.logger.error(f"Transfer failed: {e}")
       await self.notify_user(...)
   ```

## Detailed Implementation Guidelines

### Adding New External Economies
1. Create economy service implementing standard interface
2. Create economy cog that registers with Transfer Service
3. Add to cog_load_order in bot.py
4. Economy automatically becomes available for prediction markets

### Transaction Flow
1. User initiates action (bet, resolution)
2. Service validates request
3. Transfer Service handles token movement
4. Database updates transaction record
5. User notification sent

### Notification System
- Automated notifications for:
  - Market creation
  - Betting period end
  - Market resolution
  - Payout distribution
  - Error conditions

### Logging Strategy
- DEBUG: Detailed flow information
- INFO: Major state changes
- WARNING: Recoverable issues
- ERROR: Critical failures
- Include relevant context in log messages

## Development Guidelines

### Code Style
- Use type hints
- Document public methods
- Include error handling
- Log meaningful events
- Follow PEP 8

### Testing Requirements
- Unit tests for services
- Integration tests for cogs
- Mock external services
- Test error conditions
- Verify logging output

### Deployment Considerations
- Environment configuration
- Database migrations
- Discord permissions
- External service credentials
- Logging setup