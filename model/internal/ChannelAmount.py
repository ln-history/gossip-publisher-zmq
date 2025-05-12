from dataclasses import dataclass, asdict

@dataclass
class ChannelAmount:
    """Type 4101: Contains the actual capacity of a public channel."""
    satoshis: int # u64

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return f"ChannelAmount(satoshis={self.satoshis})"