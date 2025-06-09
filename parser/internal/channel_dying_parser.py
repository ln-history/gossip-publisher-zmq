import io
import struct
from model.internal.ChannelDying import ChannelDying

def parse(data: bytes) -> ChannelDying:
    b = io.BytesIO(data)
    short_channel_id = struct.unpack(">Q", b.read(8))[0]
    blockheight = struct.unpack(">I", b.read(4))[0]
    return ChannelDying(short_channel_id=short_channel_id, blockheight=blockheight)