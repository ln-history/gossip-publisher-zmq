from model.AddressType import AddressType

class Address:
    def __init__(self):
        self.typ: AddressType = None
        self.addr: str = None
        self.port: int = None

    def __repr__(self):
        return f"<Address type={self.typ} addr={self.addr} port={self.port}>"

    def to_dict(self):
        return {
            "type": self.typ.to_dict() if self.typ else None,
            "address": self.addr,
            "port": self.port
        }