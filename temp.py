from typing import Optional

import bech32


def decode_ln_dns_name(encoded: bytes) -> Optional[bytes]:
    """Decode a Lightning node Bech32 domain-style string to get the compressed pubkey (33 bytes)."""
    try:
        # Decode bech32 (e.g. 'ln1qfkx...' -> hrp='ln', data=[int list])
        hrp, data = bech32.bech32_decode(encoded.decode())

        if hrp is None or data is None:
            return None

        # Convert from 5-bit to 8-bit
        decoded_bytes = bytes(bech32.convertbits(data, 5, 8, False))

        # Ensure it’s 33 bytes (compressed pubkey length)
        if len(decoded_bytes) != 33:
            return None

        return decoded_bytes
    except Exception:
        return None


encoded = b"ln1qtxv63e3agfytfphsvqh6hc28wqkcns8q9kse5zzck7jfnajlsddkt6whzc"
pubkey_bytes = decode_ln_dns_name(encoded)

if pubkey_bytes:
    print(pubkey_bytes.hex())
