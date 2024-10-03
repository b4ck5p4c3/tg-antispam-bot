import json


class JsonDB:
    def __init__(self, db_path):
        self.db_path = db_path

    def read_or_default(self, default):
        try:
            with open(self.db_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return default

    def write(self, data):
        with open(self.db_path, 'w') as f:
            json.dump(data, f, indent=4)