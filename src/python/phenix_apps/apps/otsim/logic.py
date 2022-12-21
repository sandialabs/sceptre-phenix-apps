import lxml.etree as ET


class Logic:
  def init_xml_root(self, name='logic-module'):
    self.root = ET.Element('logic', {'name': name})


  def logic_to_xml(self, program, vars, **kwargs):
    period  = kwargs.get('period', '1s')
    updates = kwargs.get('process_updates', True)

    ET.SubElement(self.root, 'period').text = period
    ET.SubElement(self.root, 'process-updates').text = str(updates).lower()
    ET.SubElement(self.root, 'program').text = ET.CDATA(program)

    variables = ET.SubElement(self.root, 'variables')

    for k, v in vars.items():
      if 'tag' in v:
        ET.SubElement(variables, k, {'tag': v['tag']}).text = str(v['value'])
      else:
        ET.SubElement(variables, k).text = str(v['value'])