class Address:
    def __init__(self):
        self.typ = None
        self.addr = None
        self.port = None

    def __repr__(self):
         return f"<Address type={self.typ} addr={self.addr} port={self.port}>"
