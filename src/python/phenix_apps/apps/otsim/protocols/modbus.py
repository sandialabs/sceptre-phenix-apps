import ipaddress

import xml.etree.ElementTree as ET

from phenix_apps.apps.otsim.infrastructure     import DEFAULT_INFRASTRUCTURES
from phenix_apps.apps.otsim.protocols.protocol import Protocol


class Modbus(Protocol):
  def __init__(self):
    Protocol.__init__(self, 'modbus')

    self.addrs = {'coil': 0, 'discrete': 20000, 'input': 30000, 'holding': 40000}


  def init_xml_root(self, mode, node, name='modbus-outstation'):
    self.mode = mode

    self.root = ET.Element('modbus', {'name': name, 'mode': mode})
    endpoint = ET.SubElement(self.root, 'endpoint')

    md = node.metadata

    if 'modbus' in md and isinstance(md['modbus'], dict):
      if 'interface' in md['modbus']:
        if ':' in md['modbus']['interface']:
          addr, port = md['modbus']['interface'].split(':', 1)
        else:
          addr = md['modbus']['interface']
          port = 502

        try:
          # test if IP address was provided
          ip = str(ipaddress.ip_address(addr))
        except ValueError:
          # assume interface name was provided
          for i in node.topology.network.interfaces:
            if i['name'] == addr and 'address' in i:
              ip = i['address']
              break
      else:
        if len(node.topology.network.interfaces[0]) > 0:
          ip   = node.topology.network.interfaces[0].address
          port = 502
    else: # legacy way of getting IP address
      if len(node.topology.network.interfaces[0]) > 0:
        ip   = node.topology.network.interfaces[0].address
        port = 502

    assert ip

    endpoint.text = f'{ip}:{port}'


  def registers_to_xml(self, registers):
    for reg in registers:
      if reg.type == 'binary-read-write':
        typ = 'coil'
        coil = ET.SubElement(self.root, 'register', {'type': typ})

        addr = ET.SubElement(coil, 'address')
        addr.text = str(self.addrs[typ])

        self.addrs[typ] += 1

        tag = ET.SubElement(coil, 'tag')
        tag.text = reg.tag
      elif reg.type == 'binary-read':
        typ = 'discrete'
        discrete = ET.SubElement(self.root, 'register', {'type': typ})

        addr = ET.SubElement(discrete, 'address')
        addr.text = str(self.addrs[typ])

        self.addrs[typ] += 1

        tag = ET.SubElement(discrete, 'tag')
        tag.text = reg.tag
      elif reg.type == 'analog-read':
        typ = 'input'
        input = ET.SubElement(self.root, 'register', {'type': typ})

        addr = ET.SubElement(input, 'address')
        addr.text = str(self.addrs[typ])

        self.addrs[typ] += 1

        tag = ET.SubElement(input, 'tag')
        tag.text = reg.tag

        if 'modbus' in reg.md:
          if 'scaling' in reg.md['modbus']:
            scale = reg.md['modbus']['scaling']

            scaling = ET.SubElement(input, 'scaling')
            scaling.text = str(int(scale) * -1 if self.mode == 'server' else int(scale))
      elif reg.type == 'analog-read-write':
        typ = 'holding'
        holding = ET.SubElement(self.root, 'register', {'type': typ})

        addr = ET.SubElement(holding, 'address')
        addr.text = str(self.addrs[typ])

        self.addrs[typ] += 1

        tag = ET.SubElement(holding, 'tag')
        tag.text = reg.tag

        if 'modbus' in reg.md:
          if 'scaling' in reg.md['modbus']:
            scale = reg.md['modbus']['scaling']

            scaling = ET.SubElement(holding, 'scaling')
            scaling.text = str(int(scale) * -1 if self.mode == 'server' else int(scale))