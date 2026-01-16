"""
This is a "dependacy free" implementation of a register-map generator, only using
native python modules. This module simple takes in a field device config and
generates an XML file that can be read my Microsoft Excel."
"""

import datetime
import json
import xml.etree.ElementTree as ET


class RegMapGen:
    def __init__(
        cls, exp_dir, exp, filename="excel.xml", num_cols="11", num_rows="591"
    ):
        wb_attrib = {
            "xmlns": "urn:schemas-microsoft-com:office:spreadsheet",
            "xmlns:o": "urn:schemas-microsoft-com:office:office",
            "xmlns:x": "urn:schemas-microsoft-com:office:excel",
            "xmlns:ss": "urn:schemas-microsoft-com:office:spreadsheet",
            "xmlns:html": "http://www.w3.org/TR/REC-html40",
        }
        cls.exp_dir = exp_dir
        cls.exp = exp
        cls.workbook = ET.Element("Workbook", attrib=wb_attrib)
        cls.fd_bit = True
        cls.ip_bit = True
        cls.attr_bit = True
        # init DocumentProperties
        cls.dp = ET.SubElement(
            cls.workbook,
            "DocumentProperties",
            attrib={"xmlns": "urn:schemas-microsoft-com:office:office"},
        )
        item = ET.SubElement(cls.dp, "LastAuthor")
        item.text = "Microsoft Office User"
        item = ET.SubElement(cls.dp, "Created")
        item.text = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        item = ET.SubElement(cls.dp, "Version")
        item.text = "16.00"

        # init OfficeDocumentSettings
        cls.ods = ET.SubElement(
            cls.workbook,
            "OfficeDocumentSettings",
            attrib={"xmlns": "urn:schemas-microsoft-com:office:office"},
        )
        item = ET.SubElement(cls.ods, "AllowPNG")
        item = ET.SubElement(cls.ods, "Colors")
        color = ET.SubElement(item, "Color")
        item = ET.SubElement(color, "Index")
        item.text = "25"
        item = ET.SubElement(color, "RGB")
        item.text = "#EBEBEB"

        # init ExcelWorkbook
        cls.ew = ET.SubElement(
            cls.workbook,
            "ExcelWorkbook",
            attrib={"xmlns": "urn:schemas-microsoft-com:office:excel"},
        )
        item = ET.SubElement(cls.ew, "WindowHeight")
        item.text = "10840"
        item = ET.SubElement(cls.ew, "WindowWidth")
        item.text = "16340"
        item = ET.SubElement(cls.ew, "WindowTopX")
        item.text = "480"
        item = ET.SubElement(cls.ew, "WindowTopY")
        item.text = "460"
        item = ET.SubElement(cls.ew, "DoNotCalculateBeforeSave")
        item = ET.SubElement(cls.ew, "ProtectStructure")
        item.text = "False"
        item = ET.SubElement(cls.ew, "ProtectWindows")
        item.text = "False"

        # init Styles
        cls.styles = ET.SubElement(cls.workbook, "Styles")
        item = ET.SubElement(
            cls.styles, "Style", attrib={"ss:ID": "Default", "ss:Name": "Normal"}
        )
        ET.SubElement(item, "Font", attrib={"ss:FontName": "Arial", "x:CharSet": "1"})

        # Style: timestamp
        style = ET.SubElement(cls.styles, "Style", attrib={"ss:ID": "created"})
        ET.SubElement(
            style,
            "Alignment",
            attrib={"ss:Horizontal": "Right", "ss:Vertical": "Center"},
        )
        ET.SubElement(style, "Borders")
        ET.SubElement(
            style,
            "Font",
            attrib={
                "ss:FontName": "calibri",
                "x:CharSet": "1",
                "ss:Color": "#000000",
                "ss:Italic": "1",
            },
        )
        ET.SubElement(style, "Interior")
        ET.SubElement(style, "Protection")

        style = ET.SubElement(cls.styles, "Style", attrib={"ss:ID": "date"})
        ET.SubElement(
            style,
            "Alignment",
            attrib={"ss:Horizontal": "Right", "ss:Vertical": "Center"},
        )
        ET.SubElement(style, "Borders")
        ET.SubElement(
            style,
            "Font",
            attrib={
                "ss:FontName": "calibri",
                "x:CharSet": "1",
                "ss:Color": "#000000",
                "ss:Italic": "1",
            },
        )
        ET.SubElement(style, "Interior")
        ET.SubElement(style, "NumberFormat", attrib={"ss:Format": "General Date"})
        ET.SubElement(style, "Protection")

        # Style: index_bar
        cls.add_style(
            "index_bar",
            "#808080",
            {
                "ss:FontName": "calibri",
                "x:CharSet": "1",
                "ss:Color": "#FFFFFF",
                "ss:Bold": "1",
                "ss:Italic": "1",
            },
        )
        # Style: small_dark
        cls.add_style(
            "small_dark",
            "#C0C0C0",
            {"ss:FontName": "calibri", "x:CharSet": "1", "ss:Color": "#000000"},
        )
        # Style: small_light
        cls.add_style(
            "small_light",
            "#EBEBEB",
            {"ss:FontName": "calibri", "x:CharSet": "1", "ss:Color": "#000000"},
        )
        # Style: ip_proto_dark
        cls.add_style(
            "ip_proto_dark",
            "#C0C0C0",
            {"ss:FontName": "calibri", "x:CharSet": "1", "ss:Color": "#000000"},
        )
        # Style: ip_proto_light
        cls.add_style(
            "ip_proto_light",
            "#EBEBEB",
            {"ss:FontName": "calibri", "x:CharSet": "1", "ss:Color": "#000000"},
        )
        # Style: field_device_dark
        cls.add_style(
            "field_device_dark",
            "#C0C0C0",
            {
                "ss:FontName": "calibri",
                "x:CharSet": "1",
                "ss:Color": "#000000",
                "ss:Bold": "1",
                "ss:Italic": "1",
            },
        )
        # Style: field_device_light
        cls.add_style(
            "field_device_light",
            "#EBEBEB",
            {
                "ss:FontName": "calibri",
                "x:CharSet": "1",
                "ss:Color": "#000000",
                "ss:Bold": "1",
                "ss:Italic": "1",
            },
        )

        # init Worksheet
        cls.worksheet = ET.SubElement(
            cls.workbook, "Worksheet", attrib={"ss:Name": "Register Map"}
        )

        # init table
        cls.table = ET.SubElement(
            cls.worksheet,
            "Table",
            attrib={
                "ss:ExpandedColumnCount": num_cols,
                "ss:ExpandedRowCount": num_rows,
                "x:FullColumns": "1",
                "x:FullRows": "1",
                "ss:DefaultColumnWidth": "130",
                "ss:DefaultRowHeight": "13",
            },
        )
        row = ET.SubElement(cls.table, "Row", attrib={"ss:Height": "14"})
        cls.add_cell(row, "created", "String", "Created:")
        cls.add_cell(
            row,
            "date",
            "DateTime",
            datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        )

        # index bar
        row = ET.SubElement(cls.table, "Row", attrib={"ss:Height": "14"})
        cls.add_cell(row, "index_bar", "String", "Field Device", index="2")
        cls.add_cell(row, "index_bar", "String", "IP Address")
        cls.add_cell(row, "index_bar", "String", "Protocol")
        cls.add_cell(row, "index_bar", "String", "Device")
        cls.add_cell(row, "index_bar", "String", "Device Type")
        cls.add_cell(row, "index_bar", "String", "Register #")
        cls.add_cell(row, "index_bar", "String", "Reg Type")
        cls.add_cell(row, "index_bar", "String", "Read/Write")
        cls.add_cell(row, "index_bar", "String", "Scaling")
        cls.add_cell(row, "index_bar", "String", "Data")

        # worksheet cont.
        cls.wo = ET.SubElement(
            cls.worksheet,
            "WorksheetOptions",
            attrib={"xmlns": "urn:schemas-microsoft-com:office:excel"},
        )
        cls.ps = ET.SubElement(cls.wo, "PageSetup")
        ET.SubElement(
            cls.ps,
            "Layout",
            attrib={"x:CenterHorizontal": "1", "x:StartPageNumber": "1"},
        )
        ET.SubElement(cls.ps, "Header", attrib={"x:Margin": "0.1", "x:Data": "&amp;P"})
        ET.SubElement(cls.ps, "Footer", attrib={"x:Margin": "0.1", "x:Data": "&amp;F"})
        ET.SubElement(
            cls.ps,
            "PageMargins",
            attrib={
                "x:Bottom": "0.37",
                "x:Left": "0.3",
                "x:Right": "0.3",
                "x:Top": "0.61",
            },
        )
        ET.SubElement(cls.wo, "NoSummaryRowsBelowDetail")
        ET.SubElement(cls.wo, "NoSummaryColumnsRightDetail")
        print_item = ET.SubElement(cls.wo, "Print")
        ET.SubElement(print_item, "LeftToRight")
        ET.SubElement(print_item, "ValidPrinterInfo")
        item = ET.SubElement(print_item, "PaperSizeIndex")
        item.text = "9"
        item = ET.SubElement(print_item, "HorizontalResolution")
        item.text = "300"
        item = ET.SubElement(print_item, "VerticalResolution")
        item.text = "300"
        ET.SubElement(cls.wo, "Selected")
        item = ET.SubElement(cls.wo, "ProtectObjects")
        item.text = "False"
        item = ET.SubElement(cls.wo, "ProtectScenarios")
        item.text = "False"

    def add_cell(cls, row, ss_sid, ss_type, data, md="", index=""):
        cell_attri = {}
        cell_attri["ss:StyleID"] = ss_sid
        if md != "":
            cell_attri["ss:MergeDown"] = md
        if index != "":
            cell_attri["ss:Index"] = index

        cell = ET.SubElement(row, "Cell", attrib=cell_attri)
        data_item = ET.SubElement(cell, "Data", attrib={"ss:Type": ss_type})
        data_item.text = data

    def add_style(cls, sid, int_color, fnt_dict):
        style = ET.SubElement(cls.styles, "Style", attrib={"ss:ID": sid})
        ET.SubElement(
            style,
            "Alignment",
            attrib={"ss:Horizontal": "Center", "ss:Vertical": "Center"},
        )
        bds = ET.SubElement(
            style,
            "Borders",
        )
        ET.SubElement(
            bds,
            "Border",
            attrib={
                "ss:Position": "Bottom",
                "ss:LineStyle": "Continuous",
                "ss:Weight": "1",
                "ss:Color": "#FFFFFF",
            },
        )
        ET.SubElement(
            bds,
            "Border",
            attrib={
                "ss:Position": "Left",
                "ss:LineStyle": "Continuous",
                "ss:Weight": "1",
                "ss:Color": "#FFFFFF",
            },
        )
        ET.SubElement(
            bds,
            "Border",
            attrib={
                "ss:Position": "Right",
                "ss:LineStyle": "Continuous",
                "ss:Weight": "1",
                "ss:Color": "#FFFFFF",
            },
        )
        ET.SubElement(style, "Font", attrib=fnt_dict)
        ET.SubElement(
            style, "Interior", attrib={"ss:Color": int_color, "ss:Pattern": "Solid"}
        )
        ET.SubElement(style, "Protection")

    def write(cls):
        # create a new XML file with the results
        mydata = ET.tostring(cls.workbook).decode("utf-8")
        with open(f"{cls.exp_dir}analytics/register_map_{cls.exp}.xml", "w") as f:
            f.write('<?xml version="1.0"?>')
            f.write('<?mso-application progid="Excel.Sheet"?>')
            f.write(mydata)

    def new_row(cls, regs, i, proto=[], dev=[], ip=""):
        if i == 0 and dev != []:
            row = ET.SubElement(cls.table, "Row", attrib={"ss:Height": "14"})
            if cls.fd_bit:
                cls.add_cell(
                    row,
                    "field_device_dark",
                    "String",
                    dev[0],
                    md=str(dev[1]),
                    index="2",
                )
                cls.fd_bit = not cls.fd_bit
            else:
                cls.add_cell(
                    row,
                    "field_device_light",
                    "String",
                    dev[0],
                    md=str(dev[1]),
                    index="2",
                )
                cls.fd_bit = not cls.fd_bit

            if cls.ip_bit:
                cls.add_cell(row, "ip_proto_dark", "String", ip, md=str(dev[1]))
                cls.add_cell(
                    row, "ip_proto_light", "String", proto[0], md=str(proto[1])
                )

            else:
                cls.add_cell(row, "ip_proto_light", "String", ip, md=str(dev[1]))
                cls.add_cell(row, "ip_proto_dark", "String", proto[0], md=str(proto[1]))

            if cls.attr_bit:
                cls.add_cell(row, "small_dark", "String", regs["device"])
                cls.add_cell(row, "small_dark", "String", regs["device_type"])
                cls.add_cell(row, "small_dark", "String", str(regs["register_number"]))
                cls.add_cell(row, "small_dark", "String", regs["register_type"])
                cls.add_cell(row, "small_dark", "String", regs["rw"])
                cls.add_cell(row, "small_dark", "String", str(regs["scale"]))
                cls.add_cell(row, "small_dark", "String", regs["data"])
                cls.attr_bit = not cls.attr_bit
            else:
                cls.add_cell(row, "small_light", "String", regs["device"])
                cls.add_cell(row, "small_light", "String", regs["device_type"])
                cls.add_cell(row, "small_light", "String", str(regs["register_number"]))
                cls.add_cell(row, "small_light", "String", regs["register_type"])
                cls.add_cell(row, "small_light", "String", regs["rw"])
                cls.add_cell(row, "small_light", "String", str(regs["scale"]))
                cls.add_cell(row, "small_light", "String", regs["data"])
                cls.attr_bit = not cls.attr_bit

        elif proto != []:
            row = ET.SubElement(cls.table, "Row", attrib={"ss:Height": "14"})

            if cls.ip_bit:
                cls.add_cell(
                    row,
                    "ip_proto_dark",
                    "String",
                    proto[0],
                    md=str(proto[1]),
                    index="4",
                )
                cls.ip_bit = not cls.ip_bit
            else:
                cls.add_cell(
                    row,
                    "ip_proto_light",
                    "String",
                    proto[0],
                    md=str(proto[1]),
                    index="4",
                )
                cls.ip_bit = not cls.ip_bit

            if cls.attr_bit:
                cls.add_cell(row, "small_dark", "String", regs["device"])
                cls.add_cell(row, "small_dark", "String", regs["device_type"])
                cls.add_cell(row, "small_dark", "String", str(regs["register_number"]))
                cls.add_cell(row, "small_dark", "String", regs["register_type"])
                cls.add_cell(row, "small_dark", "String", regs["rw"])
                cls.add_cell(row, "small_dark", "String", str(regs["scale"]))
                cls.add_cell(row, "small_dark", "String", regs["data"])
                cls.attr_bit = not cls.attr_bit
            else:
                cls.add_cell(row, "small_light", "String", regs["device"])
                cls.add_cell(row, "small_light", "String", regs["device_type"])
                cls.add_cell(row, "small_light", "String", str(regs["register_number"]))
                cls.add_cell(row, "small_light", "String", regs["register_type"])
                cls.add_cell(row, "small_light", "String", regs["rw"])
                cls.add_cell(row, "small_light", "String", str(regs["scale"]))
                cls.add_cell(row, "small_light", "String", regs["data"])
                cls.attr_bit = not cls.attr_bit

        else:
            row = ET.SubElement(cls.table, "Row", attrib={"ss:Height": "14"})

            if cls.attr_bit:
                cls.add_cell(row, "small_dark", "String", regs["device"], index="5")
                cls.add_cell(row, "small_dark", "String", regs["device_type"])
                cls.add_cell(row, "small_dark", "String", str(regs["register_number"]))
                cls.add_cell(row, "small_dark", "String", regs["register_type"])
                cls.add_cell(row, "small_dark", "String", regs["rw"])
                cls.add_cell(row, "small_dark", "String", str(regs["scale"]))
                cls.add_cell(row, "small_dark", "String", regs["data"])
                cls.attr_bit = not cls.attr_bit
            else:
                cls.add_cell(row, "small_light", "String", regs["device"], index="5")
                cls.add_cell(row, "small_light", "String", regs["device_type"])
                cls.add_cell(row, "small_light", "String", str(regs["register_number"]))
                cls.add_cell(row, "small_light", "String", regs["register_type"])
                cls.add_cell(row, "small_light", "String", regs["rw"])
                cls.add_cell(row, "small_light", "String", str(regs["scale"]))
                cls.add_cell(row, "small_light", "String", regs["data"])
                cls.attr_bit = not cls.attr_bit


def generate_file(fd_configs, exp_dir, exp):
    number_of_regs = 0
    ## Get the number of registers so we can configure the worksheet
    ## to support the correct number of rows
    for _, field_dev in fd_configs.items():
        for _, regs in field_dev.registers.items():
            for _ in regs:
                number_of_regs += 1

    ## Initialize workbook
    wb = RegMapGen(exp_dir, exp, num_rows=str((number_of_regs + 10)))

    ## Loop through every device in the experiemnt
    for name, field_dev in fd_configs.items():
        fd_addr = field_dev.ipaddr
        protos = {}

        ## Generate a map containing protocols and their associated registers
        for devname, regs in field_dev.registers.items():
            for reg in regs:
                if reg.protocol.lower() == "modbus":
                    scale = reg.range
                else:
                    scale = "N/A"
                if reg.protocol in protos:
                    protos[reg.protocol].append(
                        {
                            "device": devname,
                            "device_type": reg.devtype,
                            "register_number": reg.addr,
                            "rw": reg.fieldtype,
                            "scale": scale,
                            "data": reg.field,
                            "register_type": reg.regtype,
                        }
                    )
                else:
                    protos[reg.protocol] = []
                    protos[reg.protocol].append(
                        {
                            "device": devname,
                            "device_type": reg.devtype,
                            "register_number": reg.addr,
                            "rw": reg.fieldtype,
                            "scale": scale,
                            "data": reg.field,
                            "register_type": reg.regtype,
                        }
                    )

        total_reg_cnt = 0
        protos_names = list(protos)

        ## Get the register count for the current device for formatting
        for key, regs in protos.items():
            total_reg_cnt += len(regs)

        ## For each protocol in current device we want to properly create rows in our table
        for key, regs in protos.items():
            i = 0
            for reg in sorted(regs, key=lambda k: k["register_number"]):
                if i == 0:
                    if len(protos_names) == len(protos.items()):
                        wb.new_row(
                            reg,
                            i,
                            [key.upper(), (len(protos[key]) - 1)],
                            [name.upper(), (total_reg_cnt - 1)],
                            ip=fd_addr,
                        )
                    else:
                        wb.new_row(reg, i, [key.upper(), (len(protos[key]) - 1)])
                else:
                    wb.new_row(reg, i)
                i += 1
            protos_names.pop()
    wb.write()


def update_config(
    config, fd, devname, protocol, fieldtype, field, register_number, regtype
):
    for i in range(len(config["nodes"])):
        if config["nodes"][i]["general"]["hostname"] == fd:
            if "manual_register_config" not in config["nodes"][i]["metadata"].keys():
                config["nodes"][i]["metadata"]["manual_register_config"] = "False"
            if "connected_rtus" in config["nodes"][i]["metadata"].keys():
                continue
            for j in range(len(config["nodes"][i]["metadata"][protocol])):
                if config["nodes"][i]["metadata"][protocol][j]["name"] == devname:
                    if fieldtype in config["nodes"][i]["metadata"][protocol][j]:
                        config["nodes"][i]["metadata"][protocol][j][fieldtype].append(
                            {
                                "field": field,
                                "register_number": register_number,
                                "register_type": regtype,
                            }
                        )
                    else:
                        config["nodes"][i]["metadata"][protocol][j][fieldtype] = []
                        config["nodes"][i]["metadata"][protocol][j][fieldtype].append(
                            {
                                "field": field,
                                "register_number": register_number,
                                "register_type": regtype,
                            }
                        )
    return config


def generate_json(topology, topo_dir, fd_configs, experiment_directory):
    """
    This is a utility used to create a register map template as a json file.
    """
    with open(f"{topo_dir}{topology}.json") as topo:
        config = json.load(topo)
    for devconfig in fd_configs:
        for proto in devconfig.protocols:
            for dev in proto.devices:
                for reg in dev.registers:
                    config = update_config(
                        config,
                        devconfig.name,
                        reg.devname,
                        proto.protocol,
                        reg.fieldtype,
                        reg.field,
                        reg.addr,
                        reg.regtype,
                    )
    with open("{}/ConfigWithCustomRegs.json".format(experiment_directory), "w") as f:
        f.write(json.dumps(config, indent=4))
