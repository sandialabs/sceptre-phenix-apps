import xml.etree.ElementTree as ET


DEFAULT_INFRASTRUCTURES = {
  'power-distribution': {
    'node': {
      'voltage': {'type': 'analog-read', 'modbus': {'scaling': 2}},
    },
    'bus': {
      'voltage': {'type': 'analog-read', 'modbus': {'scaling': 2}},
    },
    'breaker': {
      'voltage':  {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'current':  {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'freq':     {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'power':    {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'status':   {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'controls': {'type': 'analog-read-write', 'modbus': {'scaling': 2}},
    },
    'capacitor': {
      'voltage':       {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'current':       {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'freq':          {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'power':         {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'status':        {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'on_off_status': {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'setpt':         {'type': 'analog-read-write', 'modbus': {'scaling': 2}},
    },
    'regulator': {
      'voltage':       {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'current':       {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'freq':          {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'power':         {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'status':        {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'on_off_status': {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'setpt':         {'type': 'analog-read-write', 'modbus': {'scaling': 2}},
    },
    'load': {
      'voltage':        {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'current':        {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'active_power':   {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'reactive_power': {'type': 'analog-read', 'modbus': {'scaling': 2}},
    },
    'line': {
      'from_voltage':        {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'from_current':        {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'from_active_power':   {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'from_reactive_power': {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'to_voltage':          {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'to_current':          {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'to_active_power':     {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'to_reactive_power':   {'type': 'analog-read', 'modbus': {'scaling': 2}},
    },
    'transformer': {
      'from_voltage':        {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'from_current':        {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'from_active_power':   {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'from_reactive_power': {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'to_voltage':          {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'to_current':          {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'to_active_power':     {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'to_reactive_power':   {'type': 'analog-read', 'modbus': {'scaling': 2}},
    }
  }
}


class Infrastructure:
  def __init__(self, mappings):
    self.mappings = mappings


  def io_module_xml(self, doc, infra, devices, default_fed):
    # merge provided mappings (if any) with default mappings (if any)
    default = DEFAULT_INFRASTRUCTURES.get(infra, {})
    mapping = {**default, **self.mappings.get(infra, {})}

    # `devices` is a dictionary mapping infrastructure device names (used for
    # HELICS topic names and ot-sim tag names) to its corresponding
    # intfrastructure type.
    for name, type in devices.items():
      assert type in mapping
      device = mapping[type]

      parts = name.split('/')

      for var, var_type in device.items():
          # We don't care about scaling in the I/O module, so if the variable
          # type is a dictionary convert it to a string (using its `type` entry)
          # so the rest of the code can assume it's just a string.
        if isinstance(var_type, dict):
          var_type = var_type['type']

        if var_type in ['analog-read', 'binary-read']:
          sub = ET.Element('subscription')

          if len(parts) == 1:
            topic_name = f'{default_fed}/{name}'
          else:
            topic_name = name

          key = ET.SubElement(sub, 'key')
          key.text = f'{topic_name}.{var}'

          if len(parts) == 2:
            tag_name = parts[1]
          else:
            tag_name = name

          tag = ET.SubElement(sub, 'tag')
          tag.text = f'{tag_name}.{var}'

          typ = ET.SubElement(sub, 'type')

          if var_type == 'analog-read':
            typ.text = 'double'
          else:
            typ.text = 'boolean'

          doc.append(sub)
        elif var_type in ['analog-read-write', 'binary-read-write']:
          pub = ET.Element('publication')

          if len(parts) == 2:
            name = parts[1]

          key = ET.SubElement(pub, 'key')
          key.text = f'{name}.{var}'

          tag = ET.SubElement(pub, 'tag')
          tag.text = f'{name}.{var}'

          typ = ET.SubElement(pub, 'type')

          if var_type == 'analog-read-write':
            typ.text = 'double'
          else:
            typ.text = 'boolean'

          doc.append(pub)