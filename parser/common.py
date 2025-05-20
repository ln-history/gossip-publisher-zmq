import struct
import codecs
import socket
import hashlib
import io
import struct
import base64
import ipaddress

from model.TLVRecord import TLVRecord
from model.Address import Address

def to_base_32(addr: bytes) -> str:
    """Base32 encode for .onion (lowercase, no padding)"""
    return base64.b32encode(addr).decode("ascii").strip("=").lower()

def parse_address(b: io.BytesIO) -> Address | None:
    pos_before = b.tell()
    try:
        t = read_exact(b, 1)
        a = Address()
        (a.typ,) = struct.unpack("!B", t)

        if a.typ == 1:  # IPv4
            a.addr = str(ipaddress.IPv4Address(read_exact(b, 4)))
            (a.port,) = struct.unpack("!H", read_exact(b, 2))
        elif a.typ == 2:  # IPv6
            raw = read_exact(b, 16)
            a.addr = f"[{ipaddress.IPv6Address(raw)}]"
            (a.port,) = struct.unpack("!H", read_exact(b, 2))
        elif a.typ == 3:  # Tor v2
            raw = read_exact(b, 10)
            a.addr = to_base_32(raw) + ".onion"
            (a.port,) = struct.unpack("!H", read_exact(b, 2))
        elif a.typ == 4:  # Tor v3
            raw = read_exact(b, 35)
            a.addr = to_base_32(raw) + ".onion"
            (a.port,) = struct.unpack("!H", read_exact(b, 2))
        else:
            # Unknown type — skip
            return None

        return a
    except Exception as e:
        # Rewind if parse failed
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


def read_bigsize(data: bytes, offset: int = 0):
    """Reads a BOLT BigSize variable-length integer."""
    first = data[offset]
    if first < 0xfd:
        return first, 1
    elif first == 0xfd:
        return struct.unpack(">H", data[offset+1:offset+3])[0], 3
    elif first == 0xfe:
        return struct.unpack(">I", data[offset+1:offset+5])[0], 5
    elif first == 0xff:
        return struct.unpack(">Q", data[offset+1:offset+9])[0], 9
    else:
        raise ValueError("Invalid BigSize encoding")

def parse_tlv_stream(data: bytes) -> dict:
    """Parses a TLV stream and returns a dict {type: TLVRecord}."""
    offset = 0
    records = {}

    while offset < len(data):
        typ, typ_len = read_bigsize(data, offset)
        offset += typ_len

        length, len_len = read_bigsize(data, offset)
        offset += len_len

        value = data[offset:offset+length]
        if len(value) != length:
            raise ValueError("TLV value truncated or malformed")

        offset += length
        records[typ] = TLVRecord(typ, length, value)

    return records