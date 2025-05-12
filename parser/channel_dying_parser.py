import io
import struct
from model.internal.ChannelDying import ChannelDying

def parse(data: bytes) -> ChannelDying:
    b = io.BytesIO(data)
    scid = struct.unpack(">Q", b.read(8))[0]
    blockheight = struct.unpack(">I", b.read(4))[0]
    return ChannelDying(scid=scid, blockheight=blockheight)