"""Initialize cogs package."""
from .local_economy import LocalEconomy
from .hackathon_economy import HackathonEconomy
from .ffs_economy import FFSEconomy
from .economy_cog_template import ExternalEconomyCog

__all__ = [
    'LocalEconomy', 
    'HackathonEconomy', 
    'FFSEconomy', 
    'ExternalEconomyCog'
]