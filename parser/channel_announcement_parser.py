import io
import struct
from model.ChannelAnnouncement import ChannelAnnouncement

def parse(data: bytes) -> ChannelAnnouncement:
    b = io.BytesIO(data)

    node_signature_1 = b.read(64)
    node_signature_2 = b.read(64)
    bitcoin_signature_1 = b.read(64)
    bitcoin_signature_2 = b.read(64)

    features_len = struct.unpack(">H", b.read(2))[0]
    features = b.read(features_len)

    chain_hash = b.read(32)[::-1]  # Convert from little-endian
    short_channel_id = struct.unpack(">Q", b.read(8))[0]

    node_id_1 = b.read(33)
    node_id_2 = b.read(33)
    bitcoin_key_1 = b.read(33)
    bitcoin_key_2 = b.read(33)

    return ChannelAnnouncement(
        features=features,
        chain_hash=chain_hash,
        short_channel_id=short_channel_id,
        node_id_1=node_id_1,
        node_id_2=node_id_2,
        bitcoin_key_1=bitcoin_key_1,
        bitcoin_key_2=bitcoin_key_2,
        node_signature_1=node_signature_1,
        node_signature_2=node_signature_2,
        bitcoin_signature_1=bitcoin_signature_1,
        bitcoin_signature_2=bitcoin_signature_2
    )
