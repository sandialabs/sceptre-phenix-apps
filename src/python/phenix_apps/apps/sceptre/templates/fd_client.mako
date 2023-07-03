<?xml version="1.0" encoding="utf-8"?>
<SCEPTRE>
    <field-device>
        <name>${name}</name>
        <comms>
<%
in_count = {}
out_count = {}
for config in server_configs:
    in_count[config.name] = 0
    out_count[config.name] = 0
protocols = sorted({proto.protocol for x in server_configs for proto in x.protocols})
%>\
% for protocol in protocols:
    % if protocol == 'dnp3' or protocol == 'dnp3-serial':
            <dnp3-client>
                <address>1</address>
                <scan-rate>5</scan-rate>
    % elif protocol == 'modbus' or protocol == 'modbus-serial':
            <modbus-client>
    % elif protocol == 'bacnet':
            <bacnet-client>
                <scan-rate>5</scan-rate>
    % elif protocol == 'iec60870-5-104':
            <iec60870-5-104-client>
    % else:
            <NOT IMPLEMENTED ERROR!>
    % endif
    % for config in server_configs:
        % for proto in config.protocols:
            % if proto.protocol != protocol:
<% continue %>
	    % endif
            % if proto.protocol == 'dnp3':
                <dnp3-connection>
                    <endpoint>tcp://${config.ipaddr}:20000</endpoint>
                    <address>10</address>
            % elif proto.protocol == 'dnp3-serial':
                <dnp3-connection>
                    <endpoint>${config.serial_dev}</endpoint>
                    <address>${config.ipaddr.split('.')[-1]}</address>
            % elif proto.protocol == 'modbus':
                <modbus-connection>
		    <endpoint>tcp://${config.ipaddr}:502</endpoint>
		    <unit-id>1</unit-id>
            % elif proto.protocol == 'modbus-serial':
                <modbus-connection>
                    <endpoint>${config.serial_dev}</endpoint>
            % elif proto.protocol == 'bacnet':
                <bacnet-connection>
                    <endpoint>udp://${config.ipaddr}:47808</endpoint>
		    <instance>${config.counter}</instance>
            % elif proto.protocol == 'iec60870-5-104':
                <iec60870-5-104-connection>
                    <endpoint>tcp://${config.ipaddr}:2404</endpoint>
            % else:
                <NOT IMPLEMENTED ERROR!>
            % endif
            % for device in proto.devices:
                % for register in device.registers:
<%
input_regs = ['analog-input', 'binary-input',
              'input-register', 'discrete-input']
if register.regtype in input_regs:
    io_name = config.name+'_'+'I'+str(in_count[config.name])
    in_count[config.name] += 1
else:
    io_name = config.name+'_'+'O'+str(out_count[config.name])
    out_count[config.name] += 1
%>\
                    <${register.regtype}>
                        <address>${register.addr}</address>
                        % if register.regtype in ['holding-register', 'input-register']:
                        <max-value>${register.range[1]}</max-value>
                        <min-value>${register.range[0]}</min-value>
                        % endif
                        <tag>var_${io_name}</tag>
                    </${register.regtype}>
                % endfor
            % endfor
            % if proto.protocol == 'dnp3' or proto.protocol == 'dnp3-serial':
                </dnp3-connection>
            % elif proto.protocol == 'modbus':
                </modbus-connection>
            % elif proto.protocol == 'bacnet':
                </bacnet-connection>
            % elif proto.protocol == 'iec60870-5-104':
                </iec60870-5-104-connection>
            % else:
                </NOT IMPLEMENTED ERROR!>
            % endif
        % endfor
    % endfor
    % if protocol == 'dnp3' or protocol == 'dnp3-serial':
                <command-interface>tcp://${command_endpoint}:1330</command-interface>
            </dnp3-client>
    % elif protocol == 'modbus' or protocol == 'modbus-serial':
                <command-interface>tcp://${command_endpoint}:1331</command-interface>
            </modbus-tcp-client>
    % elif protocol == 'bacnet':
                <command-interface>tcp://${command_endpoint}:1332</command-interface>
            </bacnet-client>
    % elif protocol == 'iec60870-5-104':
                <command-interface>tcp://${command_endpoint}:1330</command-interface>
            </iec60870-5-104-client>
    % else:
            </NOT IMPLEMENTED ERROR!>
    %endif
% endfor
        </comms>
    </field-device>
</SCEPTRE>
