# Prediction Market Integration

This document outlines the integration of user interface components from `lpm.py` into the prediction market system, detailing command mappings, UI transformations, database interactions, and user flow changes.

## Command Mappings

### `/create_prediction`
- **Original Functionality**: Allows users to create a new prediction market.
- **Current Implementation**: 
  - **UI Elements**: Uses a modal to gather prediction details (question, options, end time).
  - **Database Mapping**: 
    - `Prediction` table stores the question, options, creator ID, and end time.
  - **Flow**: 
    1. User invokes `/create_prediction`.
    2. Modal collects input.
    3. Data is validated and stored in the database.
    4. Confirmation message sent to user.

### `/bet`
- **Original Functionality**: Users place bets on active predictions.
- **Current Implementation**:
  - **UI Elements**: 
    - Dropdown for bet amount.
    - Optional economy selection if multiple economies are available.
  - **Database Mapping**:
    - `Bet` table records user ID, prediction ID, option ID, amount, and economy.
  - **Flow**:
    1. User selects prediction and option.
    2. Dropdown for bet amount appears.
    3. Economy selection shown if needed.
    4. Bet is validated and stored.
    5. Confirmation message sent.

### `/list_predictions`
- **Original Functionality**: Lists all active and pending predictions.
- **Current Implementation**:
  - **UI Elements**: 
    - Embed displays active and pending predictions.
  - **Database Mapping**:
    - Queries `Prediction` table for active and pending predictions.
  - **Flow**:
    1. User invokes `/list_predictions`.
    2. Active and pending predictions are fetched.
    3. Embed is constructed and sent to user.

### `/resolve_prediction`
- **Original Functionality**: Allows users to resolve predictions.
- **Current Implementation**:
  - **UI Elements**: 
    - Selection menu for unresolved predictions.
    - Button for selecting winning option.
  - **Database Mapping**:
    - Updates `Prediction` table with winning option and resolution status.
  - **Flow**:
    1. User selects prediction to resolve.
    2. Winning option is selected.
    3. Resolution is processed and stored.
    4. Notifications sent to participants.

## UI Component Transformations

### Selection Menus
- **Original**: Used for selecting predictions and options.
- **Current**: 
  - Enhanced with dynamic content based on user permissions and prediction state.
  - Integrated with Discord's interaction system for real-time updates.

### Buttons
- **Original**: Used for confirming actions.
- **Current**: 
  - Expanded to include economy selection and confirmation of bets.
  - Integrated with error handling for permission issues.

### Views and Modals
- **Original**: Basic input collection.
- **Current**: 
  - Modals used for detailed input collection (e.g., creating predictions).
  - Views manage complex interactions like betting and resolution.

### Notifications
- **Original**: Basic user feedback.
- **Current**: 
  - Automated notifications for market events (creation, resolution).
  - Integrated with Discord's DM system for direct user communication.

## Database Interactions

### Prediction Data Flow
- **Creation**: Data collected via modal, validated, and stored in `Prediction` table.
- **Listing**: Active and pending predictions fetched for display.
- **Resolution**: Winning option updated in `Prediction` table.

### Bet Data Storage
- **Placement**: Bet details stored in `Bet` table.
- **Validation**: Ensures sufficient balance and valid prediction state.

### Resolution Handling
- **Process**: Winning option selected, payouts calculated, and stored.
- **Notifications**: Participants notified of resolution and payouts.

## Sequence Diagrams

### Betting Flow
```plaintext
User -> Bot: /bet
Bot -> User: Select prediction
User -> Bot: Select option
Bot -> User: Select amount
User -> Bot: Confirm bet
Bot -> Database: Store bet
Bot -> User: Confirmation message
```

### Resolution Flow
```plaintext
User -> Bot: /resolve_prediction
Bot -> User: Select prediction
User -> Bot: Select winning option
Bot -> Database: Update prediction
Bot -> User: Resolution confirmation
Bot -> Participants: Send notifications
```

## Method Name Mappings and Transformations

This section tracks the method name changes and transformations between the original `lpm.py` implementation and our current prediction market system.

### Command Methods

#### Prediction Creation
```python
# Original (lpm.py)
@app_commands.command(name="create_prediction")
async def create_prediction_command(self, interaction: discord.Interaction)

# Current (prediction_market.py)
@app_commands.command(name="create_prediction")
async def create_prediction(self, interaction: discord.Interaction)
```

#### Prediction Resolution
```python
# Original (lpm.py)
@app_commands.command(name="resolve_prediction")
async def resolve_prediction_command(self, interaction: discord.Interaction)

# Current (prediction_market.py)
@app_commands.command(name="resolve_prediction")
async def resolve_prediction(self, interaction: discord.Interaction)
```

### Service Methods

#### Resolution Scheduling
```python
# Original (lpm.py)
async def schedule_prediction_resolution(self, prediction: Prediction):
    # Used print statements for debugging
    print(f"DEBUG: Waiting {time_until_betting_ends} seconds for betting to end")

# Current (prediction_market_service.py)
async def schedule_prediction_resolution(self, prediction: Prediction):
    # Uses proper logging
    self.logger.debug(f"Waiting {time_until_betting_ends} seconds for betting to end")
```

#### Bet Processing
```python
# Original (lpm.py)
async def process_bet(self, user_id: int, prediction_id: int, option: str, amount: int)

# Current (prediction_market_service.py)
async def place_bet(
    self,
    prediction_id: int,
    option_id: int,
    user_id: int,
    amount: int,
    economy: str
)
```

## Key Transformations

### Notification System
```python
# Original (lpm.py)
await creator.send(
    f"Betting has ended for your prediction: '{prediction.question}'\n"
    f"Please use `/resolve_prediction` to resolve the market."
)

# Current (prediction_market_service.py)
try:
    creator = await self.bot.fetch_user(prediction.creator_id)
    await creator.send(
        f"Betting has ended for your prediction: '{prediction.question}'\n"
        f"Please use /resolve_prediction to resolve the market.\n"
        f"If not resolved within 48 hours, all bets will be automatically refunded."
    )
    self.logger.debug(f"Sent notification to creator {prediction.creator_id}")
except Exception as e:
    self.logger.error(f"Error notifying creator: {str(e)}", exc_info=True)
```

### View Handling
```python
# Original (lpm.py)
class PredictionSelect(discord.ui.Select):
    def __init__(self, predictions):
        options = [
            discord.SelectOption(
                label=prediction.question[:100],
                description=f"Ended {prediction.end_time.strftime('%Y-%m-%d %H:%M