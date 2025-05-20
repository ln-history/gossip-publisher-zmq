import io
import struct
from model.internal.GossipStoreEnded import GossipStoreEnded

def parse(data: bytes) -> GossipStoreEnded:
    b = io.BytesIO(data)
    equivalent_offset = struct.unpack(">Q", b.read(8))[0]
    return GossipStoreEnded(equivalent_offset=equivalent_offset)