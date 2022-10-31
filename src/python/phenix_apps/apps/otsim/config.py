import xml.dom.minidom       as minidom
import xml.etree.ElementTree as ET


class Config:
  def __init__(self, md):
    if 'message-bus' in md:
      self.default_pull = md['message-bus'].get('pull-endpoint', 'tcp://127.0.0.1:1234')
      self.default_pub  = md['message-bus'].get('pub-endpoint',  'tcp://127.0.0.1:5678')
    else:
      self.default_pull = 'tcp://127.0.0.1:1234'
      self.default_pub  = 'tcp://127.0.0.1:5678'

    if 'cpu-module' in md:
      self.default_api = md['cpu-module'].get('api-endpoint', '0.0.0.0:9101')
    else:
      self.default_api = '0.0.0.0:9101'

    if 'ground-truth-module' in md:
      self.ground_truth = {}

      if 'elastic' in md['ground-truth-module']:
        self.ground_truth['elastic'] = {
          'default_endpoint':        md['ground-truth-module']['elastic'].get('endpoint', 'http://localhost:9200'),
          'default_index_base_name': md['ground-truth-module']['elastic'].get('index-base-name', 'ot-sim'),
        }
      else:
        self.ground_truth = None
    else:
      self.ground_truth = None


  def init_xml_root(self, md):
    self.root = ET.Element('ot-sim')

    msgbus = ET.SubElement(self.root, 'message-bus')
    pull   = ET.SubElement(msgbus, 'pull-endpoint')
    pub    = ET.SubElement(msgbus, 'pub-endpoint')

    if 'message-bus' in md:
      pull.text = md['message-bus'].get('pull-endpoint', self.default_pull)
      pub.text  = md['message-bus'].get('pub-endpoint',  self.default_pub)
    else:
      pull.text = self.default_pull
      pub.text  = self.default_pub

    self.cpu = ET.SubElement(self.root, 'cpu')

    if 'cpu-module' in md:
      api = ET.SubElement(self.cpu, 'api-endpoint')
      api.text = md['cpu-module'].get('api-endpoint', self.default_api)
    elif self.default_api:
      api = ET.SubElement(self.cpu, 'api-endpoint')
      api.text = self.default_api

    backplane = ET.SubElement(self.cpu, 'module', {'name': 'backplane'})
    backplane.text = 'ot-sim-message-bus {{config_file}}'

    if 'ground-truth-module' in md:
      # Might be null in config, which means disable it for this particular
      # device even though it's enabled globally.
      if md['ground-truth-module'] and 'elastic' in md['ground-truth-module']:
        gt  = ET.SubElement(self.root, 'ground-truth')
        es  = ET.SubElement(gt, 'elastic')
        ep  = ET.SubElement(es, 'endpoint')
        idx = ET.SubElement(es, 'index-base-name')

        ep.text  = md['ground-truth-module']['elastic'].get('endpoint',        self.ground_truth['elastic']['default_endpoint'])
        idx.text = md['ground-truth-module']['elastic'].get('index-base-name', self.ground_truth['elastic']['default_index_base_name'])
    elif self.ground_truth and 'elastic' in self.ground_truth:
      gt  = ET.SubElement(self.root, 'ground-truth')
      es  = ET.SubElement(gt, 'elastic')
      ep  = ET.SubElement(es, 'endpoint')
      idx = ET.SubElement(es, 'index-base-name')

      ep.text  = self.ground_truth['elastic']['default_endpoint']
      idx.text = self.ground_truth['elastic']['default_index_base_name']


  def append_to_root(self, child):
    self.root.append(child)


  def append_to_cpu(self, child):
    self.cpu.append(child)


  def to_file(self, path):
    with open(path, 'w') as f:
      f.write(minidom.parseString(ET.tostring(self.root)).toprettyxml())