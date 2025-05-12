from dataclasses import dataclass

@dataclass
class PrivateChannelAnnouncement:
    """Type 4104: Represents a private channel with announcement data."""
    amount_sat: int  # u64
    announcement: bytes  # u8[len], len: u16

    def to_dict(self) -> dict:
        return {
            "amount_sat": self.amount_sat,
            "announcement": self.announcement.hex()
        }

    def __str__(self) -> str:
        return f"PrivateChannel(amount_sat={self.amount_sat}, announcement={self.announcement.hex()[:40]}...)"

