import lxml.etree as ET


class Logic:
    @staticmethod
    def parse_metadata(md):
        if "logic" not in md:
            return None

        if "program" not in md["logic"]:
            return None

        program = md["logic"]["program"]
        variables = md["logic"].get("variables", {})
        period = md["logic"].get("period", "1s")
        process_updates = md["logic"].get("processUpdates", False)

        logic = Logic()

        logic.init_xml_root()
        logic.logic_to_xml(
            program, variables, period=period, process_updates=process_updates
        )

        return logic

    def init_xml_root(self, name="logic-module"):
        self.root = ET.Element("logic", {"name": name})

    def logic_to_xml(self, program, vars, **kwargs):
        period = kwargs.get("period", "1s")
        updates = kwargs.get("process_updates", True)

        ET.SubElement(self.root, "period").text = period
        ET.SubElement(self.root, "process-updates").text = str(updates).lower()
        ET.SubElement(self.root, "program").text = ET.CDATA(program)

        variables = ET.SubElement(self.root, "variables")

        for k, v in vars.items():
            if "tag" in v:
                ET.SubElement(variables, k, {"tag": v["tag"]}).text = str(v["value"])
            else:
                ET.SubElement(variables, k).text = str(v["value"])
