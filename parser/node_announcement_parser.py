import struct
import io
from model.NodeAnnouncement import NodeAnnouncement
from parser.common import parse_tlv_stream


def parse(data: bytes) -> NodeAnnouncement:
    b = io.BytesIO(data)

    signature = b.read(64)

    features_len = struct.unpack(">H", b.read(2))[0]
    features = b.read(features_len)

    timestamp = struct.unpack(">I", b.read(4))[0]
    node_id = b.read(33)
    rgb_color = b.read(3)
    alias = b.read(32)

    # Remaining data is TLV-encoded addresses
    address_data = b.read()
    addresses = parse_tlv_stream(address_data)

    return NodeAnnouncement(
        signature=signature,
        features=features,
        timestamp=timestamp,
        node_id=node_id,
        rgb_color=rgb_color,
        alias=alias,
        addresses=addresses
    )