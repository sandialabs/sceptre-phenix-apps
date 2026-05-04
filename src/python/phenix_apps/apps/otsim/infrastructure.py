import copy
from collections import defaultdict

import lxml.etree as ET

DEFAULT_INFRASTRUCTURES = {
    "power-distribution": {
        "node": {
            "voltage": {"type": "analog-read", "modbus": {"scaling": 2}},
        },
        "bus": {
            "voltage": {"type": "analog-read", "modbus": {"scaling": 2}},
        },
        "breaker": {
            "voltage": {"type": "analog-read", "modbus": {"scaling": 2}},
            "current": {"type": "analog-read", "modbus": {"scaling": 2}},
            "freq": {"type": "analog-read", "modbus": {"scaling": 2}},
            "power": {"type": "analog-read", "modbus": {"scaling": 2}},
            "status": {"type": "binary-read"},
            "controls": {"type": "binary-read-write"},
        },
        "capacitor": {
            "voltage": {"type": "analog-read", "modbus": {"scaling": 2}},
            "current": {"type": "analog-read", "modbus": {"scaling": 2}},
            "freq": {"type": "analog-read", "modbus": {"scaling": 2}},
            "power": {"type": "analog-read", "modbus": {"scaling": 2}},
            "setpt": {"type": "analog-read-write", "modbus": {"scaling": 2}},
        },
        "regulator": {
            "voltage": {"type": "analog-read", "modbus": {"scaling": 2}},
            "current": {"type": "analog-read", "modbus": {"scaling": 2}},
            "freq": {"type": "analog-read", "modbus": {"scaling": 2}},
            "power": {"type": "analog-read", "modbus": {"scaling": 2}},
            "setpt": {"type": "analog-read-write", "modbus": {"scaling": 2}},
        },
        "load": {
            "voltage": {"type": "analog-read", "modbus": {"scaling": 2}},
            "current": {"type": "analog-read", "modbus": {"scaling": 2}},
            "active_power": {"type": "analog-read", "modbus": {"scaling": 2}},
            "reactive_power": {"type": "analog-read", "modbus": {"scaling": 2}},
        },
        "line": {
            "from_voltage": {"type": "analog-read", "modbus": {"scaling": 2}},
            "from_current": {"type": "analog-read", "modbus": {"scaling": 2}},
            "from_active_power": {"type": "analog-read", "modbus": {"scaling": 2}},
            "from_reactive_power": {"type": "analog-read", "modbus": {"scaling": 2}},
            "to_voltage": {"type": "analog-read", "modbus": {"scaling": 2}},
            "to_current": {"type": "analog-read", "modbus": {"scaling": 2}},
            "to_active_power": {"type": "analog-read", "modbus": {"scaling": 2}},
            "to_reactive_power": {"type": "analog-read", "modbus": {"scaling": 2}},
        },
        "transformer": {
            "from_voltage": {"type": "analog-read", "modbus": {"scaling": 2}},
            "from_current": {"type": "analog-read", "modbus": {"scaling": 2}},
            "from_active_power": {"type": "analog-read", "modbus": {"scaling": 2}},
            "from_reactive_power": {"type": "analog-read", "modbus": {"scaling": 2}},
            "to_voltage": {"type": "analog-read", "modbus": {"scaling": 2}},
            "to_current": {"type": "analog-read", "modbus": {"scaling": 2}},
            "to_active_power": {"type": "analog-read", "modbus": {"scaling": 2}},
            "to_reactive_power": {"type": "analog-read", "modbus": {"scaling": 2}},
        },
    },
    # 3-phase variants of `power-distribution`. Variables that are inherently
    # per-phase (V/I/P/Q) are now declared as HELICS vectors with elements
    # [a,b,c]; the OT-sim io module subscribes to one vector per logical
    # variable and splits incoming values into per-phase scalar tags
    # (e.g. `{device}.voltage_magnitude.a`) for downstream dnp3/modbus
    # consumers. Variable names mirror the publishing federate convention
    # (`voltage_magnitude` etc.) for drop-in interop.
    "power-3-phase-distribution": {
        "node": {
            "voltage_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "voltage_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
        },
        "bus": {
            "voltage_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "voltage_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
        },
        "breaker": {
            "voltage_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "voltage_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "current_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "current_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "active_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "reactive_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "status": {"type": "binary-read"},
            "controls": {"type": "binary-read-write"},
        },
        "line": {
            "from_voltage_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "from_voltage_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "from_current_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "from_current_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "from_active_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "from_reactive_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "to_voltage_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "to_voltage_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "to_current_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "to_current_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "to_active_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "to_reactive_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
        },
        "transformer": {
            "from_voltage_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "from_voltage_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "from_current_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "from_current_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "from_active_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "from_reactive_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "to_voltage_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "to_voltage_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "to_current_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "to_current_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "to_active_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "to_reactive_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
        },
        "capacitor": {
            "voltage_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "voltage_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "current_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "current_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "active_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "reactive_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "setpt": {"type": "analog-read-write", "modbus": {"scaling": 2}},
        },
        "regulator": {
            "voltage_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "voltage_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "current_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "current_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "active_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "reactive_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "setpt": {"type": "analog-read-write", "modbus": {"scaling": 2}},
        },
        "load": {
            "voltage_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "voltage_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "current_magnitude": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "current_angle": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "active_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
            "reactive_power": {
                "type": "analog-read",
                "elements": ["a", "b", "c"],
                "modbus": {"scaling": 2},
            },
        },
    },
}


def merge_infrastructure_with_default(infra, mappings):
    # Merge provided infrastructure mappings (if any) with default infrastructure
    # mappings (if any). Note that this only goes two levels deep (which is all
    # that's needed right now).
    merged = copy.deepcopy(DEFAULT_INFRASTRUCTURES.get(infra, {}))

    for k, v in mappings.items():
        if k in merged:
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v

    return merged


class Infrastructure:
    def __init__(self, mappings):
        self.mappings = mappings

    def io_module_xml(self, doc, infra, devices):
        # merge provided mappings (if any) with default mappings (if any)
        mapping = merge_infrastructure_with_default(infra, self.mappings.get(infra, {}))

        # mapping of unique message endpoint names --> tag elements for IO module
        endpoints = defaultdict(list)

        # `devices` is a dictionary mapping infrastructure device names (used for
        # HELICS topic names and ot-sim tag names - always prepended with source
        # federate name) to its corresponding device.
        for topic in devices.keys():
            dev_type = devices[topic]["type"]
            endpoint = devices[topic]["endpoint"]

            assert dev_type in mapping

            device = mapping[dev_type]
            tag_name = topic.split("/")[1]

            for var, var_type in device.items():
                # `elements` (when present) marks the variable as a HELICS vector;
                # the OT-sim io module splits incoming vectors into per-element
                # scalar tags `{base_tag}.{label}` for downstream consumers.
                if isinstance(var_type, dict):
                    elements = var_type.get("elements")
                    var_type = var_type["type"]
                else:
                    elements = None

                if elements and var_type not in ["analog-read", "analog-read-write"]:
                    raise ValueError(
                        f"variable '{var}' on type '{dev_type}' has 'elements' but "
                        f"non-analog type '{var_type}'; vectors are analog-only"
                    )

                sub = ET.Element("subscription")

                key = ET.SubElement(sub, "key")
                key.text = f"{topic}.{var}"

                tag = ET.SubElement(sub, "tag")
                tag.text = f"{tag_name}.{var}"

                typ = ET.SubElement(sub, "type")

                if elements:
                    typ.text = "vector"
                    elts = ET.SubElement(sub, "elements")
                    elts.text = ",".join(elements)
                elif var_type in ["analog-read", "analog-read-write"]:
                    typ.text = "double"
                else:
                    typ.text = "boolean"

                doc.append(sub)

                if var_type in ["analog-read-write", "binary-read-write"]:
                    # `endpoint` will be False if disabled, otherwise it will be the name
                    # of the endpoint to send updates to (prepended with the destination
                    # federate name).
                    if endpoint:
                        if elements:
                            # endpoint write-back of a vector flows as per-element
                            # scalar tag/value pairs (the OT-sim io endpoint sender
                            # iterates the message bus's scalar Points).
                            for e in elements:
                                tag = ET.Element("tag")
                                tag.attrib["key"] = f"{tag_name}.{var}.{e}"
                                tag.text = f"{tag_name}.{var}.{e}"
                                endpoints[endpoint].append(tag)
                        else:
                            tag = ET.Element("tag")
                            tag.attrib["key"] = f"{tag_name}.{var}"
                            tag.text = f"{tag_name}.{var}"

                            endpoints[endpoint].append(tag)
                    else:
                        pub = ET.Element("publication")

                        key = ET.SubElement(pub, "key")
                        key.text = f"{tag_name}.{var}"

                        tag = ET.SubElement(pub, "tag")
                        tag.text = f"{tag_name}.{var}"

                        typ = ET.SubElement(pub, "type")

                        if elements:
                            typ.text = "vector"
                            elts = ET.SubElement(pub, "elements")
                            elts.text = ",".join(elements)
                        elif var_type == "analog-read-write":
                            typ.text = "double"
                        else:
                            typ.text = "boolean"

                        doc.append(pub)

        for name, tags in endpoints.items():
            endpoint = ET.Element("endpoint")
            endpoint.attrib["name"] = name

            for tag in tags:
                endpoint.append(tag)

            doc.append(endpoint)
