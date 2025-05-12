from dataclasses import dataclass, asdict

@dataclass
class DeleteChannel:
    """Type 4103: Indicates deletion of a channel."""
    scid: int  # u64

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return f"DeleteChannel(scid={self.scid})"
