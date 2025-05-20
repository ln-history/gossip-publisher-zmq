import io
import struct
from model.internal.PrivateChannelAnnouncement import PrivateChannelAnnouncement

def parse(data: bytes) -> PrivateChannelAnnouncement:
    b = io.BytesIO(data)
    amount_sat = struct.unpack(">Q", b.read(8))[0]
    length = struct.unpack(">H", b.read(2))[0]
    announcement = b.read(length)
    return PrivateChannelAnnouncement(amount_sat=amount_sat, announcement=announcement)
