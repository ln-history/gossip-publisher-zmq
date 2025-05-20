import struct
import codecs
import io
import struct
import base64
import ipaddress

from model.Address import Address
from model.AddressType import AddressType

def to_base_32(addr: bytes) -> str:
    """Base32 encode for .onion (lowercase, no padding)"""
    return base64.b32encode(addr).decode("ascii").strip("=").lower()

def parse_address(b: io.BytesIO) -> Address | None:
    pos_before = b.tell()
    try:
        type_byte = read_exact(b, 1)
        type_id = struct.unpack("!B", type_byte)[0]

        a = Address()
        a.typ = AddressType(type_id)

        if type_id == 1:  # IPv4
            a.addr = str(ipaddress.IPv4Address(read_exact(b, 4)))
            (a.port,) = struct.unpack("!H", read_exact(b, 2))
        elif type_id == 2:  # IPv6
            raw = read_exact(b, 16)
            a.addr = f"[{ipaddress.IPv6Address(raw)}]"
            (a.port,) = struct.unpack("!H", read_exact(b, 2))
        elif type_id == 3:  # Tor v2
            raw = read_exact(b, 10)
            a.addr = to_base_32(raw) + ".onion"
            (a.port,) = struct.unpack("!H", read_exact(b, 2))
        elif type_id == 4:  # Tor v3
            raw = read_exact(b, 35)
            a.addr = to_base_32(raw) + ".onion"
            (a.port,) = struct.unpack("!H", read_exact(b, 2))
        elif type_id == 5:  # DNS
            hostname_len = struct.unpack("!B", read_exact(b, 1))[0]
            hostname = read_exact(b, hostname_len).decode("ascii")
            a.addr = hostname
            (a.port,) = struct.unpack("!H", read_exact(b, 2))
        else:
            return None

        return a
    except Exception as e:
        b.seek(pos_before)
        print(f"Error parsing address: {e}")
        return None


def read_exact(b: io.BytesIO, n: int) -> bytes:
    data = b.read(n)
    if len(data) != n:
        raise ValueError(f"Expected {n} bytes, got {len(data)}")
    return data

def decode_alias(alias_bytes: bytes) -> str:
    try:
        # Try UTF-8 first
        return alias_bytes.decode('utf-8').strip('\x00')
    except UnicodeDecodeError:
        try:
            # If UTF-8 fails, try punycode (with stripped null bytes)
            cleaned = alias_bytes.strip(b'\x00')
            return codecs.decode(cleaned, 'punycode')
        except Exception:
            # As last resort, return hex
            return alias_bytes.hex()
