import copy

import lxml.etree as ET

from collections import defaultdict


DEFAULT_INFRASTRUCTURES = {
  'power-distribution': {
    'node': {
      'voltage': {'type': 'analog-read', 'modbus': {'scaling': 2}},
    },
    'bus': {
      'voltage': {'type': 'analog-read', 'modbus': {'scaling': 2}},
    },
    'breaker': {
      'voltage':  {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'current':  {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'freq':     {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'power':    {'type': 'analog-read', 'modbus': {'scaling': 2}},
      'status':   {'type': 'binary-read'},
      'controls': {'type': 'binary-read-write'},
    },
    'capacitor': {
      'voltage':       {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'current':       {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'freq':          {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'power':         {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'setpt':         {'type': 'analog-read-write', 'modbus': {'scaling': 2}},
    },
    'regulator': {
      'voltage':       {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'current':       {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'freq':          {'type': 'analog-read',       'modbus': {'scaling': 2}},
      'power':         {'type': 'analog-read',       'modbus': {'scaling': 2}},
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


def merge_infrastructure_with_default(infra, mappings):
  # Merge provided infrastructure mappings (if any) with default infrastructure
  # mappings (if any). Note that this only goes two levels deep (which is all
  # that's needed right now).
  merged = copy.deepcopy(DEFAULT_INFRASTRUCTURES.get(infra, {}))

  for k, v in mappings.items():
    if k in merged:
      merged[k] = {**merged[k], **v}
    else:
      merged[k] = v

  return merged


class Infrastructure:
  def __init__(self, mappings):
    self.mappings = mappings


  def io_module_xml(self, doc, infra, devices):
    # merge provided mappings (if any) with default mappings (if any)
    mapping = merge_infrastructure_with_default(infra, self.mappings.get(infra, {}))

    # mapping of unique message endpoint names --> tag elements for IO module
    endpoints = defaultdict(list)

    # `devices` is a dictionary mapping infrastructure device names (used for
    # HELICS topic names and ot-sim tag names - always prepended with source
    # federate name) to its corresponding device.
    for topic in devices.keys():
      type     = devices[topic]['type']
      endpoint = devices[topic]['endpoint']

      assert type in mapping
      assert endpoint

      device   = mapping[type]
      tag_name = topic.split('/')[1]

      for var, var_type in device.items():
          # We don't care about scaling in the I/O module, so if the variable
          # type is a dictionary convert it to a string (using its `type` entry)
          # so the rest of the code can assume it's just a string.
        if isinstance(var_type, dict):
          var_type = var_type['type']

        if var_type in ['analog-read', 'binary-read']:
          sub = ET.Element('subscription')

          key = ET.SubElement(sub, 'key')
          key.text = f'{topic}.{var}'

          tag = ET.SubElement(sub, 'tag')
          tag.text = f'{tag_name}.{var}'

          typ = ET.SubElement(sub, 'type')

          if var_type == 'analog-read':
            typ.text = 'double'
          else:
            typ.text = 'boolean'

          doc.append(sub)
        elif var_type in ['analog-read-write', 'binary-read-write']:
          # `endpoint` will be False if disabled, otherwise it will be the name
          # of the endpoint to send updates to (prepended with the destination
          # federate name).
          if endpoint:
            tag = ET.Element('tag')
            tag.attrib['key'] = f'{tag_name}.{var}'
            tag.text = f'{tag_name}.{var}'

            endpoints[endpoint].append(tag)
          else:
            pub = ET.Element('publication')

            key = ET.SubElement(pub, 'key')
            key.text = f'{tag_name}.{var}'

            tag = ET.SubElement(pub, 'tag')
            tag.text = f'{tag_name}.{var}'

            typ = ET.SubElement(pub, 'type')

            if var_type == 'analog-read-write':
              typ.text = 'double'
            else:
              typ.text = 'boolean'

            doc.append(pub)

    for name, tags in endpoints.items():
      endpoint = ET.Element('endpoint')
      endpoint.attrib['name'] = name

      for tag in tags:
        endpoint.append(tag)

      doc.append(endpoint)
