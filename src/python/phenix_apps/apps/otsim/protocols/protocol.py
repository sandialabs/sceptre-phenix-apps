import ipaddress

from phenix_apps.common import utils


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


def resolve_endpoint(node, protocol: str, default_port: int) -> tuple[str, int]:
    """Listen address for a protocol server on `node`.

    `<protocol>.interface` in the host metadata may be `ip[:port]` or
    `iface[:port]`; otherwise the first topology interface is used.
    """
    settings = node.metadata.get(protocol)
    interfaces = node.topology.network.interfaces
    ip = None
    port = default_port

    if isinstance(settings, dict) and "interface" in settings:
        try:
            addr, given = utils.split_host_port(str(settings["interface"]))
        except ValueError as ex:
            raise ValueError(
                f"'{node.hostname}' has an invalid {protocol} interface: {ex}"
            ) from None
        port = given or default_port
        try:
            ip = str(ipaddress.ip_address(addr))
        except ValueError:
            # assume an interface name was provided
            for i in interfaces:
                if i["name"] == addr and "address" in i:
                    ip = i["address"]
                    break
    elif interfaces and "address" in interfaces[0]:
        ip = interfaces[0]["address"]

    if not ip:
        raise ValueError(
            f"'{node.hostname}' has no addressed interface for its {protocol} endpoint"
        )
    return ip, port
