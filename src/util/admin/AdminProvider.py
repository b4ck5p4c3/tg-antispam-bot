class AdminProvider:
    """Provides a list of admin users"""

    async def is_admin(self, user_id: int, chat_id: int) -> bool:
        raise NotImplementedError()

    async def is_admin_with_request(self, user_id: int, chat_id: int, telegram_request) -> bool:
        """External providers need no Telegram budget; Telegram providers override."""
        return await self.is_admin(user_id, chat_id)
