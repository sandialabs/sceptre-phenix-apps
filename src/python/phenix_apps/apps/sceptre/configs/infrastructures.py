import phenix_apps.apps.sceptre.protocols.sunspec as sunspec


class Infrastructure:
    def __init__(self):
        self.infrastructure_name = ""
        self.device_fields = {}
        self.device_fields['analog-read'] = {}
        self.device_fields['analog-read-write'] = {}
        self.device_fields['binary-read'] = {}
        self.device_fields['binary-read-write'] = {}
        self.range = 0, 1  # min/max value for Modbus points

    def register(self, name: str) -> None:
        self.infrastructure_name = name

    def get_infrastructure_name(self) -> str:
        return self.infrastructure_name

    def get_fields(self, field_type, device_type) -> list:
        if device_type in self.device_fields[field_type]:
            return self.device_fields[field_type][device_type]
        else:
            return []

    def add_analog_read_fields(self, device_type, fields) -> None:
        self.device_fields['analog-read'][device_type] = fields

    def add_analog_read_write_fields(self, device_type, fields) -> None:
        self.device_fields['analog-read-write'][device_type] = fields

    def add_binary_read_fields(self, device_type, fields) -> None:
        self.device_fields['binary-read'][device_type] = fields

    def add_binary_read_write_fields(self, device_type, fields) -> None:
        self.device_fields['binary-read-write'][device_type] = fields

    def add_integer_read_fields(self, device_type, fields) -> None:
        self.device_fields['integer-read'][device_type] = fields

    def add_integer_read_write_fields(self, device_type, fields) -> None:
        self.device_fields['integer-read-write'][device_type] = fields


class PowerTransmissionInfrastructure(Infrastructure):
    def __init__(self):
        super().__init__()
        super().register('power-transmission')
        self.range = -600, 1800

    INFRA = 'power-transmission'

    @staticmethod
    def create_device(device_type, device_name, protocol, reg_config, **kwargs):
        if type(device_type) == str and device_type.lower() == 'generator':
            device_kwargs = {'range'        : (-600, 1800),
                      'analog-read'         : kwargs.get('analog-read',
                            ['voltage', 'mw', 'mvar']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['active']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['active'])}
        elif type(device_type) == str and device_type.lower() == 'bus':
            device_kwargs = {'range'        : (-600, 1800),
                      'analog-read'         : kwargs.get('analog-read',
                            ['voltage', 'angle', 'gen_mw',
                             'gen_mvar', 'load_mw', 'load_mvar',
                             'shunt_mvar']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['active', 'slack']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['active'])}
        elif type(device_type) == str and device_type.lower() == 'load':
            device_kwargs = {'range'        : (-600, 1800),
                      'analog-read'         : kwargs.get('analog-read',
                            ['mw', 'mvar']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['active']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['active'])}
        elif type(device_type) == str and device_type.lower() == 'branch':
            device_kwargs = {'range'        : (-600, 1800),
                      'analog-read'         : kwargs.get('analog-read',
                            ['charging', 'current', 'source_mw',
                            'target_mw', 'phase_angle']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['active']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['active'])}
        elif type(device_type) == str and device_type.lower() == 'shunt':
            device_kwargs = {'range'        : (-600, 1800),
                      'analog-read'         : kwargs.get('analog-read',
                            ['actual_mvar']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['active']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['active'])}
        elif type(device_type) == str and device_type.lower() == 'inverter':
            device_kwargs = {
                'infrastructure': 'PowerTransmission',
                'analog-read-write': kwargs.get('analog-read-write', [1, 103, 120, 123]),
            }
        infra = PowerTransmissionInfrastructure.INFRA
        return Device(device_type, device_name, protocol, reg_config,
                      infrastructure=infra, **device_kwargs)


class PowerDistributionInfrastructure(Infrastructure):
    def __init__(self):
        super().__init__()
        super().register('power-distribution')
        self.range = -600, 1800

    INFRA = 'power-distribution'

    @staticmethod
    def create_device(device_type, device_name, protocol,reg_config, **kwargs):
        if type(device_type) == str and device_type.lower() == 'generator':
            device_kwargs = {'range'        : (-600, 1800),
                      'analog-read'         : kwargs.get('analog-read',
                            ['voltage_mag_p1', 'voltage_mag_p2',
                             'voltage_mag_p3', 'voltage_ang_p1',
                             'voltage_ang_p2', 'voltage_ang_p3',
                             'current_mag_p1', 'current_mag_p2',
                             'current_mag_p3', 'current_ang_p1',
                             'current_ang_p2', 'current_ang_p3',
                             'active_power_output', 'real_power_p1',
                             'real_power_p2', 'real_power_p3',
                             'reactive_power_p1', 'reactive_power_p2',
                             'reactive_power_p3', 'power_factor']),
                      'analog-read-write'   : kwargs.get('analog-read-write',
                            ['active_power_output', 'power_factor']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['active']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['active'])}
        elif type(device_type) == str and device_type.lower() == 'bus':
            device_kwargs = {'range'        : (-600, 1800),
                      'analog-read'         : kwargs.get('analog-read',
                            ['voltage_mag_p1', 'voltage_mag_p2',
                             'voltage_mag_p3', 'voltage_ang_p1',
                             'voltage_ang_p2', 'voltage_ang_p3'])}
        elif type(device_type) == str and device_type.lower() == 'load':
            device_kwargs = {'range'        : (-600, 1800),
                      'analog-read'         : kwargs.get('analog-read',
                            ['voltage_mag_p1', 'voltage_mag_p2',
                             'voltage_mag_p3', 'voltage_ang_p1',
                             'voltage_ang_p2', 'voltage_ang_p3',
                             'current_mag_p1', 'current_mag_p2',
                             'current_mag_p3', 'current_ang_p1',
                             'current_ang_p2', 'current_ang_p3',
                             'real_power_p1', 'real_power_p2',
                             'real_power_p3', 'reactive_power_p1',
                             'reactive_power_p2', 'reactive_power_p3']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['active']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['active'])}
        elif type(device_type) == str and device_type.lower() == 'shunt':
            device_kwargs = {'range'        : (-600, 1800),
                      'analog-read'         : kwargs.get('analog-read',
                            ['voltage_mag_p1', 'voltage_mag_p2',
                             'voltage_mag_p3', 'voltage_ang_p1',
                             'voltage_ang_p2', 'voltage_ang_p3',
                             'current_mag_p1', 'current_mag_p2',
                             'current_mag_p3', 'current_ang_p1',
                             'current_ang_p2', 'current_ang_p3',
                             'real_power_p1', 'real_power_p2',
                             'real_power_p3', 'reactive_power_p1',
                             'reactive_power_p2', 'reactive_power_p3']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['active']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['active'])}
        elif type(device_type) == str and device_type.lower() == 'branch':
            device_kwargs = {'range'        : (-600, 1800),
                      'analog-read'         : kwargs.get('analog-read',
                            ['voltage_mag_src_p1', 'voltage_mag_src_p2',
                             'voltage_mag_src_p3', 'voltage_ang_src_p1',
                             'voltage_ang_src_p2', 'voltage_ang_src_p3',
                             'current_mag_src_p1', 'current_mag_src_p2',
                             'current_mag_src_p3', 'current_ang_src_p1',
                             'current_ang_src_p2', 'current_ang_src_p3',
                             'real_power_src_p1', 'real_power_src_p2',
                             'real_power_src_p3', 'reactive_power_src_p1',
                             'reactive_power_src_p2', 'reactive_power_src_p3']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['active']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['active'])}
        elif type(device_type) == str and device_type.lower() == 'transformer':
            device_kwargs = {'range'        : (-600, 1800),
                      'analog-read'         : kwargs.get('analog-read',
                            ['voltage_mag_wdg1_p1', 'voltage_mag_wdg1_p2',
                             'voltage_mag_wdg1_p3', 'voltage_ang_wdg1_p1',
                             'voltage_ang_wdg1_p2', 'voltage_ang_wdg1_p3',
                             'current_mag_wdg1_p1', 'current_mag_wdg1_p2',
                             'current_mag_wdg1_p3', 'current_ang_wdg1_p1',
                             'current_ang_wdg1_p2', 'current_ang_wdg1_p3',
                             'voltage_mag_wdg2_p1', 'voltage_mag_wdg2_p2',
                             'voltage_mag_wdg2_p3', 'voltage_ang_wdg2_p1',
                             'voltage_ang_wdg2_p2', 'voltage_ang_wdg2_p3',
                             'current_mag_wdg2_p1', 'current_mag_wdg2_p2',
                             'current_mag_wdg2_p3', 'current_ang_wdg2_p1',
                             'current_ang_wdg2_p2', 'current_ang_wdg2_p3',
                             'real_power_p1', 'real_power_p2',
                             'real_power_p3', 'reactive_power_p1',
                             'reactive_power_p2', 'reactive_power_p3',
                             'tap_setting_wdg1', 'tap_setting_wdg2']),
                      'analog-read-write'   : kwargs.get('analog-read-write',
                            ['tap_setting_wdg1', 'tap_setting_wdg2']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['active']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['active'])}
        elif type(device_type) == str and device_type.lower() == 'inverter':
            device_kwargs = {'range'        : (-600, 1800),
                      'analog-read'         : kwargs.get('analog-read',
                            ['voltage_mag_p1', 'voltage_mag_p2',
                             'voltage_mag_p3', 'voltage_ang_p1',
                             'voltage_ang_p2', 'voltage_ang_p3',
                             'current_mag_p1', 'current_mag_p2',
                             'current_mag_p3', 'current_ang_p1',
                             'current_ang_p2', 'current_ang_p3',
                             'active_power_output', 'real_power_p1',
                             'real_power_p2', 'real_power_p3',
                             'reactive_power_p1', 'reactive_power_p2',
                             'reactive_power_p3']),
                      'analog-read-write'   : kwargs.get('analog-read-write',
                            [1, 101, 123, 126]),
                      'binary-read'         : kwargs.get('binary-read',
                            ['active']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['active'])}
        infra = PowerDistributionInfrastructure.INFRA
        return Device(device_type, device_name, protocol, reg_config,
                      infrastructure=infra, **device_kwargs)


class BatchProcessInfrastructure(Infrastructure):
    def __init__(self):
        super().__init__()
        super().register('batch-process')
        self.range = 0, 1000

    INFRA = 'batch-process'

    @staticmethod
    def create_device(device_type, device_name, protocol, reg_config, **kwargs):
        if type(device_type) == str and device_type.lower() == 'storagetank':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['level_setpoint', 'flow_in', 'flow_out',
                             'tank_level', 'tank_volume', 'temperature',
                             'volume_to_drain']),
                      'analog-read-write'   : kwargs.get('analog-read-write',
                            ['flow_in', 'level_setpoint']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['fill_control', 'empty_control',
                             'emergency_shutoff']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['fill_control', 'empty_control'])}
        elif type(device_type) == str and device_type.lower() == 'heatingtank':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['heating_rate', 'level_setpoint',
                             'flow_in', 'flow_out',
                             'temperature_setpoint', 'tank_level',
                             'tank_volume', 'temperature']),
                      'analog-read-write'   : kwargs.get('analog-read-write',
                            ['heating_rate', 'level_setpoint',
                             'temperature_setpoint']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['fill_control', 'empty_control',
                             'heater_control', 'emergency_shutoff']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['fill_control', 'empty_control',
                             'heater_control'])}
        elif type(device_type) == str and device_type.lower() == 'mixingtank':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['requested_fill_rate', 'mixing_rate',
                             'requested_empty_rate', 'level_setpoint',
                             'flow_in', 'flow_out',
                             'mix_percent_setpoint', 'tank_level',
                             'tank_volume', 'mix_percent',
                             'temperature']),
                      'analog-read-write'   : kwargs.get('analog-read-write',
                            ['mixing_rate', 'level_setpoint',
                             'mix_percent_setpoint']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['fill_control', 'empty_control',
                             'mixing_control', 'emergency_shutoff']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['fill_control', 'empty_control',
                             'mixing_control'])}
        elif type(device_type) == str and device_type.lower() == 'pump':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['flow', 'temperature']),
                      'analog-read-write'   : kwargs.get('analog-read-write',
                            ['flow']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['active', 'control']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['active', 'control'])}
        elif type(device_type) == str and device_type.lower() == 'generator':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['fuel'])}
        elif type(device_type) == str and device_type.lower() == 'fillingstation':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['request', 'volume_wasted', 'backlog'])}
        elif type(device_type) == str and device_type.lower() == 'valve':
            device_kwargs = {'range'        : (0, 1000),
                      'binary-read'         : kwargs.get('binary-read',
                            ['open']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['open'])}
        infra = BatchProcessInfrastructure.INFRA
        return Device(device_type, device_name, protocol, reg_config,
                      infrastructure=infra, **device_kwargs)


class HVACInfrastructure(Infrastructure):
    def __init__(self):
        super().__init__()
        super().register('hvac')
        self.range = 0, 1000

    INFRA = 'hvac'

    @staticmethod
    def create_device(device_type, device_name, protocol, reg_config, **kwargs):
        if type(device_type) == str and device_type.lower() == 'room':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['temperature'])}
        elif type(device_type) == str and device_type.lower() == 'thermostat':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['setpoint', 'margin']),
                      'analog-read-write'         : kwargs.get('analog-read-write',
                            ['change_setpoint', 'change_margin'])}
        elif type(device_type) == str and device_type.lower() == 'fan':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['speed']),
                      'analog-read-write'         : kwargs.get('analog-read-write',
                            ['change_speed'])}
        elif type(device_type) == str and device_type.lower() == 'heater':
            device_kwargs = {'range'        : (0, 1000),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['turn_on']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['on'])}
        elif type(device_type) == str and device_type.lower() == 'cooler':
            device_kwargs = {'range'        : (0, 1000),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['turn_on']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['on'])}
        infra = HVACInfrastructure.INFRA
        return Device(device_type, device_name, protocol, reg_config,
                      infrastructure=infra, **device_kwargs)


class FuelInfrastructure(Infrastructure):
    def __init__(self):
        super().__init__()
        super().register('fuel')
        self.range = 0, 1000

    INFRA = 'fuel'

    @staticmethod
    def create_device(device_type, device_name, protocol,reg_config,**kwargs):
        if type(device_type) == str and device_type.lower() == 'storagetank':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['level_setpoint', 'flow_in',
                             'tank_volume', 'volume_to_drain']),
                      'analog-read-write'   : kwargs.get('analog-read-write',
                            ['flow_in', 'level_setpoint']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['fill_control']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['fill_control'])}
        elif type(device_type) == str and device_type.lower() == 'pump':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['flow', 'voltage_in']),
                      'analog-read-write'   : kwargs.get('analog-read-write',
                            ['flow', 'voltage_in']),
                      'binary-read'         : kwargs.get('binary-read',
                            ['active', 'control']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['active', 'control'])}
        elif type(device_type) == str and device_type.lower() == 'generator':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['fuel'])}
        elif type(device_type) == str and device_type.lower() == 'fillingstation':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['request', 'volume_wasted', 'backlog'])}
        elif type(device_type) == str and device_type.lower() == 'valve':
            device_kwargs = {'range'        : (0, 1000),
                      'binary-read'         : kwargs.get('binary-read',
                            ['open']),
                      'binary-read-write'   : kwargs.get('binary-read-write',
                            ['open'])}
        infra = BatchProcessInfrastructure.INFRA
        return Device(device_type, device_name, protocol, reg_config,
                      infrastructure=infra, **device_kwargs)


class OPALRTInfrastructure(Infrastructure):
    """OPALRT infrastructure for the OPALRT dynamic simulator."""

    def __init__(self):
        super().__init__()
        super().register('opalrt')
        self.range = -32767.0, 32767.0

    @staticmethod
    def create_device(device_type, device_name, protocol, reg_config, **kwargs):
        if type(device_type) == str and device_type.lower() == 'analog-read':
            device_kwargs = {
                'range': (-32767.0, 32767.0),
                'analog-read': kwargs.get('analog-read', ['value']),
            }
            return Device(device_type, device_name, protocol, reg_config, **device_kwargs)
        elif type(device_type) == str and device_type.lower() == 'analog-read-write':
            device_kwargs = {
                'range': (-32767.0, 32767.0),
                'analog-read-write': kwargs.get('analog-read-write', ['value']),
            }
            return Device(device_type, device_name, protocol, reg_config, **device_kwargs)
        elif type(device_type) == str and device_type.lower() == 'binary-read':
            device_kwargs = {
                'range': (0, 1000),
                'binary-read': kwargs.get('binary-read', ['value']),
            }
            return Device(device_type, device_name, protocol, reg_config, **device_kwargs)
        elif type(device_type) == str and device_type.lower() == 'binary-read-write':
            device_kwargs = {
                'range': (0, 1000),
                'binary-read-write': kwargs.get('binary-read-write', ['value']),
            }
            return Device(device_type, device_name, protocol, reg_config, **device_kwargs)


class RTDSInfrastructure(Infrastructure):
    """Real-Time Dynamic Simulator (RTDS) infrastructure."""
    def __init__(self):
        super().__init__()
        super().register('rtds')
        self.range = -32767.0, 32767.0

    @staticmethod
    def create_device(device_type, device_name, protocol, reg_config, **kwargs):
        if type(device_type) == str and device_type.lower() == 'analog-read':
            device_kwargs = {
                'range': (-32767.0, 32767.0),
                'analog-read': kwargs.get('analog-read', ['real', 'angle']),
            }
            return Device(device_type, device_name, protocol, reg_config, **device_kwargs)
        elif type(device_type) == str and device_type.lower() == 'analog-read-write':
            device_kwargs = {
                'range': (-32767.0, 32767.0),
                'analog-read-write': kwargs.get('analog-read-write', ['value']),
            }
            return Device(device_type, device_name, protocol, reg_config, **device_kwargs)
        elif type(device_type) == str and device_type.lower() == 'binary-read-write':
            device_kwargs = {
                'range': (0, 1000),
                'binary-read-write': kwargs.get('binary-read-write', ['closed']),
            }
            return Device(device_type, device_name, protocol, reg_config, **device_kwargs)


class WaterwayInfrastructure(Infrastructure):
    def __init__(self):
        super().__init__()
        super().register('waterway')
        self.range = 0, 1000

    INFRA = 'waterway'

    @staticmethod
    def create_device(device_type, device_name, protocol,reg_config,**kwargs):
        if type(device_type) == str and device_type.lower() == 'water':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['height'])}
        elif type(device_type) == str and device_type.lower() == 'gate':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['open']),
                      'analog-read-write'         : kwargs.get('analog-read-write',
                            ['open'])}
        elif type(device_type) == str and device_type.lower() == 'valve':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['open']),
                      'analog-read-write'         : kwargs.get('analog-read-write',
                            ['open'])}
        elif type(device_type) == str and device_type.lower() == 'boat-sensor':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['active', 'direction'])}
        elif type(device_type) == str and device_type.lower() == 'boat':
            device_kwargs = {'range'        : (0, 1000),
                      'analog-read'         : kwargs.get('analog-read',
                            ['location', 'direction'])}
        infra = infrastructure=WaterwayInfrastructure.INFRA
        return Device(device_type, device_name, protocol, reg_config,
                      infrastructure=infra, **device_kwargs)


class BatteryInfrastructure(Infrastructure):
    """
    Infrastructure for a specific Simulink model of a battery system.

    TODO: There needs to be a better way of specifying this stuff
    directly in the scenario file and not have to do a
    infrastructure for every Simulink model.
    """

    MAPPING = {
        "bmsscrtu": {
            "analog-read": ["istack", "vstack", "socstack"],
            "binary-read-write": ["disconnect"],
        },
        "bmsse": {
            "analog-read": ["istack", "vstack", "socstack"],
        },
        "battstack": {
            "analog-read": ["istack", "vstack"],
        },
        "cps": {
            "analog-read": ["pinj", "qinj", "vbess", "ibess"],
        },
    }

    def __init__(self):
        super().__init__()
        super().register("battery")
        self.range = -32767.0, 32767.0

    @staticmethod
    def create_device(
        device_type, device_name, protocol, reg_config, **kwargs
    ):
        if type(device_type) != str:
            return None

        if device_type not in BatteryInfrastructure.MAPPING:
            return None

        device_kwargs = BatteryInfrastructure.MAPPING[device_type]
        device_kwargs["range"] = (-32767.0, 32767.0)

        return Device(device_type, device_name, protocol, reg_config, **device_kwargs)


class Device(Infrastructure):
    def __init__(self, device_type, device_name, protocol, reg_config, **kwargs):
        super().__init__()
        self.device_type = device_type
        self.device_name = device_name
        self.protocol = protocol
        self.range = kwargs.get('range', None)
        self.infrastructure = kwargs.get('infrastructure', None)
        self.reg_config = reg_config
        super().add_analog_read_fields(device_type, kwargs.get(
                            'analog-read', []))
        super().add_analog_read_write_fields(device_type, kwargs.get(
                            'analog-read-write', []))
        super().add_binary_read_fields(device_type, kwargs.get(
                            'binary-read', []))
        super().add_binary_read_write_fields(device_type, kwargs.get(
                            'binary-read-write', []))
        self.registers = []
        self.__generate_register_list()

    def __generate_register_list(self) -> None:
        field_types  = ['analog-read', 'analog-read-write',
                        'binary-read', 'binary-read-write']
        for field_type in field_types:
            fields = self.get_fields(field_type, self.device_type)
            if self.protocol == 'sunspec':
                if self.device_type == 'inverter' and field_type == 'analog-read-write':
                    sunspec_device = sunspec.SunSpecDevice(self.infrastructure, self.device_name, self.registers)
                    sunspec_device.generate_registers(fields)
                continue
            for field in fields:
                fd_register = Register(self.device_name, field, field_type,
                                self.device_type, self.protocol, self.range,self.reg_config)
                self.registers.append(fd_register)


class Register:
    TYPE = {}
    TYPE['dnp3'] = {
        'analog-read': 'analog-input', 'analog-read-write': 'analog-output',
        'binary-read': 'binary-input', 'binary-read-write': 'binary-output'
    }
    TYPE['dnp3-serial'] = {
        'analog-read': 'analog-input', 'analog-read-write': 'analog-output',
        'binary-read': 'binary-input', 'binary-read-write': 'binary-output'
    }
    TYPE['modbus'] = {
        'analog-read': 'input-register', 'analog-read-write': 'holding-register',
        'binary-read': 'discrete-input', 'binary-read-write': 'coil'
    }
    TYPE['modbus-serial'] = {
        'analog-read': 'input-register', 'analog-read-write': 'holding-register',
        'binary-read': 'discrete-input', 'binary-read-write': 'coil'
    }
    TYPE['bacnet'] = {
        'analog-read': 'analog-input', 'analog-read-write': 'analog-output',
        'binary-read': 'binary-input', 'binary-read-write': 'binary-output'}
    TYPE['iec60870-5-104'] = {
        'analog-read': 'analog-input', 'analog-read-write': 'analog-output',
        'binary-read': 'binary-input', 'binary-read-write': 'binary-output'}
    addresses = {'dnp3': 0, 'dnp3-serial': 0, 'bacnet': 0, 'iec60870-5-104': 1,
        'input-register': 30000, 'holding-register': 40000, 'discrete-input': 10000,
        'coil': 0, 'float-point': 1000, 'single-point': 3000}

    def __init__(self, devname, field, fieldtype, devtype, protocol, range_, reg_config):
        self.devname = devname
        self.field = field
        self.fieldtype = fieldtype
        self.regtype = type(self).TYPE[protocol][fieldtype]
        self.protocol = protocol
        self.devtype = devtype
        self.range = range_

        # Protocol-wide register numbers used for DNP3 registers
        if not bool(reg_config):
            if 'dnp3' in self.protocol or 'bacnet' in self.protocol or 'iec60870-5-104' in self.protocol:
                self.addr = type(self).addresses[self.protocol]
                type(self).addresses[self.protocol] += 1
            else:
                self.addr = type(self).addresses[self.regtype]
                type(self).addresses[self.regtype] += 1
        else:
            for config in reg_config:
                if self.fieldtype in config.keys() and self.devname == config["name"] and self.devtype == config["type"]:
                    for item in config[self.fieldtype]:
                        if self.field == item['field'] and self.regtype == item['register_type']:
                            register_number = item["register_number"]
                            if 'dnp3' in self.protocol or 'bacnet' in self.protocol or 'iec60870-5-104' in self.protocol:
                                self.addr = type(self).addresses[self.protocol]
                                type(self).addresses[self.protocol] = register_number
                            else:
                                self.addr = type(self).addresses[self.regtype]
                                type(self).addresses[self.regtype] = register_number

            # DEFAULT: if something isn't right
            if 'dnp3' in self.protocol or 'bacnet' in self.protocol or 'iec60870-5-104' in self.protocol:
                self.addr = type(self).addresses[self.protocol]
                type(self).addresses[self.protocol] += 1
            else:
                self.addr = type(self).addresses[self.regtype]
                type(self).addresses[self.regtype] += 1

    @staticmethod
    def reset_addresses():
        Register.addresses = {'dnp3': 0, 'dnp3-serial': 0, 'bacnet': 0, 'iec60870-5-104': 1, 'input-register': 30000,
        'holding-register': 40000, 'discrete-input': 10000, 'coil': 0,
        'float-point': 1000, 'single-point': 3000}
