from dataclasses import dataclass
from parser.common import decode_alias, parse_tlv_stream, parse_address_descriptor

@dataclass
class NodeAnnouncement:
    signature: bytes
    features: bytes
    timestamp: int
    node_id: bytes
    rgb_color: bytes
    alias: bytes
    addresses: dict

    def __str__(self) -> str:
        return (f"NodeAnnouncement(scid={self.node_id}, timestamp={self.timestamp}, "
                f"features={self.features}, signature={self.signature}, "
                f"cltv_delta={self.alias}, rgb_color={self.rgb_color}, "
                f"addresses={[parse_address_descriptor(rec.value) for rec in parse_tlv_stream(self.addresses).values()]}")

    def to_dict(self) -> dict:
        return {
            "signatures": self.signature.hex(),
            "features": self.features.hex(),
            "timestamp": self.timestamp,
            "node_id": self.node_id.hex(),
            "rgb_color": self.rgb_color.hex(),
            "alias": decode_alias(self.alias),
            "addresses": [
                parse_address_descriptor(rec.value)
                for rec in self.addresses.values()
            ]
        }