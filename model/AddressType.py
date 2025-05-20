class AddressType:
    def __init__(self, id=None):
        self.id = id
        self.name = self.resolve_name(id)

    def resolve_name(self, id):
        mapping = {
            1: "IPv4",
            2: "IPv6",
            3: "Torv2",
            4: "Torv3",
            5: "DNS"
        }
        return mapping.get(id, "Unknown")

    def __repr__(self):
        return f"<AddressType id={self.id} name='{self.name}'>"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name
        }