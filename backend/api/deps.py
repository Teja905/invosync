"""Shared FastAPI dependencies for route modules."""

from config.settings import default_user


async def get_authenticated_user() -> dict:
    """Demo mode: return default user without auth."""
    return await default_user()
