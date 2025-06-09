from dataclasses import dataclass

@dataclass
class ChannelDying:
    """Type 4106: Indicates a funding tx was spent; scheduled for deletion."""
    short_channel_id: int  # u64
    blockheight: int  # u32

    @property
    def short_channel_id_str(self):
        block = (self.short_channel_id >> 40) & 0xFFFFFF
        txindex = (self.short_channel_id >> 16) & 0xFFFFFF
        output = self.short_channel_id & 0xFFFF
        return f"{block}x{txindex}x{output}"

    def to_dict(self) -> dict:
        return {
            "short_channel_id": self.short_channel_id_str,
            "blockheight": self.blockheight
        }

    def __str__(self) -> str:
        return f"ChannelDying(scid={self.short_channel_id_str}, blockheight={self.blockheight})"