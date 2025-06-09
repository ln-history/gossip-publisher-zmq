import io
import struct
from model.internal.DeleteChannel import DeleteChannel

def parse(data: bytes) -> DeleteChannel:
    b = io.BytesIO(data)
    short_channel_id = struct.unpack(">Q", b.read(8))[0]
    return DeleteChannel(short_channel_id=short_channel_id)