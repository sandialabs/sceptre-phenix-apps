import lxml.etree as ET

from phenix_apps.apps.otsim.protocols.protocol import Protocol, resolve_endpoint

# register type -> DNP3 point kind (analog/binary input/output)
POINT_KINDS = {
    "analog-read": "ai",
    "analog-read-write": "ao",
    "binary-read": "bi",
    "binary-read-write": "bo",
}


def assign_addresses(registers, addrs=None):
    """Number registers the way the outstation serves them: one counter per
    point kind, in register order. Returns (kind, index, register) tuples;
    registers of unknown types get no point."""
    if addrs is None:
        addrs = dict.fromkeys(POINT_KINDS.values(), 0)

    points = []
    for reg in registers:
        kind = POINT_KINDS.get(reg.type)
        if kind is None:
            continue
        points.append((kind, addrs[kind], reg))
        addrs[kind] += 1

    return points


class DNP3(Protocol):
    def __init__(self):
        Protocol.__init__(self, "dnp3")

        self.addrs = dict.fromkeys(POINT_KINDS.values(), 0)

    def init_xml_root(self, mode, node, name="dnp3-outstation"):
        self.mode = mode

        self.root = ET.Element("dnp3", {"name": name, "mode": mode})
        endpoint = ET.SubElement(self.root, "endpoint")

        ip, port = resolve_endpoint(node, "dnp3", 20000)
        endpoint.text = f"{ip}:{port}"

    def init_master_xml(self, scan_rate=None, name="dnp3-master"):
        self.master = ET.SubElement(self.root, "master", {"name": name})

        local = ET.SubElement(self.master, "local-address")
        local.text = str(1)

        remote = ET.SubElement(self.master, "remote-address")
        remote.text = str(1024)

        # Leave unset to fall back to the ot-sim DNP3 module default.
        if scan_rate is not None:
            rate = ET.SubElement(self.master, "scan-rate")
            rate.text = str(scan_rate)

    def init_outstation_xml(self, name="dnp3-outstation"):
        self.outstn = ET.SubElement(self.root, "outstation", {"name": name})

        local = ET.SubElement(self.outstn, "local-address")
        local.text = str(1024)

        remote = ET.SubElement(self.outstn, "remote-address")
        remote.text = str(1)

    def registers_to_xml(self, registers):
        parent = self.outstn if self.mode == "server" else self.master

        for kind, index, reg in assign_addresses(registers, self.addrs):
            direction = "input" if kind in ("ai", "bi") else "output"
            typ = "analog" if kind in ("ai", "ao") else "binary"
            point = ET.SubElement(parent, direction, {"type": typ})

            ET.SubElement(point, "address").text = str(index)
            ET.SubElement(point, "tag").text = reg.tag

            for key in ("sgvar", "egvar", "class"):
                if key in reg.md:
                    ET.SubElement(point, key).text = str(reg.md[key])

            if direction == "output" and "sbo" in reg.md:
                ET.SubElement(point, "sbo").text = str(reg.md["sbo"])
