from dataclasses import dataclass

@dataclass
class ChannelAnnouncement:
    features: bytes
    chain_hash: bytes
    short_channel_id: int
    node_id_1: bytes
    node_id_2: bytes
    bitcoin_key_1: bytes
    bitcoin_key_2: bytes
    node_signature_1: bytes
    node_signature_2: bytes
    bitcoin_signature_1: bytes
    bitcoin_signature_2: bytes

    @property
    def short_channel_id_str(self):
        block = (self.short_channel_id >> 40) & 0xFFFFFF
        txindex = (self.short_channel_id >> 16) & 0xFFFFFF
        output = self.short_channel_id & 0xFFFF
        return f"{block}x{txindex}x{output}"

    def __str__(self):
        return f"ChannelAnnouncement(scid={self.short_channel_id_str}, node_id_1={self.node_id_1.hex()}, node_id_2={self.node_id_2.hex()}, features={self.features.hex()}, chain_hash={self.chain_hash})"
    
    def to_dict(self) -> dict:
        return {
            "features": self.features.hex(),
            "chain_hash": self.chain_hash.hex(),
            "short_channel_id": self.short_channel_id_str,
            "node_id_1": self.node_id_1.hex(),
            "node_id_2": self.node_id_2.hex(),
            "bitcoin_key_1": self.bitcoin_key_1.hex(),
            "bitcoin_key_2": self.bitcoin_key_2.hex(),
            "node_signature_1": self.node_signature_1.hex(),
            "node_signature_2": self.node_signature_2.hex(),
            "bitcoin_signature_1": self.bitcoin_signature_1.hex(),
            "bitcoin_signature_2": self.bitcoin_signature_2.hex()
        }
