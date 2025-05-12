import io
import struct
from model.internal.ChannelAmount import ChannelAmount

def parse(data: bytes) -> ChannelAmount:
    b = io.BytesIO(data)
    satoshis = struct.unpack(">Q", b.read(8))[0]
    return ChannelAmount(satoshis=satoshis)