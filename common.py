import json
from typing import Any

def is_json_serializable(self, obj: Any) -> bool:
        """Check if an object can be serialized to JSON."""
        try:
            json.dumps(obj)
            return True
        except (TypeError, OverflowError):
            return False