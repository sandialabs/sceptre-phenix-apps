import lxml.etree as ET

from phenix_apps.apps.otsim.infrastructure   import merge_infrastructure_with_default
from phenix_apps.apps.otsim.protocols.dnp3   import DNP3
from phenix_apps.apps.otsim.protocols.modbus import Modbus


class Register:
  def __init__(self, type, tag, md = {}):
    self.type = type
    self.tag  = tag
    self.md   = md


class Device:
  def __init__(self, node, default_infra = 'power-distribution'):
    self.node  = node
    self.md    = node.get('metadata', {})
    self.infra = self.md.get('infrastructure', default_infra)

    self.registers = {}
    self.processed = False


class FEP(Device):
  def __init__(self, node):
    Device.__init__(self, node)

  def process(self, devices):
    if self.processed: return

    # TODO: track upstream device registers by device name (which should be
    # unique across device types) so downstream server doesn't include a
    # register twice if an upstream server provides access to the same device
    # across multiple protocols. Would need to figure out how to handle what
    # client to default to using if multiple protocols provide access upstream.

    # TODO: support configuring which registers are available downstream. Right
    # now, all registers available upstream are made available downstream. Users
    # may want to only make a subset of registers available downstream.

    # Support legacy `connected_rtus` key if `upstream` key is not present.
    for name in self.md.get('upstream', self.md.get('connected_rtus', [])):
      device = devices[name]
      assert device

      device.process(devices)

      for proto, regs in device.registers.items():
        if proto not in self.registers:
          self.registers[proto] = []

        self.registers[proto] += regs

    self.processed = True

  def configure(self, config, known):
    protos = {}

    # Support legacy `connected_rtus` key if `upstream` key is not present.
    for upstream in self.md.get('upstream', self.md.get('connected_rtus', [])):
      device = known[upstream]

      if 'modbus' in device.registers:
        client = Modbus()
        client.init_xml_root('client', device.node)
        client.registers_to_xml(device.registers['modbus'])

        config.append_to_root(client.root)
        protos['modbus'] = True

      if 'dnp3' in device.registers:
        client = DNP3()
        client.init_xml_root('client', device.node)
        client.init_master_xml()
        client.registers_to_xml(device.registers['dnp3'])

        config.append_to_root(client.root)
        protos['dnp3'] = True

    registers = []
    for regs in self.registers.values():
      registers += regs

    downstream = self.md.get('downstream', None)

    # Default to using DNP3 for downstream side.
    if not downstream or downstream == 'dnp3':
      server = DNP3()
      server.init_xml_root('server', self.node)
      server.init_outstation_xml()
      server.registers_to_xml(registers)

      config.append_to_root(server.root)
      protos['dnp3'] = True
    elif downstream == 'modbus':
      server = Modbus()
      server.init_xml_root('server', self.node)
      server.registers_to_xml(registers)

      config.append_to_root(server.root)
      protos['modbus'] = True

    if 'dnp3' in protos:
      module = ET.Element('module', {'name': 'dnp3'})
      module.text = 'ot-sim-dnp3-module {{config_file}}'

      config.append_to_cpu(module)

    if 'modbus' in protos:
      module = ET.Element('module', {'name': 'modbus'})
      module.text = 'ot-sim-modbus-module {{config_file}}'

      config.append_to_cpu(module)


class FieldDeviceServer(Device):
  def __init__(self, node, default_infra = 'power-distribution'):
    Device.__init__(self, node, default_infra)

  def process(self, mappings):
    if self.processed: return

    # merge provided mappings (if any) with default mappings (if any)
    mapping = merge_infrastructure_with_default(self.infra, mappings.get(self.infra, {}))

    if 'dnp3' in self.md:
      if 'dnp3' not in self.registers:
        self.registers['dnp3'] = []

      # md['dnp3'] can either be a list of infrastructure devices configured to
      # be monitored using the DNP3 protocol or a dictionary that contains a
      # `devices` key that holds the list. Each entry includes a name that's
      # used for tags and a type that references an infrastructure type.
      if isinstance(self.md['dnp3'], dict):
        devices = self.md['dnp3']['devices']
      else:
        devices = self.md['dnp3']

      for fd in devices:
        assert fd['type'] in mapping
        device = mapping[fd['type']]

        # defice name might be prefixed with HELICS federate name
        parts = fd['name'].split('/')
        name  = parts[1] if len(parts) > 1 else parts[0]

        for var, var_type in device.items():
          # We care about static and event variable types in the DNP3 protocol
          # module, so if the variable type is a string convert it to a
          # dictionary so the rest of the code can be the same when checking to
          # see if variable types were provided.
          if isinstance(var_type, str):
            var_type = {'type': var_type}

          reg = Register(var_type['type'], f"{name}.{var}", var_type.get('dnp3', {}))
          self.registers['dnp3'].append(reg)

    if 'modbus' in self.md:
      if 'modbus' not in self.registers:
        self.registers['modbus'] = []

      # md['modbus'] can either be a list of infrastructure devices configured
      # to be monitored using the DNP3 protocol or a dictionary that contains a
      # `devices` key that holds the list. Each entry includes a name that's
      # used for tags and a type that references an infrastructure type.
      if isinstance(self.md['modbus'], dict):
        devices = self.md['modbus']['devices']
      else:
        devices = self.md['modbus']

      for fd in devices:
        assert fd['type'] in mapping
        device = mapping[fd['type']]

        # defice name might be prefixed with HELICS federate name
        parts = fd['name'].split('/')
        name  = parts[1] if len(parts) > 1 else parts[0]

        for var, var_type in device.items():
          # We care about scaling in the Modbus protocol module, so if the
          # variable type is a string convert it to a dictionary so the rest of
          # the code can be the same when checking to see if a scaling factor
          # was provided.
          if isinstance(var_type, str):
            var_type = {'type': var_type}

          reg = Register(var_type['type'], f"{name}.{var}", var_type.get('modbus', {}))
          self.registers['modbus'].append(reg)

    self.processed = True

  def configure(self, config):
    if 'dnp3' in self.registers:
      server = DNP3()
      server.init_xml_root('server', self.node)
      server.init_outstation_xml()
      server.registers_to_xml(self.registers['dnp3'])

      module = ET.Element('module', {'name': 'dnp3'})
      module.text = 'ot-sim-dnp3-module {{config_file}}'

      config.append_to_root(server.root)
      config.append_to_cpu(module)

    if 'modbus' in self.registers:
      server = Modbus()
      server.init_xml_root('server', self.node)
      server.registers_to_xml(self.registers['modbus'])

      module = ET.Element('module', {'name': 'modbus'})
      module.text = 'ot-sim-modbus-module {{config_file}}'

      config.append_to_root(server.root)
      config.append_to_cpu(module)


class FieldDeviceClient(Device):
  def __init__(self, node):
    Device.__init__(self, node)

  def process(self, devices):
    if self.processed: return

    for name in self.md.get('connected_rtus', []):
      device = devices[name]
      assert device

      device.process(devices)

    self.processed = True

  def configure(self, config, known):
    protos = {}

    for downstream in self.md.get('connected_rtus', []):
      device = known[downstream]

      if 'modbus' in device.registers:
        client = Modbus()
        client.init_xml_root('client', device.node)
        client.registers_to_xml(device.registers['modbus'])

        config.append_to_root(client.root)
        protos['modbus'] = True

      if 'dnp3' in device.registers:
        client = DNP3()
        client.init_xml_root('client', device.node)
        client.init_master_xml()
        client.registers_to_xml(device.registers['dnp3'])

        config.append_to_root(client.root)
        protos['dnp3'] = True

    if 'modbus' in protos:
      module = ET.Element('module', {'name': 'modbus'})
      module.text = 'ot-sim-modbus-module {{config_file}}'

      config.append_to_cpu(module)

    if 'dnp3' in protos:
      module = ET.Element('module', {'name': 'dnp3'})
      module.text = 'ot-sim-dnp3-module {{config_file}}'

      config.append_to_cpu(module)