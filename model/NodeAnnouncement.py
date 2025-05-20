import struct
from io import BytesIO
from dataclasses import dataclass

from parser.common import decode_alias
from model.TLVRecord import parse_address_descriptor

@dataclass
class NodeAnnouncement:
    signature: bytes
    features: bytes
    timestamp: int
    node_id: bytes
    rgb_color: bytes
    alias: bytes
    addresses: bytes  # TLV-encoded

    def __str__(self) -> str:
        address_list = {
            t: parse_address_descriptor(record.value)
            for t, record in self.addresses.items()
        }
        return (
            f"NodeAnnouncement(node_id={self.node_id.hex()}, timestamp={self.timestamp}, "
            f"features={self.features.hex()}, signature={self.signature.hex()}, "
            f"alias={decode_alias(self.alias)}, rgb_color={self.rgb_color.hex()}, "
            f"addresses={address_list})"
        )

    def to_dict(self) -> dict:
        return {
            "signature": self.signature.hex(),
            "features": self.features.hex(),
            "timestamp": self.timestamp,
            "node_id": self.node_id.hex(),
            "rgb_color": self.rgb_color.hex(),
            "alias": decode_alias(self.alias),
            "addresses": {
                t: parse_address_descriptor(r.value)
                for t, r in self.addresses.items()
            },
        }
