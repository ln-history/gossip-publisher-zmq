from dataclasses import dataclass

@dataclass
class PrivateChannelUpdate:
    """Type 4102: Private channel update corresponding to a private channel."""
    update: bytes  # u8[len], len: u16

    def to_dict(self) -> dict:
        return {
            "update": self.update.hex()
        }

    def __str__(self) -> str:
        return f"PrivateChannelUpdate(update={self.update.hex()[:40]}...)"
