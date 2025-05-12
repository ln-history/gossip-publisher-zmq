from dataclasses import dataclass, asdict

@dataclass
class ChannelDying:
    """Type 4106: Indicates a funding tx was spent; scheduled for deletion."""
    scid: int  # u64
    blockheight: int  # u32

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return f"ChannelDying(scid={self.scid}, blockheight={self.blockheight})"