<?xml version="1.0" encoding="utf-8"?>
<SCEPTRE>
    <field-device>

        <name>${fd_config.name}</name>
% if cycle_time:
        <cycle-time>${cycle_time}</cycle-time>
% else:
        <cycle-time>1000</cycle-time>
% endif
        <tags>
<%
def intercambio(dictionary, string):
    # sort keys by length, in reverse order
    for item in sorted(dictionary.keys(), key = len, reverse = True):
        string = string.replace(item, dictionary[item])
    return string
%>\
% for protocol in fd_config.protocols:
    % for device in protocol.devices:
        % for register in device.registers:
            <%
            input_regs = ['analog-input', 'binary-input',
                            'input-register', 'discrete-input']
            if register.regtype in input_regs:
                io_name = fd_config.name+'_'+'I'+str(register.addr)
            else:
                io_name = fd_config.name+'_'+'O'+str(register.addr)
            type_ = register.fieldtype.split('-')[0]
            %>
            <external-tag>
                <name>var_${io_name}</name>
                <io>${io_name}</io>
                <type>${type_}</type>
            </external-tag>
        % endfor
    % endfor
% endfor
        </tags>
        <comms>
% for protocol in fd_config.protocols:
    % if protocol.protocol == 'dnp3':
            <dnp3-server>
                <endpoint>tcp://${fd_config.ipaddr}:20000</endpoint>
                <address>10</address>
                <event-logging>${fd_config.name}-dnp3-outstation.log</event-logging>
    % elif protocol.protocol == 'dnp3-serial':
            <dnp3-server>
                <endpoint>${protocol.serial_dev}</endpoint>
                <address>${fd_config.ipaddr.split('.')[-1]}</address>
                <event-logging>${fd_config.name}-dnp3-outstation.log</event-logging>
    % elif protocol.protocol == 'modbus':
            <modbus-server>
                <endpoint>tcp://${fd_config.ipaddr}:502</endpoint>
                <event-logging>${fd_config.name}-modbus-tcp-server.log</event-logging>
    % elif protocol.protocol == 'modbus-serial':
            <modbus-server>
                <endpoint>${protocol.serial_dev}</endpoint>
                <event-logging>${fd_config.name}-modbus-tcp-server.log</event-logging>
                <ip>${fd_config.ipaddr}</ip>
    % elif protocol.protocol == 'bacnet':
            <bacnet-server>
	        <endpoint>udp://${fd_config.ipaddr}:47808</endpoint>
		<instance>${fd_config.counter}</instance>
                <event-logging>${fd_config.name}-bacnet-server.log</event-logging>
    % elif protocol.protocol == 'iec60870-5-104':
            <iec60870-5-104-server>
            <rpoll-rate>2</rpoll-rate>
            <endpoint>tcp://${fd_config.ipaddr}:2404</endpoint>
            <event-logging>${fd_config.name}-104-outstation.log</event-logging>
    % else:
            <NOT IMPLEMENTED ERROR!>
    % endif
    % for device in protocol.devices:
        % for register in device.registers:
            <%
            input_regs = ['analog-input', 'binary-input',
                            'input-register', 'discrete-input']
            if register.regtype in input_regs:
                io_name = fd_config.name+'_'+'I'+str(register.addr)
            else:
                io_name = fd_config.name+'_'+'O'+str(register.addr)
            %>
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
    % if protocol.protocol == 'dnp3' or protocol.protocol == 'dnp3-serial':
            </dnp3-server>
    % elif protocol.protocol == 'modbus' or protocol.protocol == 'modbus-serial':
            </modbus-server>
    % elif protocol.protocol == 'bacnet':
            </bacnet-server>
    % elif protocol.protocol == 'iec60870-5-104':
            </iec60870-5-104-server>
    % else:
            </NOT IMPLEMENTED ERROR!>
    % endif
% endfor
        </comms>
<%
mapa_nombre_entrada = {}
%>\
        <input>
            <endpoint>${fd_config.publish_endpoint}</endpoint>
% for protocol in fd_config.protocols:
    % for device in protocol.devices:
        % for register in device.registers:
            <%
            input_regs = ['analog-input', 'binary-input',
                            'input-register', 'discrete-input']
            if register.regtype in input_regs:
                io_name = fd_config.name+'_'+'I'+str(register.addr)
            else:
                continue
            binary_regs = ['binary-input', 'binary-output',
                            'discrete-input', 'coil']
            mapa_nombre_entrada[register.devname+'.'+register.field] = 'var_'+io_name
            %>
            % if register.regtype in binary_regs:
            <binary>
            % else:
            <analog>
            % endif
                <id>${io_name}</id>
                <name>${register.devname}.${register.field}</name>
            % if register.regtype in binary_regs:
            </binary>
            % else:
            </analog>
            % endif
        % endfor
    % endfor
% endfor
        </input>
<%
mapa_nombre_salida = {}
%>\
        <output>
            <endpoint>${fd_config.server_endpoint}</endpoint>
% for protocol in fd_config.protocols:
    % for device in protocol.devices:
        % for register in device.registers:
            <%
            input_regs = ['analog-input', 'binary-input',
                            'input-register', 'discrete-input']
            if register.regtype in input_regs:
                continue
            else:
                io_name = fd_config.name+'_'+'O'+str(register.addr)
            binary_regs = ['binary-input', 'binary-output',
                            'discrete-input', 'coil']
            mapa_nombre_salida[register.devname+'.'+register.field] = 'var_'+io_name
            %>
            % if register.regtype in binary_regs:
            <binary>
            % else:
            <analog>
            % endif
                <id>${io_name}</id>
                <name>${register.devname}.${register.field}</name>
            % if register.regtype in binary_regs:
            </binary>
            % else:
            </analog>
            % endif
        % endfor
    % endfor
% endfor
        </output>
% if logic:
        <logic>
            <![CDATA[
            <% lines = logic.split(';') %>
            % for line in lines:
                % if line:
                    <%
                    partes = line.split('=', 1)
                    salida = intercambio(mapa_nombre_salida, partes[0]).strip()
                    entrada = intercambio(mapa_nombre_entrada, partes[1]).strip()
                    %>
            ${salida} = ${entrada}
                % endif
            % endfor
            ]]>
        </logic>
% endif
    </field-device>
</SCEPTRE>
