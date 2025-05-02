import phenix_apps.common.error as error
import phenix_apps.apps.sceptre.configs.infrastructures as infra


def get_fdconfig_class(infrastructure: str) -> type:
    if infrastructure == 'power-transmission':
        base_class = infra.PowerTransmissionInfrastructure
    elif infrastructure == 'power-distribution':
        base_class = infra.PowerDistributionInfrastructure
    elif infrastructure == 'batch-process':
        base_class = infra.BatchProcessInfrastructure
    elif infrastructure == 'hvac':
        base_class = infra.HVACInfrastructure
    elif infrastructure == 'fuel':
        base_class = infra.FuelInfrastructure
    elif infrastructure == 'rtds':
        base_class = infra.RTDSInfrastructure
    elif infrastructure == 'opalrt':
        base_class = infra.OPALRTInfrastructure
    elif infrastructure == 'waterway':
        base_class = infra.WaterwayInfrastructure
    elif infrastructure == 'battery':
        base_class = infra.BatteryInfrastructure
    else:
        raise error.AppError(f"Infrastructure: {infrastructure} not supported")

    class FieldDeviceConfig(base_class):
        def __init__(self, provider, name: str, interfaces, devices_by_protocol, publish_endpoint, server_endpoint, device_subtype, reg_config, counter):
            super().__init__()
            if name in reg_config.keys():
                self.reg_config = reg_config[name]
            else:
                self.reg_config = {}
            self.provider = provider
            self.name = name
            self.ipaddr = interfaces.get("tcp", "")
            self.serial_dev = interfaces.get("serial", "[]")
            self.protocols = self.__generate_protocols(devices_by_protocol, base_class)
            self.server_endpoint = server_endpoint
            self.publish_endpoint = publish_endpoint
            self.device_subtype = device_subtype
            self.counter = counter

        def __generate_protocols(self, devices_by_protocol: dict, base_class: type) -> list:
            protocols_list = []
            for protocol in devices_by_protocol.keys():
                if 'serial' in protocol:
                    protocols_list.append(SerialProtocol(
                        protocol,
                        devices_by_protocol[protocol],
                        base_class,
                        self.serial_dev.pop(0),
                        self.reg_config
                    ))
                else:
                    protocols_list.append(Protocol(
                        protocol, devices_by_protocol[protocol], base_class, self.reg_config
                    ))
            infra.Register.reset_addresses()
            return protocols_list

    return FieldDeviceConfig


class Protocol:
    def __init__(self, protocol, devices, infrastructure_class, reg_config):
        self.protocol = protocol
        self.devices = self.__generate_devices(devices, infrastructure_class, reg_config)

    def __generate_devices(self, devices, infrastructure_class, reg_config) -> list:
        devices_list = []
        for device in devices:
            kwargs = {}
            for key in device.keys():
                if key == 'type' or key == 'name':
                    continue
                kwargs[key] = device[key]
            if self.protocol in reg_config.keys():
                devices_list.append(infrastructure_class.create_device(device['type'], device['name'], self.protocol,reg_config=reg_config[self.protocol], **kwargs))
            else:
                devices_list.append(infrastructure_class.create_device(device['type'], device['name'], self.protocol,[], **kwargs))
        return devices_list


class SerialProtocol(Protocol):
    def __init__(self, protocol, devices, infrastructure_class, serial_dev, reg_config):
        self.serial_dev = serial_dev
        super().__init__(protocol, devices, infrastructure_class, reg_config)


class OpcConfig:
    def __init__(self, fd_configs, opc_ip):
        """Build an OPC configuration object, used to build the OPC
        config file from a mako template.

        Args:
            fd_configs (configs.OpcConfig.Device): A list of field devices to be used in OPC configuration
            opc_ip (string): The IP address of the primary OPC server
        """
        self.channel_list = []
        for fd_config in fd_configs.values():
            for protocol in fd_config.protocols:
                if protocol.protocol == 'bacnet':
                    chan_name = 'ChannelBACnet'
                else:
                    chan_name = (f'Channel{protocol.protocol.title().replace("-", "_")}'
                                 f'{fd_config.name.title().replace("-","_")}')
                # search channel_list and return item if we find a matching channel
                # name, otherwise None
                channel = next((x for x in self.channel_list if x.name == chan_name), None)
                pending_channel = False
                if not channel:
                    pending_channel = True
                    channel = OpcConfig.Channel(chan_name, protocol.protocol,
                                                opc_ip, fd_config.ipaddr)
                device = OpcConfig.Device(fd_config.name, protocol.protocol,
                                          fd_config.ipaddr, fd_config.range,
                                          fd_config.counter)
                for fd_dev in protocol.devices:
                    for register in fd_dev.registers:
                        device.add_tag(register)
                channel.add_device(device)
                if pending_channel:
                    self.channel_list.append(channel)

    class Channel:
        def __init__(self, name, protocol, opc_ip, fd_ip):
            self.name = name
            self.protocol = protocol
            self.opc_ip = opc_ip
            self.fd_ip = fd_ip
            self.devices = []

        def add_device(self, device) -> None:
            self.devices.append(device)

    class Device:
        def __init__(self, fd_name, protocol, fd_ip, range_, fd_counter=None):
            self.fd_name = fd_name
            self.protocol = protocol
            self.fd_ip = fd_ip
            self.fd_counter = fd_counter
            self.range = range_
            self.tags = []

        def add_tag(self, tag) -> None:
            self.tags.append(tag)


class HmiConfig:
    def __init__(self, fd_configs: dict):
        """Build an HMI configuration object, used to build the HMI
        config file from a mako template.

        Args:
            fd_configs (configs.HmiConfig.Device): A dictionary of field devices to be used in OPC configuration
        """
        self.devices = {}
        self.populate_devices(fd_configs.values())

    def populate_devices(self, fd_configs) -> None:
        for fd in fd_configs:
            for protocol in fd:
                for device in protocol:
                    devname = device.name
                    devtype = device.type
                    if devtype not in self.devices.keys():
                        self.devices[devtype] = {}
                    if devname not in self.devices[devtype].keys():
                        self.devices[devtype][devname] = HmiConfig.Device(devname, devtype,
                                                                          protocol, fd, device)
                    else:
                        self.devices[devtype][devname].add_monitor(protocol, fd, device)

    class Device:
        def __init__(self, name: str, type: str, monitor_proto, monitor_fd, monitor_dev):
            self.name = name
            self.type = type
            self.protos = [monitor_proto]
            self.fds = [monitor_fd]
            self.regs = monitor_dev.registers

        def add_monitor(self, monitor_proto, monitor_fd, monitor_dev) -> None:
            self.protos.append(monitor_proto)
            self.fds.append(monitor_fd)
            self.regs.append(monitor_dev.registers)
            if self.type == 'branch':
                # order of member lists depends on branch name
                # only works with at most 2 fds per branch
                bus = ''
                for protocol in self.fds[-1]:
                    for dev in protocol:
                        if dev.type == 'bus':
                            bus = dev.name
                            break
                    if bus:
                        break
                from_, to_ = self.name.split('_')[-1].split('-')
                if f'bus-{to_}' != bus:
                    self.protos = list(reversed(self.protos))
                    self.fds = list(reversed(self.fds))
                    self.regs = list(reversed(self.regs))


class HistorianConfig:
    def __init__(
        self, opc_config=None, opc_ip ="", replication_ips=[],
        scadaConnectToHistorian=False, fields=[]
        ):
        """Build a historian configuration object, used to build the historian
        config file from a mako template.

        All arguments are optional.  Any data not available in the configuration
        object will be ommitted from the config file

        Args:
            opc_config (configs.OpcConfig): The configuration object built for OPC
            opc_ip (string): The IP address of the primary OPC server
            replication_ips (list of strings): A list of IP addresses for the servers running the backup historians
            scadaConnectToHistorian (Boolean): True if the SCADA server connects to the primary historian
            fields (list of strings): A list of field "types" (i.e. mw, mvar, tank_level).  Only these fields "types"
                                      will be added to a historians configuration from OPC.  If the list is empty
                                      all fields will be added.
        """
        # Dictionary to hold the tags that will be retreived from OPC and stroed in the
        # historian.  Key = TopicName, Value = List of associated tags (points)
        self.tags = {}
        self.opc_ip = opc_ip
        self.replication_ips = replication_ips
        self.scadaConnectToHistorian = scadaConnectToHistorian

        if opc_config is not None:
            # Loop through channel list (for channel in opc_config.channel_list) and get each channel name
            for channel in opc_config.channel_list:
                # Loop through each device (for tag in device.devices) and get tag name
                for device in channel.devices:
                    device_name = "Device" + device.fd_name.title().replace('-', '_')
                    tag_list = []
                    for register in device.tags:
                        if not fields or register.field in fields:
                            tagname = f'{register.devname}_{register.regtype}_{register.field}'.replace('-', '_')
                            tag_list.append(tagname)
                    if tag_list:
                        topic_name = channel.name + "_" + device_name
                        self.tags[topic_name] = tag_list
