class AddressType:
    TYPE_NAMES = {
        1: "IPv4",
        2: "IPv6",
        3: "Torv2 (Deprecated)",
        4: "Torv3",
        5: "DNS",
    }

    def __init__(self, type_id: int):
        self.id: int = type_id
        self.name: str = self.TYPE_NAMES.get(type_id, "Unknown")

    def __repr__(self):
        return f"<AddressType id={self.id} name='{self.name}'>"