import io
import struct
from model.internal.DeleteChannel import DeleteChannel

def parse(data: bytes) -> DeleteChannel:
    b = io.BytesIO(data)
    scid = struct.unpack(">Q", b.read(8))[0]
    return DeleteChannel(scid=scid)