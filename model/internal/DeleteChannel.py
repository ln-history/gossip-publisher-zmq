from dataclasses import dataclass

@dataclass
class DeleteChannel:
    """Type 4103: Indicates deletion of a channel."""
    scid: int  # u64

    @property
    def short_channel_id_str(self):
        block = (self.short_channel_id >> 40) & 0xFFFFFF
        txindex = (self.short_channel_id >> 16) & 0xFFFFFF
        output = self.short_channel_id & 0xFFFF
        return f"{block}x{txindex}x{output}"

    def to_dict(self) -> dict:
        return {
            "short_channel_id": self.short_channel_id_str
        }

    def __str__(self) -> str:
        return f"DeleteChannel(scid={self.short_channel_id_str})"
