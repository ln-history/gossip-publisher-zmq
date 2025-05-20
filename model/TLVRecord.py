import socket
import codecs
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

class TLVRecord:
    def __init__(self, typ: int, length: int, value: bytes):
        self.typ = typ
        self.length = length
        self.value = value

    def __str__(self):
        return f"TLVRecord(type={self.typ}, length={self.length}, value={self.value.hex()})"
    
    def decode_address(self):
        return parse_address_descriptor(self.value)