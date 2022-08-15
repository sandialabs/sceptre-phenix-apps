import ipaddress

import xml.etree.ElementTree as ET

from phenix_apps.apps.otsim.infrastructure     import DEFAULT_INFRASTRUCTURES
from phenix_apps.apps.otsim.protocols.protocol import Protocol


class DNP3(Protocol):
  def __init__(self):
    Protocol.__init__(self, 'dnp3')

    self.addrs = {'ai': 0, 'ao': 0, 'bi': 0, 'bo': 0}


  def init_xml_root(self, mode, node, name='dnp3-outstation'):
    self.mode = mode

    self.root = ET.Element('dnp3', {'name': name, 'mode': mode})
    endpoint = ET.SubElement(self.root, 'endpoint')

    md = node.metadata

    if 'dnp3' in md and isinstance(md['dnp3'], dict):
      if 'interface' in md['dnp3']:
        if ':' in md['dnp3']['interface']:
          addr, port = md['dnp3']['interface'].split(':', 1)
        else:
          addr = md['dnp3']['interface']
          port = 20000

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
          port = 20000
    else: # legacy way of getting IP address
      if len(node.topology.network.interfaces[0]) > 0:
        ip   = node.topology.network.interfaces[0].address
        port = 20000

    assert ip

    endpoint.text = f'{ip}:{port}'


  def init_master_xml(self, name='dnp3-master'):
    self.master = ET.SubElement(self.root, 'master', {'name': name})

    local = ET.SubElement(self.master, 'local-address')
    local.text = str(1)

    remote = ET.SubElement(self.master, 'remote-address')
    remote.text = str(1024)

    scan_rate = ET.SubElement(self.master, 'scan-rate')
    scan_rate.text = str(5)


  def init_outstation_xml(self, name='dnp3-outstation'):
    self.outstn = ET.SubElement(self.root, 'outstation', {'name': name})

    local = ET.SubElement(self.outstn, 'local-address')
    local.text = str(1024)

    remote = ET.SubElement(self.outstn, 'remote-address')
    remote.text = str(1)


  def registers_to_xml(self, registers):
    parent = self.outstn if self.mode == 'server' else self.master

    for reg in registers:
      if reg.type == 'analog-read':
        input = ET.SubElement(parent, 'input', {'type': 'analog'})

        addr = ET.SubElement(input, 'address')
        addr.text = str(self.addrs['ai'])

        self.addrs['ai'] += 1

        tag = ET.SubElement(input, 'tag')
        tag.text = reg.tag

        if 'sgvar' in reg.md:
          svar = ET.SubElement(input, 'sgvar')
          svar.text = reg.md['sgvar']

        if 'egvar' in reg.md:
          evar = ET.SubElement(input, 'egvar')
          evar.text = reg.md['egvar']

        if 'class' in reg.md:
          klass = ET.SubElement(input, 'class')
          klass.text = reg.md['class']
      elif reg.type == 'analog-read-write':
        output = ET.SubElement(parent, 'output', {'type': 'analog'})

        addr = ET.SubElement(output, 'address')
        addr.text = str(self.addrs['ao'])

        self.addrs['ao'] += 1

        tag = ET.SubElement(output, 'tag')
        tag.text = reg.tag

        if 'sgvar' in reg.md:
          svar = ET.SubElement(output, 'sgvar')
          svar.text = reg.md['sgvar']

        if 'egvar' in reg.md:
          evar = ET.SubElement(output, 'egvar')
          evar.text = reg.md['egvar']

        if 'class' in reg.md:
          klass = ET.SubElement(output, 'class')
          klass.text = reg.md['class']

        if 'sbo' in reg.md:
          sbo = ET.SubElement(output, 'sbo')
          sbo.text = str(reg.md['sbo'])
      elif reg.type == 'binary-read':
        input = ET.SubElement(parent, 'input', {'type': 'binary'})

        addr = ET.SubElement(input, 'address')
        addr.text = str(self.addrs['bi'])

        self.addrs['bi'] += 1

        tag = ET.SubElement(input, 'tag')
        tag.text = reg.tag

        if 'sgvar' in reg.md:
          svar = ET.SubElement(input, 'sgvar')
          svar.text = reg.md['sgvar']

        if 'egvar' in reg.md:
          evar = ET.SubElement(input, 'egvar')
          evar.text = reg.md['egvar']

        if 'class' in reg.md:
          klass = ET.SubElement(input, 'class')
          klass.text = reg.md['class']
      elif reg.type == 'binary-read-write':
        output = ET.SubElement(parent, 'output', {'type': 'binary'})

        addr = ET.SubElement(output, 'address')
        addr.text = str(self.addrs['bo'])

        self.addrs['bo'] += 1

        tag = ET.SubElement(output, 'tag')
        tag.text = reg.tag

        if 'sgvar' in reg.md:
          svar = ET.SubElement(output, 'sgvar')
          svar.text = reg.md['sgvar']

        if 'egvar' in reg.md:
          evar = ET.SubElement(output, 'egvar')
          evar.text = reg.md['egvar']

        if 'class' in reg.md:
          klass = ET.SubElement(output, 'class')
          klass.text = reg.md['class']

        if 'sbo' in reg.md:
          sbo = ET.SubElement(output, 'sbo')
          sbo.text = str(reg.md['sbo'])
