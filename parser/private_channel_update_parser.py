import io
import struct
from model.internal.PrivateChannelUpdate import PrivateChannelUpdate

def parse(data: bytes) -> PrivateChannelUpdate:
    b = io.BytesIO(data)
    length = struct.unpack(">H", b.read(2))[0]
    update = b.read(length)
    return PrivateChannelUpdate(update=update)