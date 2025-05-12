import struct
import codecs
import socket
import hashlib

def parse_address_descriptor(value: bytes) -> dict:
    if not value:
        return {"type": "unknown", "raw": value.hex()}

    addr_type = value[0]
    body = value[1:]

    if addr_type == 1 and len(body) == 6:
        ip = socket.inet_ntoa(body[:4])
        port = int.from_bytes(body[4:], byteorder="big")
        return {"type": "ipv4", "ip": ip, "port": port}

    elif addr_type == 2 and len(body) == 18:
        ip = socket.inet_ntop(socket.AF_INET6, body[:16])
        port = int.from_bytes(body[16:], byteorder="big")
        return {"type": "ipv6", "ip": ip, "port": port}

    elif addr_type == 3:
        return {"type": "torv2 (deprecated)", "raw": body.hex()}

    elif addr_type == 4 and len(body) == 37:
        pubkey = body[:32]
        checksum = body[32:34]
        version = body[34]
        port = int.from_bytes(body[35:], byteorder="big")

        # Compute .onion name
        onion_input = b".onion checksum" + pubkey + bytes([version])
        onion_checksum = hashlib.sha3_256(onion_input).digest()[:2]

        if checksum == onion_checksum and version == 3:
            onion_address = codecs.encode(pubkey + checksum + bytes([version]), "base32").decode("ascii").lower().rstrip("=") + ".onion"
        else:
            onion_address = "invalid"

        return {"type": "torv3", "onion": onion_address, "port": port}

    elif addr_type == 5 and len(body) >= 3:
        hostname_len = body[0]
        hostname = body[1:1+hostname_len].decode("ascii", errors="replace")
        try:
            # Attempt to decode punycode if applicable
            hostname = codecs.decode(hostname.encode(), "punycode")
        except Exception:
            pass
        port = int.from_bytes(body[1+hostname_len:], byteorder="big")
        return {"type": "dns", "hostname": hostname, "port": port}

    else:
        return {"type": f"unknown ({addr_type})", "raw": body.hex()}



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

class TLVRecord:
    def __init__(self, typ: int, length: int, value: bytes):
        self.typ = typ
        self.length = length
        self.value = value

    def __repr__(self):
        return f"TLVRecord(type={self.typ}, length={self.length}, value={self.value.hex()})"

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
