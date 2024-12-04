# FoxBot Discord Bot

A Discord bot featuring a sophisticated prediction market system that integrates with multiple token economies. The system follows a service-oriented architecture with clear separation of concerns.

## System Architecture

### Component Overview
```plaintext
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│     Discord     │     │    FoxBot UI    │     │  Business Logic │
│   Interactions  │────▶│      Layer      │────▶│     Services    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │                         │
                               │                         │
                        ┌─────────────────┐     ┌─────────────────┐
                        │   Transfer &    │     │    Database     │
                        │ Economy Service │◀───▶│      Layer      │
                        └─────────────────┘     └─────────────────┘
```

### Project Structure
```plaintext
FoxBot/
├── bot.py                         # Main entry point and initialization
├── cogs/
│   ├── prediction_market.py       # Command handlers and coordination
│   ├── local_economy.py          # Local economy command handlers
│   ├── hackathon_economy.py      # External economy integration
│   └── views/                    # UI Components
│       ├── prediction_market_views.py  # Market display
│       ├── betting_views.py           # Betting interface
│       └── resolution_views.py        # Resolution interface
├── services/
│   ├── transfer_service.py       # Central token movement handler
│   ├── local_points.py          # Local economy service
│   └── prediction_market.py      # Market business logic
└── database/
    ├── models.py                # SQLAlchemy models
    └── database.py             # Database connection handling
```

## Component Responsibilities

### Cogs Layer
- **Purpose**: Handle Discord commands and coordinate between UI and services
- **Responsibilities**:
  - Command registration and handling
  - Input validation
  - User permission checks
  - Error handling and user feedback
  - Coordination between UI and services

### Views Layer
- **Purpose**: Manage UI components and user interactions
- **Responsibilities**:
  - Market display and updates
  - Betting interface
  - Resolution interface
  - Auto-updating displays
  - User interaction handling

### Services Layer
- **Purpose**: Implement business logic and manage data operations
- **Components**:
  1. **Transfer Service**
     - Central authority for token movements
     - Validates and executes transfers
     - Maintains transaction history
  
  2. **Prediction Market Service**
     - Market creation and management
     - Bet placement and resolution
     - Price calculations
     - Liquidity management
  
  3. **Economy Services**
     - Token balance management
     - Economy-specific operations
     - Integration with external systems

### Database Layer
- **Purpose**: Data persistence and model definitions
- **Components**:
  - SQLAlchemy models
  - Database connection management
  - Transaction handling

## Data Flow

### Betting Flow
```plaintext
User ─┐
      │    ┌───────────┐    ┌──────────┐    ┌─────────────┐
      ├───▶│   View    │───▶│   Cog    │───▶│  PM Service │
      │    └───────────┘    └──────────┘    └─────────────┘
      │                                            │
      │    ┌───────────┐    ┌──────────┐          │
      └───▶│ Transfer  │◀───│ Database │◀─────────┘
           │  Service  │    │  Layer   │
           └───────────┘    └──────────┘
```

### Market Resolution Flow
```plaintext
Creator ──┐
          │    ┌───────────┐    ┌──────────┐    ┌─────────────┐
          ├───▶│   View    │───▶│   Cog    │───▶│  PM Service │
          │    └───────────┘    └──────────┘    └─────────────┘
          │                                            │
          │    ┌───────────┐    ┌──────────┐          │
          └───▶│ Transfer  │◀───│ Database │◀─────────┘
               │  Service  │    │  Layer   │
               └───────────┘    └──────────┘
```

## Best Practices

### Code Organization
1. **Separation of Concerns**
   - UI logic stays in views
   - Business logic in services
   - Database operations in models
   - Command handling in cogs

2. **Error Handling**
   - Comprehensive try/except blocks
   - Proper error logging
   - User-friendly error messages
   - Transaction rollback on failure

3. **Type Safety**
   - Use type hints
   - Validate inputs
   - Document return types
   - Use SQLAlchemy 2.0 typing

### Database Operations
1. **Session Management**
   - Use async sessions
   - Proper transaction handling
   - Session cleanup
   - Error recovery

2. **Query Optimization**
   - Use eager loading when appropriate
   - Minimize database calls
   - Index frequently queried fields
   - Monitor query performance

### UI Components
1. **View Management**
   - Timeout handling
   - Resource cleanup
   - Auto-update management
   - Error recovery

2. **User Experience**
   - Clear feedback
   - Consistent styling
   - Responsive updates
   - Intuitive interactions

## Development Guidelines

### Adding New Features
1. Plan the feature across all layers
2. Update models if needed
3. Implement service layer logic
4. Create or update UI components
5. Add command handlers
6. Update documentation

### Testing Requirements
1. Unit tests for services
2. Integration tests for cogs
3. UI component testing
4. Database operation testing
5. Error handling verification

### Documentation Standards
1. Clear method documentation
2. Type hints and return types
3. Example usage
4. Error scenarios
5. Architecture updates

## Golden Rules
1. All token movements MUST go through Transfer Service
2. Always use proper error handling
3. Maintain separation of concerns
4. Document all changes
5. Test thoroughly
6. Follow established patterns