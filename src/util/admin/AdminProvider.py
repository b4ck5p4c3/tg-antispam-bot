import os
import time
from logging import Logger

import requests


class AdminProvider:
    """Provides a list of admin users"""

    def is_admin(self, user_id: int) -> bool:
        raise NotImplementedError()
