import copy, os, re

import lxml.etree as ET

from box import Box

from phenix_apps.apps   import AppBase
from phenix_apps.common import logger

from phenix_apps.apps.otsim.config           import Config
from phenix_apps.apps.otsim.device           import Register
from phenix_apps.apps.otsim.logic            import Logic
from phenix_apps.apps.otsim.nodered          import NodeRed
from phenix_apps.apps.otsim.protocols.modbus import Modbus
from phenix_apps.apps.otsim.protocols.dnp3   import DNP3


class WindTurbine(AppBase):
  def __init__(self):
    AppBase.__init__(self, 'wind-turbine')

    self.startup_dir = f"{self.exp_dir}/startup"
    self.ot_sim_dir  = f"{self.exp_dir}/ot-sim"

    os.makedirs(self.startup_dir, exist_ok=True)
    os.makedirs(self.ot_sim_dir,  exist_ok=True)

    self.__init_defaults()
    self.execute_stage()

    # We don't (currently) let the parent AppBase class handle this step
    # just in case app developers want to do any additional manipulation
    # after the appropriate stage function has completed.
    print(self.experiment.to_json())


  def pre_start(self):
    logger.log('INFO', f'Starting user application: {self.name}')

    app = self.extract_app()
    self.templates = app.get('metadata', {}).get('templates', {})

    for host in app.get("hosts", []):
      if host.get('metadata', {}).get('type', None) != 'main-controller':
        continue

      regex     = re.compile(host.hostname)
      extracted = self.extract_node(host.hostname, wildcard = True)

      for node in extracted:
        match = regex.match(node.general.hostname)

        # Will match if hostname matches filter exactly, but won't have any groups.
        if match and len(match.groups()) > 0:
          logger.log('INFO', f'node {node.general.hostname} matched {host.hostname}')

          md     = copy.deepcopy(host.get('metadata', {}))
          groups = match.groups()

          for i in range(len(groups)):
            group = i+1

            md.controllers.anemometer = md.controllers.anemometer.replace(f'${group}', groups[i])
            md.controllers.yaw = md.controllers.yaw.replace(f'${group}', groups[i])

            for j in range(len(md.controllers.blades)):
              blade = md.controllers.blades[j].replace(f'${group}', groups[i])
              md.controllers.blades[j] = blade

            if 'ground-truth-module' in md and 'elastic' in md['ground-truth-module']:
              for name, value in md['ground-truth-module']['elastic'].get('labels', {}).items():
                md['ground-truth-module']['elastic']['labels'][name] = value.replace(f'${group}', groups[i])

          model = Box({'hostname': node.general.hostname})
          model['metadata'] = md
          model['topology'] = node

          anemo = Box({
            'hostname': md.controllers.anemometer,
            'metadata': {'type': 'anemometer', 'template': md.get('template', 'default'), 'ground-truth-module': md.get('ground-truth-module', {})},
            'topology': self.extract_node(md.controllers.anemometer),
          })

          yaw = Box({
            'hostname': md.controllers.yaw,
            'metadata': {'type': 'yaw-controller', 'template': md.get('template', 'default'), 'ground-truth-module': md.get('ground-truth-module', {})},
            'topology': self.extract_node(md.controllers.yaw),
          })

          self.__main_controller(model, anemo, yaw, match)
          self.__anemometer(anemo)
          self.__yaw_controller(yaw)

          for blade in md.controllers.blades:
            self.__blade_controller(blade, {'ground-truth-module': md.get('ground-truth-module', {})})
        else:
          md = host.get('metadata', {})

          model = Box({'hostname': node.general.hostname})
          model['metadata'] = md
          model['topology'] = node

          self.__main_controller(model)
          self.__anemometer(md.controllers.anemometer)
          self.__yaw_controller(md.controllers.yaw)

          for blade in md.controllers.blades:
            self.__blade_controller(blade, {'ground-truth-module': md.get('ground-truth-module', {})})

    logger.log('INFO', f'Started user application: {self.name}')


  def __init_defaults(self):
    # Track multiple brokers that need an inject generated, along with their
    # total federate count to be started with and log level/file settings.
    self.brokers = {}

    if 'helics' in self.metadata:
      # The `helics.broker` key gets processed by each app host if needed.
      self.default_fed      = self.metadata['helics'].get('federate', 'OpenDSS')
      self.default_endpoint = self.metadata['helics'].get('endpoint', f'{self.default_fed}/updates')

      # handle `self.default_endpoint` being set to False
      if self.default_endpoint and '/' not in self.default_endpoint:
        self.default_endpoint = f'{self.default_fed}/{self.default_endpoint}'
    else:
      self.default_fed      = 'OpenDSS'
      self.default_endpoint = 'OpenDSS/updates'


  def __process_helics_broker_metadata(self, md):
    if 'helics' in md:
      if 'broker' in md['helics']:
        broker = md['helics']['broker']

        if 'hostname' in broker:
          if '|' in broker['hostname']:
            hostname, iface = broker['hostname'].split('|', 1)
          else:
            hostname = broker['hostname']
            iface    = None

          if 'base-fed-count' in broker:
            if hostname not in self.brokers:
              self.brokers[hostname] = {
                'feds':      int(broker['base-fed-count']),
                'log-level': broker.get('log-level', 'SUMMARY'),
                'log-file':  broker.get('log-file', '/var/log/helics-broker.log'),
              }

            self.brokers[hostname]['feds'] += 1

          node = self.extract_node(hostname)
          assert node

          if iface:
            for i in node.network.interfaces:
              if i['name'] == iface and 'address' in i:
                addr = i['address']
                break
          else:
            if len(node.network.interfaces) > 0:
              if 'address' in node.network.interfaces[0]:
                addr = node.network.interfaces[0]['address']

          assert addr
          return addr
        elif 'address' in broker:
          return broker['address']


  def __main_controller(self, node, anemo = None, yaw = None, match = None):
    config = Config(self.metadata)
    config.init_xml_root(node.metadata)

    tmpl = self.templates.get(node.metadata.get('template', 'default'), {}).get('main-controller', {})

    md        = node.metadata.get('turbine', tmpl.get('turbine', {}))
    typ       = md.get('type', 'E-126/4200')
    height    = md.get('hubHeight', 135)
    roughness = md.get('roughnessLength', 0.15)
    helics    = md.get('helicsTopic', None)
    sbo       = md.get('dnp3SBO', False)

    turbine = ET.Element('wind-turbine')
    power   = ET.SubElement(turbine, 'power-output')

    ET.SubElement(power, 'turbine-type').text     = typ
    ET.SubElement(power, 'hub-height').text       = str(height)
    ET.SubElement(power, 'roughness-length').text = str(roughness)

    md      = node.metadata.get('weather', tmpl.get('weather', {}))
    columns = md.get('columns', [])

    data = ET.SubElement(power, 'weather-data')

    for col in columns:
      for tag in col['tags']:
        ET.SubElement(data, 'column', {'name': col['name'], 'height': str(tag['height'])}).text = tag['name']

    tags = ET.SubElement(power, 'tags')

    ET.SubElement(tags, 'cut-in').text         = 'turbine.cut-in'
    ET.SubElement(tags, 'cut-out').text        = 'turbine.cut-out'
    ET.SubElement(tags, 'output').text         = 'turbine.mw-output'
    ET.SubElement(tags, 'emergency-stop').text = 'turbine.emergency-stop'

    module = ET.Element('module', {'name': 'turbine-power-output'})
    module.text = 'ot-sim-wind-turbine-power-output-module {{config_file}}'

    config.append_to_root(turbine)
    config.append_to_cpu(module)

    if helics:
      key = helics

      if match and len(match.groups()) > 0:
        groups = match.groups()

        for i in range(len(groups)):
          group = i+1
          key = key.replace(f'${group}', groups[i])

      io = ET.Element('io', {'name': 'helics-federate'})

      broker    = ET.SubElement(io, 'broker-endpoint')
      federate  = ET.SubElement(io, 'federate-name')
      log_level = ET.SubElement(io, 'federate-log-level')

      addr = self.__process_helics_broker_metadata(self.metadata)
      assert addr

      broker.text    = addr
      federate.text  = node.hostname
      log_level.text = 'SUMMARY'

      endpoint = ET.Element('endpoint')
      endpoint.attrib['name'] = self.default_endpoint

      tag = ET.Element('tag')
      tag.attrib['key'] = key
      tag.text = 'turbine.mw-output'

      endpoint.append(tag)
      io.append(endpoint)

      config.append_to_root(io)

      module = ET.Element('module', {'name': 'i/o'})
      module.text = 'ot-sim-io-module {{config_file}}'

      config.append_to_cpu(module)

      annotation = [{'broker': addr, 'fed-count': 1}]
      self.add_annotation(node.hostname, 'helics/federate', annotation)


    md = node.metadata.get('node-red', tmpl.get('node-red', None))
    if md:
      nodered = NodeRed()

      nodered.init_xml_root(md, 'main-controller')
      nodered.to_xml()

      module = ET.Element('module', {'name': 'node-red'})
      module.text = 'ot-sim-node-red-module {{config_file}}'

      config.append_to_root(nodered.root)
      config.append_to_cpu(module)

      inject = nodered.needs_inject()
      if inject:
        self.add_inject(hostname=node.hostname, inject=inject)

    md        = node.metadata.get('logic', tmpl.get('logic', {}))
    speed_tag = md.get('speedTag', 'speed.high')
    dir_tag   = md.get('directionTag', 'dir.high')
    dir_error = md.get('directionError', 0.04)

    program = f"""
      manual_stop = false
      proto_stop = proto_emer_stop != 0
      stop = proto_stop || manual_stop
      feathered = stop || speed < cut_in || speed > cut_out
      target = direction > 180 ? direction - 180 : direction + 180
      error = target * dir_error
      adjust = abs(target - current_yaw) > error
      adjust = adjust && !feathered
      yaw_setpoint = adjust ? target : yaw_setpoint
      # hack to get yaw.dir-error tag published to DNP3 module
      dir_error = dir_error
    """

    variables = {
      'speed':           {'value': 0,         'tag': speed_tag},
      'direction':       {'value': 0,         'tag': dir_tag},
      'cut_in':          {'value': 100,       'tag': 'turbine.cut-in'},
      'cut_out':         {'value': 0,         'tag': 'turbine.cut-out'},
      'current_yaw':     {'value': 0,         'tag': 'yaw.current'},
      'yaw_setpoint':    {'value': 0,         'tag': 'yaw.setpoint'},
      'dir_error':       {'value': dir_error, 'tag': 'yaw.dir-error'},
      'proto_emer_stop': {'value': 0,         'tag': 'turbine.emergency-stop'},
      'feathered':       {'value': 0},
    }

    logic = Logic()

    logic.init_xml_root('main-controller')
    logic.logic_to_xml(program, variables, period='1s', process_updates=True)

    module = ET.Element('module', {'name': 'logic'})
    module.text = 'ot-sim-logic-module {{config_file}}'

    config.append_to_root(logic.root)
    config.append_to_cpu(module)

    if not anemo:
      anemo = self.extract_app_node(node.metadata.controllers.anemometer)

    mb = Modbus()
    mb.init_xml_root('client', anemo)
    mb.registers_to_xml(self.__anemometer_registers(anemo))

    config.append_to_root(mb.root)

    if not yaw:
      yaw = self.extract_app_node(node.metadata.controllers.yaw)

    mb = Modbus()
    mb.init_xml_root('client', yaw)
    mb.registers_to_xml(self.__yaw_registers())

    config.append_to_root(mb.root)

    for hostname in node.metadata.controllers.blades:
      blade = Box({
        'hostname': hostname,
        'metadata': {},
        'topology': self.extract_node(hostname),
      })

      mb = Modbus()
      mb.init_xml_root('client', blade)
      mb.registers_to_xml(self.__blade_registers())

      config.append_to_root(mb.root)

    module = ET.Element('module', {'name': 'modbus'})
    module.text = 'ot-sim-modbus-module {{config_file}}'

    config.append_to_cpu(module)

    dnp = DNP3()
    dnp.init_xml_root('server', node)
    dnp.init_outstation_xml()

    registers = [
      Register('binary-read-write', 'turbine.emergency-stop', {'sbo': str(sbo).lower()}),
      Register('analog-read-write', 'yaw.dir-error',          {'sbo': str(sbo).lower()}),
      Register('analog-read',       'yaw.current'),
      Register('analog-read',       'yaw.setpoint'),
      Register('analog-read',       'turbine.mw-output'),
      Register('binary-read',       'feathered'),
    ] + self.__anemometer_registers(anemo)

    dnp.registers_to_xml(registers)

    config.append_to_root(dnp.root)

    module = ET.Element('module', {'name': 'dnp3'})
    module.text = 'ot-sim-dnp3-module {{config_file}}'

    config.append_to_cpu(module)

    config_file = f'{self.ot_sim_dir}/{node.hostname}.xml'
    config.to_file(config_file)

    kwargs = {
      'src': config_file,
      'dst': '/etc/ot-sim/config.xml',
    }

    self.add_inject(hostname=node.hostname, inject=kwargs)


  def __anemometer(self, node):
    if isinstance(node, str):
      node = self.extract_app_node(node)

    assert(node.metadata.type == "anemometer")

    tmpl = self.templates.get(node.metadata.get('template', 'default'), {}).get('anemometer', {})

    registers = []

    weather  = node.metadata.get('weather', tmpl.get('weather', {}))
    src_data = weather.get('replayData', '/phenix/injects/weather.csv')
    columns  = weather.get('columns', [])
    dst_data = '/etc/ot-sim/data/weather.csv'

    kwargs = {
      'src': src_data,
      'dst': dst_data,
    }

    self.add_inject(hostname=node.hostname, inject=kwargs)

    turbine = ET.Element('wind-turbine')
    anemo   = ET.SubElement(turbine, 'anemometer')
    data    = ET.SubElement(anemo, 'weather-data')

    for col in columns:
      ET.SubElement(data, 'column', {'name': col['name']}).text = col['tag']
      registers.append(Register('analog-read', col['tag'],  {'scaling': 2}))

    ET.SubElement(anemo, 'data-path').text = dst_data

    module = ET.Element('module', {'name': 'turbine-anemometer'})
    module.text = 'ot-sim-wind-turbine-anemometer-module {{config_file}}'

    config = Config(self.metadata)
    config.init_xml_root(node.metadata)

    config.append_to_root(turbine)
    config.append_to_cpu(module)

    mb = Modbus()
    mb.init_xml_root('server', node)
    mb.registers_to_xml(registers)

    module = ET.Element('module', {'name': 'modbus'})
    module.text = 'ot-sim-modbus-module {{config_file}}'

    config.append_to_root(mb.root)
    config.append_to_cpu(module)

    config_file = f'{self.ot_sim_dir}/{node.hostname}.xml'
    config.to_file(config_file)

    kwargs = {
      'src': config_file,
      'dst': '/etc/ot-sim/config.xml',
    }

    self.add_inject(hostname=node.hostname, inject=kwargs)


  def __yaw_controller(self, node):
    if isinstance(node, str):
      node = self.extract_app_node(node)

    assert(node.metadata.type == 'yaw-controller')

    tmpl = self.templates.get(node.metadata.get('template', 'default'), {}).get('yaw-controller', {})

    config = Config(self.metadata)
    config.init_xml_root(node.metadata)

    mb = Modbus()
    mb.init_xml_root('server', node)
    mb.registers_to_xml(self.__yaw_registers())

    module = ET.Element('module', {'name': 'modbus'})
    module.text = 'ot-sim-modbus-module {{config_file}}'

    config.append_to_root(mb.root)
    config.append_to_cpu(module)

    md      = node.metadata.get('yaw', tmpl.get('yaw', {}))
    initial = md.get('initialPosition', 0)
    rate    = md.get('degreePerSecond', 0.1)

    program = f"""
      current_yaw = current_yaw == 0 ? yaw_setpoint : current_yaw
      adjust = yaw_setpoint != current_yaw
      dir = yaw_setpoint > current_yaw ? 1 : -1
      current_yaw = adjust ? current_yaw + (dir * {rate}) : current_yaw
    """

    variables = {
      'current_yaw':  {'value': initial, 'tag': 'yaw.current'},
      'yaw_setpoint': {'value': 0,       'tag': 'yaw.setpoint'},
    }

    logic = Logic()

    logic.init_xml_root('yaw-controller')
    logic.logic_to_xml(program, variables, period='1s', process_updates=True)

    module = ET.Element('module', {'name': 'logic'})
    module.text = 'ot-sim-logic-module {{config_file}}'

    config.append_to_root(logic.root)
    config.append_to_cpu(module)

    config_file = f'{self.ot_sim_dir}/{node.hostname}.xml'
    config.to_file(config_file)

    kwargs = {
      'src': config_file,
      'dst': '/etc/ot-sim/config.xml',
    }

    self.add_inject(hostname=node.hostname, inject=kwargs)


  def __blade_controller(self, hostname, md = {}):
    node = Box({
      'hostname': hostname,
      'metadata': md,
      'topology': self.extract_node(hostname),
    })

    config = Config(self.metadata)
    config.init_xml_root(node.metadata)

    mb = Modbus()
    mb.init_xml_root('server', node)
    mb.registers_to_xml(self.__blade_registers())

    module = ET.Element('module', {'name': 'modbus'})
    module.text = 'ot-sim-modbus-module {{config_file}}'

    config.append_to_root(mb.root)
    config.append_to_cpu(module)

    config_file = f'{self.ot_sim_dir}/{hostname}.xml'
    config.to_file(config_file)

    kwargs = {
      'src': config_file,
      'dst': '/etc/ot-sim/config.xml',
    }

    self.add_inject(hostname=hostname, inject=kwargs)


  def __anemometer_registers(self, node):
    tmpl = self.templates.get(node.metadata.get('template', 'default'), {}).get('anemometer', {})

    weather   = node.metadata.get('weather', tmpl.get('weather', {}))
    columns   = weather.get('columns', [])
    registers = []

    for col in columns:
      registers.append(Register('analog-read', col['tag'], {'scaling': 2}))

    return registers


  def __yaw_registers(self):
    return [
      Register('analog-read',       'yaw.current',  {'scaling': 2}),
      Register('analog-read-write', 'yaw.setpoint', {'scaling': 2}),
    ]


  def __blade_registers(self):
    return [
      Register('binary-read-write', 'feathered', {}),
    ]


def main():
  WindTurbine()


if __name__ == '__main__':
  main()
