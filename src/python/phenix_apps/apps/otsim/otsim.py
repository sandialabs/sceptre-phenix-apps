import os

import lxml.etree as ET

from phenix_apps.apps   import AppBase
from phenix_apps.common import logger, utils

from phenix_apps.apps.otsim.config         import Config
from phenix_apps.apps.otsim.device         import FEP, FieldDeviceClient, FieldDeviceServer
from phenix_apps.apps.otsim.infrastructure import Infrastructure
from phenix_apps.apps.otsim.logic          import Logic
from phenix_apps.apps.otsim.nodered        import NodeRed


class OTSim(AppBase):
  def __init__(self):
    AppBase.__init__(self, 'ot-sim')

    self.otsim_dir = f"{self.exp_dir}/ot-sim"
    os.makedirs(self.otsim_dir, exist_ok=True)

    self.__init_defaults()
    self.execute_stage()

    # We don't (currently) let the parent AppBase class handle this step
    # just in case app developers want to do any additional manipulation
    # after the appropriate stage function has completed.
    print(self.experiment.to_json())


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

          if any(key in broker for key in ['base-fed-count', 'dynamic']):
            if hostname not in self.brokers:
              self.brokers[hostname] = {
                'feds':      broker.get('base-fed-count', 0),
                'dynamic':   broker.get('dynamic', False),
                'log-level': broker.get('log-level', 'SUMMARY'),
                'log-file':  broker.get('log-file', '/var/log/helics-broker.log'),
              }

            self.brokers[hostname]['feds'] += 1

          addr = self.extract_node_interface_ip(hostname, iface)
          assert addr

          # Check to see if helics app is being used. If so, check if ot-sim
          # broker matches root broker. If not, append default port 24000 to
          # address so sub broker is used.
          helics_app = self.extract_app('helics')
          if helics_app:
            root_broker = helics_app.get('metadata', {}).get('broker', {}).get('root', None)

            if root_broker:
              if '|' in root_broker:
                hostname, iface = root_broker.split('|', 1)
                root_broker = self.extract_node_interface_ip(hostname, iface)
              elif ':' in root_broker:
                root_broker, _ = root_broker.split(':', 1)

              if addr != root_broker:
                addr += ':24000'

          return addr
        elif 'address' in broker:
          return broker['address']

  def __process_scan_rate_metadata(self, md):
    if 'helics' in md:
      if 'scan-rate' in md['helics']:
        return md['helics']['scan-rate']
      else:
        return 5
    else:
      return None
    

  def __init_defaults(self):
    self.default_infrastructure = self.metadata.get('infrastructure', 'power-distribution')

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
      
      self.end_time = str(self.metadata['helics'].get('end-time', 36000))

    else:
      self.default_fed      = 'OpenDSS'
      self.default_endpoint = 'OpenDSS/updates'
      self.end_time = str(36000)
  
  # Function used to configure all devices that could have node-red as a
  # metadata tag (fd-client, fep, etc.)
  def __config_node_red(self, device, config):
    if 'node-red' in device.metadata:
      nodered = NodeRed.parse_metadata(device.metadata)

      module = ET.Element('module', {'name': 'node-red'})
      module.text = 'ot-sim-node-red-module {{config_file}}'

      config.append_to_root(nodered.root)
      config.append_to_cpu(module)

      inject = nodered.needs_inject()
      if inject:
        self.add_inject(hostname=device.hostname, inject=inject)


  def pre_start(self):
    logger.log('INFO', f'Starting user application: {self.name}')

    ot_devices = {}
    mappings   = self.metadata.get('infrastructures', {})

    # Field device, assumed to use the I/O module that acts as a HELICS
    # federate. Will use default I/O federate provided in app metadata if
    # not provided as part of the device name(s).
    servers = self.extract_nodes_type('fd-server', False)

    for server in servers:
      md    = server.metadata
      infra = md.get('infrastructure', self.default_infrastructure)

      config  = Config(self.metadata)
      injects = config.init_xml_root(server.metadata)

      for inject in injects: # will at least be an empty list
        self.add_inject(hostname=server.hostname, inject=inject)

      device = FieldDeviceServer(server, infra)
      device.process(mappings)
      device.configure(config)

      ot_devices[server.hostname] = device

      # dict[name, device_dict] -- name could be namespaced by federate
      devices    = {}
      proto_devs = []

      if 'dnp3' in md:
        if isinstance(md['dnp3'], dict):
          proto_devs += md['dnp3'].get('devices', [])
        else:
          proto_devs += md['dnp3']

      if 'modbus' in md:
        if isinstance(md['modbus'], dict):
          proto_devs += md['modbus'].get('devices', [])
        else:
          proto_devs += md['modbus']

      for device in proto_devs:
        assert 'name' in device
        assert 'type' in device

        if not '/' in device['name']:
          device['name'] = f"{self.default_fed}/{device['name']}"

        if not 'endpoint' in device:
          device['endpoint'] = self.default_endpoint

        # handle `endpoint` for this device being set to False
        if device['endpoint'] and not '/' in device['endpoint']:
          fed = device['name'].split('/')[0]
          device['endpoint'] = f"{fed}/{device['endpoint']}"

        if device['name'] in devices:
          assert devices[device['name']] == device
        else:
          devices[device['name']] = device

      if len(devices) > 0:
        infrastructure = Infrastructure(mappings)

        io = ET.Element('io', {'name': 'helics-federate'})
        broker    = ET.SubElement(io, 'broker-endpoint')
        federate  = ET.SubElement(io, 'federate-name')
        log_level = ET.SubElement(io, 'federate-log-level')
        end_time  = ET.SubElement(io, 'end-time')
        
        end_time.text = self.end_time

        if 'helics' in md:
          if 'broker' in md['helics']:
            addr = self.__process_helics_broker_metadata(md)
          else:
            addr = self.__process_helics_broker_metadata(self.metadata)

          assert addr
          broker.text = addr

          if 'federate' in md['helics']:
            if isinstance(md['helics']['federate'], str):
              federate.text  = md['helics']['federate']
              log_level.text = 'SUMMARY'
            else:
              federate.text  = md['helics']['federate'].get('name', server.hostname)
              log_level.text = md['helics']['federate'].get('log-level', 'SUMMARY')
          else:
            federate.text  = server.hostname
            log_level.text = 'SUMMARY'

        else:
          addr = self.__process_helics_broker_metadata(self.metadata)
          assert addr
          
          broker.text    = addr
          federate.text  = server.hostname
          log_level.text = 'SUMMARY'
        
        infrastructure.io_module_xml(io, infra, devices)

        config.append_to_root(io)

        module = ET.Element('module', {'name': 'i/o'})
        module.text = 'ot-sim-io-module {{config_file}}'

        config.append_to_cpu(module)

        annotation = [{'broker': addr, 'fed-count': 1}]
        self.add_annotation(server.hostname, 'helics/federate', annotation)

      if 'logic' in md:
        logic = Logic.parse_metadata(md)

        if logic:
          module = ET.Element('module', {'name': 'logic'})
          module.text = 'ot-sim-logic-module {{config_file}}'

          config.append_to_root(logic.root)
          config.append_to_cpu(module)
      
      self.__config_node_red(server, config)

      config_file = f'{self.otsim_dir}/{server.hostname}.xml'

      config.to_file(config_file)
      self.add_inject(hostname=server.hostname, inject={'src': config_file, 'dst': '/etc/ot-sim/config.xml'})

    # Front-end processor (FEP), assumed to act as a protocol gateway or
    # proxy via two or more protocol modules acting in client/server
    # configurations. Also assumed to **not** include an I/O module.
    feps = self.extract_nodes_type('fep', False)

    # Preload all the FEPs so they can force downstream FEPs to process their
    # configs during their own processing.
    scan_rate_from_md = self.__process_scan_rate_metadata(self.metadata)

    for fep in feps:
      if scan_rate_from_md is not None: 
        ot_devices[fep.hostname] = FEP(fep, {"scan-rate": scan_rate_from_md})
      else: 
        ot_devices[fep.hostname] = FEP(fep)
       
    for fep in feps:
      config  = Config(self.metadata)
      injects = config.init_xml_root(fep.metadata)

      for inject in injects: # will at least be an empty list
        self.add_inject(hostname=fep.hostname, inject=inject)

      device = ot_devices[fep.hostname]
      device.process(ot_devices)
      device.configure(config, ot_devices)

      if 'logic' in fep.metadata:
        logic = Logic.parse_metadata(fep.metadata)

        if logic:
          module = ET.Element('module', {'name': 'logic'})
          module.text = 'ot-sim-logic-module {{config_file}}'

          config.append_to_root(logic.root)
          config.append_to_cpu(module)

      self.__config_node_red(fep, config)

      config_file = f'{self.otsim_dir}/{fep.hostname}.xml'

      config.to_file(config_file)
      self.add_inject(hostname=fep.hostname, inject={'src': config_file, 'dst': '/etc/ot-sim/config.xml'})

    # Field device client, acting as a protocol client via one or more protocol
    # modules. Also assumed to **not** include an I/O module.
    clients = self.extract_nodes_type('fd-client', False)

    # By this point, all the FEPs each client will potentially talk to should
    # have already been configured.

    for client in clients:
      config  = Config(self.metadata)
      injects = config.init_xml_root(client.metadata)

      for inject in injects: # will at least be an empty list
        self.add_inject(hostname=client.hostname, inject=inject)

      device = FieldDeviceClient(client)
      device.process(ot_devices)
      device.configure(config, ot_devices)

      ot_devices[client.hostname] = device

      if 'logic' in client.metadata:
        logic = Logic.parse_metadata(client.metadata)

        if logic:
          module = ET.Element('module', {'name': 'logic'})
          module.text = 'ot-sim-logic-module {{config_file}}'

          config.append_to_root(logic.root)
          config.append_to_cpu(module)
        
      self.__config_node_red(client, config)

      config_file = f'{self.otsim_dir}/{client.hostname}.xml'

      config.to_file(config_file)
      self.add_inject(hostname=client.hostname, inject={'src': config_file, 'dst': '/etc/ot-sim/config.xml'})

    # Create and inject config files for any brokers specified in the app
    # metadata.
    templates = utils.abs_path(__file__, 'templates/')

    for hostname, cfg in self.brokers.items():
      start_file = f'{self.otsim_dir}/{hostname}-helics-broker.sh'

      with open(start_file, 'w') as f:
        utils.mako_serve_template('helics_broker.mako', templates, f, cfg=cfg)

      self.add_inject(hostname=hostname, inject={'src': start_file, 'dst': '/etc/phenix/startup/90-helics-broker.sh'})

    logger.log('INFO', f'Started user application: {self.name}')


def main():
  OTSim()


if __name__ == '__main__':
  main()
