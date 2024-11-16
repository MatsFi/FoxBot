from datetime import datetime
from typing import List
"""Custom exceptions for the Discord bot."""

class BotError(Exception):
    """Base exception for all bot-related errors."""
    pass

class DatabaseError(BotError):
    """Raised when a database operation fails."""
    pass

class APIError(BotError):
    """Raised when an API request fails."""
    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code

class PointsError(BotError):
    """Base class for points-related errors."""
    pass

class InsufficientPointsError(PointsError):
    """Raised when a user has insufficient points for an operation."""
    def __init__(self, user_id: str, required: int, available: int):
        self.user_id = user_id
        self.required = required
        self.available = available
        message = f"User {user_id} has insufficient points. Required: {required}, Available: {available}"
        super().__init__(message)

class InvalidAmountError(PointsError):
    """Raised when an invalid points amount is provided."""
    def __init__(self, amount: int):
        self.amount = amount
        message = f"Invalid points amount: {amount}. Amount must be positive."
        super().__init__(message)

class PredictionMarketError(Exception):
    """Base exception for prediction market errors."""
    pass

class PredictionNotFoundError(PredictionMarketError):
    """Raised when a prediction cannot be found."""
    def __init__(self, prediction_id: int):
        self.prediction_id = prediction_id
        super().__init__(f"Prediction {prediction_id} not found")

class PredictionAlreadyResolvedError(PredictionMarketError):
    """Raised when attempting to modify a resolved prediction."""
    def __init__(self, prediction_id: int):
        self.prediction_id = prediction_id
        super().__init__(f"Prediction {prediction_id} has already been resolved")

class BettingPeriodEndedError(PredictionMarketError):
    """Raised when attempting to bet after the betting period has ended."""
    def __init__(self, prediction_id: int, end_time: datetime):
        self.prediction_id = prediction_id
        self.end_time = end_time
        super().__init__(
            f"Betting period for prediction {prediction_id} "
            f"ended at {end_time.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )

class InvalidOptionError(PredictionMarketError):
    """Raised when an invalid option is provided."""
    def __init__(self, option: str, valid_options: List[str]):
        self.option = option
        self.valid_options = valid_options
        super().__init__(
            f"Invalid option '{option}'. Valid options are: {', '.join(valid_options)}"
        )

class UnauthorizedResolutionError(PredictionMarketError):
    """Raised when a user attempts to resolve a prediction they didn't create."""
    def __init__(self, prediction_id: int, user_id: str):
        self.prediction_id = prediction_id
        self.user_id = user_id
        super().__init__(
            f"User {user_id} is not authorized to resolve prediction {prediction_id}"
        )

class PredictionAlreadyRefundedError(PredictionMarketError):
    """Raised when attempting to refund an already refunded prediction."""
    def __init__(self, prediction_id: int):
        self.prediction_id = prediction_id
        super().__init__(f"Prediction {prediction_id} has already been refunded")

class InvalidPredictionDurationError(PredictionMarketError):
    """Raised when prediction duration is invalid."""
    def __init__(self, minutes: int, min_minutes: int, max_minutes: int):
        self.minutes = minutes
        self.min_minutes = min_minutes
        self.max_minutes = max_minutes
        super().__init__(
            f"Invalid prediction duration: {minutes} minutes. "
            f"Duration must be between {min_minutes} and {max_minutes} minutes"
        )