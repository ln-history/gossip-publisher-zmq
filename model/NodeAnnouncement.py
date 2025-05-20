import io
from dataclasses import dataclass

from parser.common import decode_alias, parse_address

from typing import List, Any

@dataclass
class NodeAnnouncement:
    signature: bytes
    features: bytes
    timestamp: int
    node_id: bytes
    rgb_color: bytes
    alias: bytes
    addresses: bytes  

    def _parse_addresses(self) -> List[Any]:
        address_stream = io.BytesIO(self.addresses)
        address_len = len(self.addresses)
        parsed_addresses = []

        while address_stream.tell() < address_len:
            addr = parse_address(address_stream)
            if addr:
                parsed_addresses.append(addr)
            else:
                break
        
        return parsed_addresses

    def __str__(self) -> str: 
        return (
            f"NodeAnnouncement(node_id={self.node_id.hex()}, timestamp={self.timestamp}, "
            f"features={self.features.hex()}, signature={self.signature.hex()}, "
            f"alias={decode_alias(self.alias)}, rgb_color={self.rgb_color.hex()}, "
            f"addresses={self._parse_addresses()})"
        )

    def to_dict(self) -> dict:
        return {
            "signature": self.signature.hex(),
            "features": self.features.hex(),
            "timestamp": self.timestamp,
            "node_id": self.node_id.hex(),
            "rgb_color": self.rgb_color.hex(),
            "alias": decode_alias(self.alias),
            "addresses": [addr.to_dict() for addr in self._parse_addresses()]
        }