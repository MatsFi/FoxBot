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