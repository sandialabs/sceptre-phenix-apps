<?xml version="1.0" encoding="utf-8"?>
<SCEPTRE>

<field-device>

    <name>${name}</name>

    <tags>
<%
def intercambio(dictionary, string):
    # sort keys by length, in reverse order
    for item in sorted(dictionary.keys(), key = len, reverse = True):
        string = string.replace(item, dictionary[item])
    return string

sunspec_register = ''
%>\
% for fd_config in server_configs:
    % for protocol in fd_config.protocols:
        % if protocol.protocol == 'sunspec':
                <internal-tag>
                    <!-- Well-known SunSpec device map identifier 'SunS' as 32-bit
                    integer (0x53756e53). -->
                    <name>identifier</name>
                    <value>1400204883</value>
                </internal-tag>
                <internal-tag>
                    <name>end</name>
                    <value>65535</value>
                </internal-tag>
                <internal-tag>
                    <name>end-length</name>
                    <value>0</value>
                </internal-tag>
        % endif
        % for device in protocol.devices:
            % for register in device.registers:
                % if device.protocol == 'sunspec':
                    % if register.static:
                <%
                if register.name == 'length':
                    sunspec_register += '-length'
                else:
                    sunspec_register = register.name
                %>
                <internal-tag>
                    <name>${sunspec_register}</name>
                        % if 'string' in register.fieldtype:
                    <string>${register.field}</string>
                        % else:
                    <value>${register.field}</value>
                        % endif
                </internal-tag>
                    % else:
                        <%
                        io_name = fd_config.name + '_' + 'O' + str(register.addr)
                        %>
                <external-tag>
                    <name>${register.name}</name>
                    <io>${io_name}</io>
                        % if register.field in ['active']:
                    <type>binary</type>
                        % else:
                    <type>analog</type>
                        % endif
                </external-tag>
                    % endif
                % else:
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
                % endif
            % endfor
        % endfor
    % endfor
% endfor
        </tags>

    <comms>
################################# CLIENT ########################################
<% proto_counter = 0 %>		
% for fep_protocol in fep_config.protocols:
        % if fep_protocol.protocol == 'dnp3' or fep_protocol.protocol == 'dnp3-serial':

            <dnp3-client>

                <address>1</address>
                <scan-rate>5</scan-rate>
        % elif fep_protocol.protocol == 'modbus' or fep_protocol.protocol == 'modbus-serial':

            <modbus-client>

        % elif fep_protocol.protocol == 'iec60870-5-104':

            <iec60870-5-104-client>
        % else:

            <NOT IMPLEMENTED ERROR!>
        % endif
    % for config in server_configs:
	% for protocol in config.protocols:
	    % if protocol.protocol == fep_protocol.protocol:
            	% if protocol.protocol == 'dnp3':
                    <dnp3-connection>
                        <endpoint>tcp://${config.ipaddr}:20000</endpoint>
                        <address>10</address>
		    % elif protocol.protocol == 'dnp3-serial':
			<dnp3-connection>
			    <endpoint>${fep_protocol.serial_dev}</endpoint>
			    <address>${config.ipaddr.split('.')[-1]}</address>
		    % elif protocol.protocol == 'modbus':
			<modbus-connection>
			    <endpoint>tcp://${config.ipaddr}:502</endpoint>
		    % elif protocol.protocol == 'modbus-serial':
			<modbus-connection>
			    <endpoint>${fep_protocol.serial_dev}</endpoint>
		    % elif protocol.protocol == 'iec60870-5-104':
			<iec60870-5-104-connection>
			    <endpoint>tcp://${config.ipaddr}:2404</endpoint>
		    % else:
			<NOT IMPLEMENTED ERROR!>
		    % endif
		    % for device in protocol.devices:
			% for register in device.registers:
			    <%
			    input_regs = ['analog-input', 'binary-input',
					  'input-register', 'discrete-input']
			    if register.regtype in input_regs:
				io_name = config.name+'_'+'I'+str(register.addr)
			    else:
				io_name = config.name+'_'+'O'+str(register.addr)
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

			</dnp3-connection>

		    % elif protocol.protocol == 'modbus' or protocol.protocol == 'modbus-serial':

			</modbus-connection>

		    % elif protocol.protocol == 'iec60870-5-104':

			</iec60870-5-104-connection>
		    
		    % else:

			</NOT IMPLEMENTED ERROR!>
		   % endif
	       % endif
        % endfor
    % endfor
   <% proto_port = 1330 + proto_counter%>
    % if fep_protocol.protocol == 'dnp3' or fep_protocol.protocol == 'dnp3-serial':
	     <command-interface>tcp://${command_endpoint}:${proto_port}</command-interface>

        </dnp3-client>
    % elif fep_protocol.protocol == 'modbus' or fep_protocol.protocol == 'modbus-serial':
	<command-interface>tcp://${command_endpoint}:${proto_port}</command-interface>

        </modbus-client>
    % elif fep_protocol.protocol == 'iec60870-5-104':
	<command-interface>tcp://${command_endpoint}:${proto_port}</command-interface>
            
        </iec60870-5-104-client>

    % else:

        </NOT IMPLEMENTED ERROR!>
    % endif
	<% proto_counter += 1 %>		
% endfor

################################# SERVER ########################################
% for fep_protocol in fep_config.protocols:
    % if fep_protocol.protocol == 'dnp3' or fep_protocol.protocol == 'dnp3-serial':
            <dnp3-server>
                <endpoint>tcp://${fep_config.ipaddr}:20000</endpoint>
                <address>10</address>
                <event-logging>${fep_config.name}-dnp3-outstation.log</event-logging>
    % elif fep_protocol.protocol == 'modbus' or fep_protocol.protocol == 'modbus-serial':
            <modbus-server>
                <endpoint>tcp://${fep_config.ipaddr}:502</endpoint>
                <event-logging>${fep_config.name}-modbus-server.log</event-logging>
    % elif fep_protocol.protocol == 'sunspec':
            <sunspec-tcp-server>
                <port>5502</port>
                <event-logging>${fep_config.name}-sunspec-tcp-server.log</event-logging>
                <register>
                    <address>40000</address>
            <uint32>identifier</uint32>
                </register>
                <ip>${fep_config.ipaddr}</ip>
    % elif fep_protocol.protocol == 'iec60870-5-104':
            <iec60870-5-104-server>
            <rpoll-rate>2</rpoll-rate>
            <endpoint>tcp://${fd_config.ipaddr}:2404</endpoint>
            <event-logging>${fd_config.name}-104-outstation.log</event-logging>
    % else:
            <NOT IMPLEMENTED ERROR!>
    % endif
    <% fep_device_iter = iter(fep_protocol.devices) %>
    % for fd_config in server_configs:
        % for protocol in fd_config.protocols:
		% if protocol.protocol == fep_protocol.protocol:
		    % for device in protocol.devices:
			<% fep_device = next(fep_device_iter) %>
			    <% fep_register_iter = iter(fep_device.registers) %>
			% for register in device.registers:
			    % if protocol.protocol == 'sunspec':
			      <%
			      sunspec_reg_addr = next(fep_register_iter).addr
			      if register.name == 'length':
				  sunspec_reg_name += '-length'
			      else:
				  sunspec_reg_name = register.name
			      %>
				<register>
				    <address>${sunspec_reg_addr}</address>
				% if register.scaling:
				    <scaling-factor>${register.scaling}</scaling-factor>
				% endif
				    <${register.fieldtype}>${sunspec_reg_name}</${register.fieldtype}>
				</register>
			    % else:
				    <%
				    input_regs = ['analog-input', 'binary-input',
						  'input-register', 'discrete-input']
				    fep_reg_addr = next(fep_register_iter).addr
				    if register.regtype in input_regs:
					io_name = fd_config.name+'_'+'I'+str(register.addr)
				    else:
					io_name = fd_config.name+'_'+'O'+str(register.addr)
				    %>
				    <${register.regtype}>
					<address>${fep_reg_addr}</address>
					    % if register.regtype in ['holding-register', 'input-register']:
					<max-value>${register.range[1]}</max-value>
					<min-value>${register.range[0]}</min-value>
					    % endif
					<tag>var_${io_name}</tag>
				    </${register.regtype}>
			    % endif
			% endfor
		    % endfor
	    % endif
        % endfor
    % endfor
    % if fep_protocol.protocol == 'dnp3' or fep_protocol.protocol == 'dnp3-serial':
            </dnp3-server>
    % elif fep_protocol.protocol == 'modbus' or fep_protocol.protocol == 'modbus-serial':
            </modbus-server>
    % elif fep_protocol.protocol == 'sunspec':
                <register>
                <address>${sunspec_reg_addr + 1}</address>
            <uint16>end</uint16>
                </register>
                <register>
                <address>${sunspec_reg_addr + 2}</address>
            <uint16>end-length</uint16>
                </register>
            </sunspec-tcp-server>
    % elif fep_protocol.protocol == 'iec60870-5-104':
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
            <endpoint>${fep_config.publish_endpoint}</endpoint>
% for fd_config in server_configs:
    % for protocol in fd_config.protocols:
        % for device in protocol.devices:
            % for register in device.registers:
                % if protocol.protocol == 'sunspec':
                    % if not register.static:
                        <%
                        io_name = fd_config.name + '_' + 'I' + str(register.addr)
                        %>
                        % if register.field in ['active']:
                <binary>
                        % else:
                <analog>
                        % endif
                    <id>${io_name}</id>
                    <name>${register.devname}.${register.field}</name>
                        % if register.field in ['active']:
                </binary>
                        % else:
                </analog>
                        % endif
                    % endif
                % else:
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
                % endif
            % endfor
        % endfor
    % endfor
% endfor
        </input>
<%
mapa_nombre_salida = {}
%>\
        <output>
            <endpoint>${fep_config.server_endpoint}</endpoint>
% for fd_config in server_configs:
    % for protocol in fd_config.protocols:
        % for device in protocol.devices:
            % for register in device.registers:
                % if protocol.protocol == 'sunspec':
                    % if not register.static:
                        <%
                        io_name = fd_config.name + '_' + 'O' + str(register.addr)
                        %>
                        % if register.field in ['active']:
                <binary>
                        % else:
                <analog>
                        % endif
                    <id>${io_name}</id>
                    <name>${register.devname}.${register.field}</name>
                        % if register.field in ['active']:
                </binary>
                        % else:
                </analog>
                        % endif
                    % endif
                % else:
                    <%
		    input_regs = ['analog-input', 'binary-input',
		    'input-register', 'discrete-input']
                    if register.regtype in input_regs:
                        continue
                    else:
                        id_name = fd_config.name+'_'+'O'+str(register.addr)
                        output_name = fd_config.name+'_'+'O'+str(register.addr)
                    binary_regs = ['binary-input', 'binary-output',
                                   'discrete-input', 'coil']
                    mapa_nombre_salida[register.devname+'.'+register.field] = 'var_'+io_name
                    %>
                    % if register.regtype in binary_regs:
                <binary>
                    % else:
                <analog>
                    % endif
                    <id>${id_name}</id>
                    <name>var_${output_name}</name>
                    % if register.regtype in binary_regs:
                </binary>
                    % else:
                </analog>
                    % endif
                % endif
            % endfor
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
