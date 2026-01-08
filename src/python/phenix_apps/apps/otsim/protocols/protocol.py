class Protocol:
    def __init__(self, name):
        self.name = name

    def init_xml_root(self, mode, node, name):
        raise NotImplementedError(
            f"init_xml_root not implemented for {self.name} protocol"
        )

    def registers_to_xml(self, infra, devices):
        raise NotImplementedError(
            f"registers_to_xml not implemented for {self.name} protocol"
        )
