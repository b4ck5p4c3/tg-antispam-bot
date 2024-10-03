class AdminProvider:
    """Provides a list of admin users"""
    #TODO: Temporary implementation. Replace with swincya api when egor is sdelaet it

    def __init__(self):
        self.admins = []

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admins