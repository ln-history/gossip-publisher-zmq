import io
import struct
from model.ChannelUpdate import ChannelUpdate

def parse(data: bytes) -> ChannelUpdate:
    b = io.BytesIO(data)

    signature = b.read(64)
    chain_hash = b.read(32)[::-1]  # Convert from little-endian
    short_channel_id = struct.unpack(">Q", b.read(8))[0]
    timestamp = struct.unpack(">I", b.read(4))[0]
    message_flags = b.read(1)
    channel_flags = b.read(1)
    cltv_expiry_delta = struct.unpack(">H", b.read(2))[0]
    htlc_minimum_msat = struct.unpack(">Q", b.read(8))[0]
    fee_base_msat = struct.unpack(">I", b.read(4))[0]
    fee_proportional_millionths = struct.unpack(">I", b.read(4))[0]

    # Conditionally read optional field
    htlc_maximum_msat = None
    if message_flags[0] & 1:  # Check if least significant bit is set
        htlc_maximum_msat = struct.unpack(">Q", b.read(8))[0]

    return ChannelUpdate(
        signature=signature,
        chain_hash=chain_hash,
        short_channel_id=short_channel_id,
        timestamp=timestamp,
        message_flags=message_flags,
        channel_flags=channel_flags,
        cltv_expiry_delta=cltv_expiry_delta,
        htlc_minimum_msat=htlc_minimum_msat,
        fee_base_msat=fee_base_msat,
        fee_proportional_millionths=fee_proportional_millionths,
        htlc_maximum_msat=htlc_maximum_msat
    )
