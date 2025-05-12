from dataclasses import dataclass, asdict

@dataclass
class GossipStoreEnded:
    """Type 4105: Marks the end of the gossip_store file."""
    equivalent_offset: int  # u64

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return f"GossipStoreEnded(equivalent_offset={self.equivalent_offset})"