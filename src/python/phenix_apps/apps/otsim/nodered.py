import lxml.etree as ET


class NodeRed:
  @staticmethod
  def parse_metadata(md):
    if 'node-red' not in md:
      return None

    nodered = NodeRed()

    nodered.init_xml_root(md['node-red'])
    nodered.to_xml()

    return nodered


  def init_xml_root(self, md, name='node-red-module'):
    self.md   = md
    self.root = ET.Element('node-red', {'name': name})


  def to_xml(self):
    exe = ET.SubElement(self.root, 'executable')
    exe.text = 'node-red'

    theme = ET.SubElement(self.root, 'theme')
    theme.text = 'dark'

    flow = ET.SubElement(self.root, 'flow-path')
    flow.text = '/etc/node-red.json'

    endpoint_md = self.md.get('endpoint', None)
    if endpoint_md:
      params = {
        'host': endpoint_md.get('host', '0.0.0.0'),
        'port': str(endpoint_md.get('port', 1880)),
      }

      ET.SubElement(self.root, 'endpoint', params)

    auth_md = self.md.get('auth', None)
    if auth_md:
      authentication = ET.SubElement(self.root, 'authentication')

      editor_md = auth_md.get('editor', None)
      if editor_md:
        params = {
          'username': editor_md.get('user', 'admin'),
          'password': editor_md.get('pass', 'admin'),
        }

        ET.SubElement(authentication, 'editor', params)

      ui_md = auth_md.get('ui', None)
      if ui_md:
        params = {
          'username': ui_md.get('user', 'ui'),
          'password': ui_md.get('pass', 'ui'),
        }

        ET.SubElement(authentication, 'ui', params)


  def needs_inject(self):
    flow_md = self.md.get('flow', None)
    if flow_md:
      return {
          'src': flow_md,
          'dst': '/etc/node-red.json',
        }

    return None
