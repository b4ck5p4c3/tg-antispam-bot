class AdminProvider:
    """Provides a list of admin users"""

    async def is_admin(self, user_id: int, chat_id: int) -> bool:
        raise NotImplementedError()
