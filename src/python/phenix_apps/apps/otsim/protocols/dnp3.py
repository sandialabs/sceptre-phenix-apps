import ipaddress

import xml.etree.ElementTree as ET

from phenix_apps.apps.otsim.infrastructure     import DEFAULT_INFRASTRUCTURES
from phenix_apps.apps.otsim.protocols.protocol import Protocol


class DNP3(Protocol):
  def __init__(self):
    Protocol.__init__(self, 'dnp3')

    self.addrs = {'analog': 0, 'binary': 0}


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
        addr.text = str(self.addrs['analog'])

        self.addrs['analog'] += 1

        tag = ET.SubElement(input, 'tag')
        tag.text = reg.tag

        if 'dnp3' in reg.md:
          if 'svar' in reg.md['dnp3']:
            svar = ET.SubElement(input, 'svar')
            svar.text = reg.md['dnp3']['svar']

          if 'evar' in reg.md['dnp3']:
            evar = ET.SubElement(input, 'evar')
            evar.text = reg.md['dnp3']['evar']

          if 'class' in reg.md['dnp3']:
            klass = ET.SubElement(input, 'class')
            klass.text = reg.md['dnp3']['class']
      elif reg.type == 'analog-read-write':
        input  = ET.SubElement(parent, 'input',  {'type': 'analog'})
        output = ET.SubElement(parent, 'output', {'type': 'analog'})

        in_addr = ET.SubElement(input, 'address')
        in_addr.text = str(self.addrs['analog'])

        out_addr = ET.SubElement(output, 'address')
        out_addr.text = str(self.addrs['analog'] + 1000)

        self.addrs['analog'] += 1

        in_tag = ET.SubElement(input, 'tag')
        in_tag.text = reg.tag

        out_tag = ET.SubElement(output, 'tag')
        out_tag.text = reg.tag

        if 'dnp3' in reg.md:
          if 'svar' in reg.md['dnp3']:
            svar = ET.SubElement(input, 'svar')
            svar.text = reg.md['dnp3']['svar']

          if 'evar' in reg.md['dnp3']:
            evar = ET.SubElement(input, 'evar')
            evar.text = reg.md['dnp3']['evar']

          if 'class' in reg.md['dnp3']:
            klass = ET.SubElement(input, 'class')
            klass.text = reg.md['dnp3']['class']

          if 'sbo' in reg.md['dnp3']:
            sbo = ET.SubElement(output, 'sbo')
            sbo.text = str(reg.md['dnp3']['sbo'])
      elif reg.type == 'binary-read':
        input = ET.SubElement(parent, 'input', {'type': 'binary'})

        addr = ET.SubElement(input, 'address')
        addr.text = str(self.addrs['binary'])

        self.addrs['binary'] += 1

        tag = ET.SubElement(input, 'tag')
        tag.text = reg.tag

        if 'dnp3' in reg.md:
          if 'svar' in reg.md['dnp3']:
            svar = ET.SubElement(input, 'svar')
            svar.text = reg.md['dnp3']['svar']

          if 'evar' in reg.md['dnp3']:
            evar = ET.SubElement(input, 'evar')
            evar.text = reg.md['dnp3']['evar']

          if 'class' in reg.md['dnp3']:
            klass = ET.SubElement(input, 'class')
            klass.text = reg.md['dnp3']['class']
      elif reg.type == 'binary-read-write':
        input  = ET.SubElement(parent, 'input',  {'type': 'binary'})
        output = ET.SubElement(parent, 'output', {'type': 'binary'})

        in_addr = ET.SubElement(input, 'address')
        in_addr.text = str(self.addrs['binary'])

        out_addr = ET.SubElement(output, 'address')
        out_addr.text = str(self.addrs['binary'] + 1000)

        self.addrs['binary'] += 1

        in_tag = ET.SubElement(input, 'tag')
        in_tag.text = reg.tag

        out_tag = ET.SubElement(output, 'tag')
        out_tag.text = reg.tag

        if 'dnp3' in reg.md:
          if 'svar' in reg.md['dnp3']:
            svar = ET.SubElement(input, 'svar')
            svar.text = reg.md['dnp3']['svar']

          if 'evar' in reg.md['dnp3']:
            evar = ET.SubElement(input, 'evar')
            evar.text = reg.md['dnp3']['evar']

          if 'class' in reg.md['dnp3']:
            klass = ET.SubElement(input, 'class')
            klass.text = reg.md['dnp3']['class']

          if 'sbo' in reg.md['dnp3']:
            sbo = ET.SubElement(output, 'sbo')
            sbo.text = str(reg.md['dnp3']['sbo'])