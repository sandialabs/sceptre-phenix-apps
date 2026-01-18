import random
import string
import xml.etree.ElementTree as ET
from typing import ClassVar

import phenix_apps.common.utils as utils


class SunSpecDevice:
    """Represents an RTU register config for the given SunSpec device.

    Breaking the SunSpec RTU device into its own class because of
    its complexity compared to other RTU devices (Modbus, DNP3, IEC-60870,
    etc). This somewhat matches the decision w/in the bennu code base
    to create a separate RTU for the SunSpec protocol.

    Parameters:
    -----------
    provider : string
        Name of infrastructure provider to be used as the data backer for this
        device. SCEPTRE RTUs can now have multiple providers per RTU, so each
        register configured must specify which provider is backing it.

    devname : string
        Unique name of this SunSpec device w/in a SCEPTRE model, pulled from
        the JSON metadata.

    registers : array
        Array of registers to append each SunSpec register to for this
        specific SunSpec device. This array is created in configs.py
        prior to being passed here.
    """

    def __init__(self, infra, devname, registers):
        self.infra = infra
        self.devname = devname
        self.registers = registers

        if self.infra is None:
            self.infra = "PowerDistribution"

        # Start the SunSpec register address at 40002 because
        # the sunspec_template automatically injects the well-known
        # SunSpec device map identifier 'SunS' at register 40000. We
        # initialize the address here because multiple SunSpec device
        # configurations can be generated in a single phēnix run, and
        # each configuration should start out at 40002.
        SunSpecDevice.Register.address = 40002

    def generate_registers(self, models):
        """Generates RTU register configs for the given models.

        Parameters:
        -----------
        models : array
            Integer array of SunSpec models to create registers for.
        """
        base_path = utils.abs_path(__file__, "../../")

        for model_id in models:
            xml_file = f"smdx_{int(model_id):05d}.xml"
            model = ET.ElementTree(
                file=f"{base_path}/protocols/sunspec/models/smdx/{xml_file}"
            ).getroot()
            model = model.find("model")

            register = SunSpecDevice.Register(
                self.infra, self.devname, model.get("name"), "uint16", model.get("id")
            )
            self.registers.append(register)

            register = SunSpecDevice.Register(
                self.infra, self.devname, "length", "uint16", model.get("len")
            )
            self.registers.append(register)

            blocks = model.findall("block")
            for block in blocks:  # model 126 has multiple block elements defined
                for point in block:
                    name = point.get("id")
                    fieldtype = point.get("type")
                    field = None
                    scaling = point.get(
                        "sf"
                    )  # Will return `None` if point doesn't have a scaling factor

                    # The SCEPTRE Bennu RTU expects string elements to indicate
                    # the base-8 length of the string (ie. `string8`, `string16`).
                    if fieldtype == "string":
                        fieldtype = f"string{point.get('len')}"

                    if model_id == 1:  # common block -- set some static values
                        if name == "Mn":
                            field = "Sandia SCEPTRE"
                        elif name == "Md":
                            field = "SunSpec RTU"
                        elif name == "SN":  # generate random string for serial number
                            field = "".join(
                                random.choice(string.ascii_uppercase + string.digits)
                                for _ in range(32)
                            )

                    register = SunSpecDevice.Register(
                        self.infra, self.devname, name, fieldtype, field, scaling
                    )
                    self.registers.append(register)

    class Register:
        sizes: ClassVar[dict[str, int]] = {
            "uint16": 1,
            "uint32": 2,
            "acc32": 2,
            "acc64": 4,
            "bitfield16": 1,
            "bitfield32": 2,
            "enum16": 1,
            "int16": 1,
            "int32": 2,
            "string8": 8,
            "string16": 16,
            "sunssf": 1,
            "float32": 2,
            "pad": 1,
        }

        disabled: ClassVar[dict[str, int]] = {
            "uint16": 65535,
            "uint32": 4294967295,
            "acc32": 0,
            "acc64": 0,
            "bitfield16": 65535,
            "bitfield32": 4294967295,
            "enum16": 65535,
            "int16": 32767,
            "int32": 2147483648,
            "string8": 0,
            "string16": 0,
            "sunssf": 0,
            "float32": 2147483648,
            "pad": 0,
        }

        mappings: ClassVar[
            dict[str, dict[str, list]]
        ] = {  # array index 0 indicates static value
            "PowerDistribution": {
                "A": [False, "current_mag_total"],
                "AphA": [False, "current_mag_p1"],
                "AphB": [False, "current_mag_p2"],
                "AphC": [False, "current_mag_p3"],
                "PhVphA": [False, "voltage_mag_p1"],
                "PhVphB": [False, "voltage_mag_p2"],
                "PhVphC": [False, "voltage_mag_p3"],
                "W": [False, "real_power_total"],
                "Hz": [True, "600"],
                "WH": [True, "0"],
                "Conn": [False, "active"],
                "WMaxLimPct": [True, "100"],
                "WMaxLim_Ena": [True, "0"],
                "OutPFSet": [True, "100"],
                "OutPFSet_Ena": [True, "0"],
                "VarPct_Ena": [True, "0"],
                "ActCrv": [True, "1"],
                "ModEna": [False, "volt_var_enable"],
                "NCrv": [True, "1"],
                "NPt": [True, "6"],
                "ActPt": [True, "6"],
                "DeptRef": [False, "volt_var_reference"],
                "V1": [False, "curve_volt_pt_1"],
                "VAr1": [False, "curve_var_pt_1"],
                "V2": [False, "curve_volt_pt_2"],
                "VAr2": [False, "curve_var_pt_2"],
                "V3": [False, "curve_volt_pt_3"],
                "VAr3": [False, "curve_var_pt_3"],
                "V4": [False, "curve_volt_pt_4"],
                "VAr4": [False, "curve_var_pt_4"],
                "V5": [False, "curve_volt_pt_5"],
                "VAr5": [False, "curve_var_pt_5"],
                "V6": [False, "curve_volt_pt_6"],
                "VAr6": [False, "curve_var_pt_6"],
                "ReadOnly": [True, "0"],
            },
            "PowerTransmission": {  # setting all these values using logic
                "A": [True, "0"],
                "AphA": [True, "0"],
                "AphB": [True, "0"],
                "AphC": [True, "0"],
                "PhVphA": [True, "0"],
                "PhVphB": [True, "0"],
                "PhVphC": [True, "0"],
                "W": [True, "0"],
                "Hz": [True, "0"],
                "Conn": [True, "0"],
                "WMaxLimPct": [True, "0"],
                "WMaxLim_Ena": [True, "0"],
                "WRtg": [True, "0"],
                "VArMaxPct": [True, "0"],
                "VArRtg": [True, "0"],
                "VAr": [True, "0"],
                "ReadOnly": [True, "0"],
            },
        }

        scalings: ClassVar[dict[str, str]] = {
            "A_SF": "-2",
            "V_SF": "-2",
            "VAr_SF": "-2",
            "W_SF": "-2",
            "Hz_SF": "-1",
            "WH_SF": "0",
            "Tmp_SF": "-1",
            "WMaxLimPct_SF": "-2",
            "OutPFSet_SF": "-2",
            "DeptRef_SF": "-1",
            "WRtg_SF": "0",
            "VArPct_SF": "-2",
        }

        # Start the SunSpec register address at 40002 because the
        # sunspec_template automatically injects the well-known SunSpec device
        # map identifier 'SunS' at register 40000.
        address = 40002

        def __init__(self, infra, devname, name, fieldtype, field=None, scaling=None):
            self.devname = devname
            self.name = name
            self.fieldtype = fieldtype
            self.field = field
            self.scaling = None

            mapping = type(self).mappings[infra]

            if scaling is not None and self.name in mapping:
                # this is for the case where the register being
                # configured has a scaling factor associated with it.
                self.scaling = type(self).scalings[scaling]

            self.regtype = "register"
            self.addr = type(self).address
            self.static = False

            if field is not None:
                self.static = True
            else:
                if self.name in mapping:
                    self.static = mapping[self.name][0]
                    self.field = mapping[self.name][1]
                elif self.name in type(self).scalings:
                    # this is for the case where the register being
                    # configured is the register for an actual scaling factor.
                    self.static = True
                    self.field = type(self).scalings[self.name]
                else:  # set field to disabled value
                    self.static = True
                    self.field = type(self).disabled[fieldtype]

                    # HACK: The SunSpec Models specify a 'pad' register
                    # type, but the SCEPTRE sunspec-rtu doesn't, so just
                    # configure it as an 'int16'. It will only ever be a static
                    # value set to it's default disabled value of '0', so it's
                    # OK to just have it in this section of the if-statement.
                    if fieldtype == "pad":
                        self.fieldtype = "int16"

            type(self).address += type(self).sizes[self.fieldtype]
