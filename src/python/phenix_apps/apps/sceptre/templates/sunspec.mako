<?xml version="1.0" encoding="utf-8"?>
<SCEPTRE>
    <field-device>
        <name>${name}</name>
% if cycle_time:
        <cycle-time>${cycle_time}</cycle-time>
% else:
        <cycle-time>1000</cycle-time>
% endif
        <tags>
% if infra == 'power-transmission':
            <external-tag>
                <name>bus</name>
                <io>I0</io>
                <type>analog</type>
            </external-tag>
            <external-tag>
                <name>base_kv</name>
                <io>I1</io>
                <type>analog</type>
            </external-tag>
            <external-tag>
                <name>mvar</name>
                <io>I2</io>
                <type>analog</type>
            </external-tag>
            <external-tag>
                <name>mw_max</name>
                <io>I3</io>
                <type>analog</type>
            </external-tag>
            <external-tag>
                <name>mw_min</name>
                <io>I4</io>
                <type>analog</type>
            </external-tag>
            <external-tag>
                <name>mva_base</name>
                <io>I5</io>
                <type>analog</type>
            </external-tag>
            <external-tag>
                <name>freq</name>
                <io>I6</io>
                <type>analog</type>
            </external-tag>
            <external-tag>
                <name>voltage_setpoint</name>
                <io>I7</io>
                <type>analog</type>
            </external-tag>
            <external-tag>
                <name>voltage_angle</name>
                <io>I8</io>
                <type>analog</type>
            </external-tag>
            <external-tag>
                <name>current</name>
                <io>I9</io>
                <type>analog</type>
            </external-tag>
            <external-tag>
                <name>active</name>
                <io>O0</io>
                <type>binary</type>
            </external-tag>
            <external-tag>
                <name>voltage</name>
                <io>O1</io>
                <type>analog</type>
            </external-tag>
            <external-tag>
                <name>mw</name>
                <io>O2</io>
                <type>analog</type>
            </external-tag>
% endif
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
<%
sunspec_reg_name = ''
%>
% for register in device.registers:
    % if register.static:
        <%
        if register.name == 'length':
            sunspec_reg_name += '-length'
        else:
            sunspec_reg_name = register.name
        %>
            <internal-tag>
                <name>${sunspec_reg_name}</name>
                    % if 'string' in register.fieldtype:
                <string>${register.field}</string>
                    % else:
                <value>${register.field}</value>
                    % endif
            </internal-tag>
    % else:
        <%
        io_name = 'O' + str(register.addr + 100)
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
% endfor
        </tags>
        <comms>
            <sunspec-tcp-server>
                <ip>${ipaddr}</ip>
                <port>502</port>
                <event-logging>${name}-sunspec-tcp-server.log</event-logging>
                <register>
                    <address>40000</address>
        		    <uint32>identifier</uint32>
        		</register>
<%
sunspec_reg_addr = 0
sunspec_reg_name = ''
%>
% for register in device.registers:
    <%
    sunspec_reg_addr = register.addr
    if register.name == 'length':
        sunspec_reg_name += '-length'
    else:
        sunspec_reg_name = register.name
    %>
                <register>
                    <address>${register.addr}</address>
                % if register.scaling:
                    <scaling-factor>${register.scaling}</scaling-factor>
                % endif
                    <${register.fieldtype}>${sunspec_reg_name}</${register.fieldtype}>
                </register>
% endfor
                <register>
	                <address>${sunspec_reg_addr + 1}</address>
        		    <uint16>end</uint16>
                </register>
                <register>
	                <address>${sunspec_reg_addr + 2}</address>
        		    <uint16>end-length</uint16>
                </register>
            </sunspec-tcp-server>
        </comms>
        <input>
            <endpoint>${publish_endpoint}</endpoint>
% if infra == 'power-transmission':
            <analog>
                <id>I0</id>
                <name>${devname}.bus</name>
            </analog>
            <analog>
                <id>I1</id>
                <name>${devname}.base_kv</name>
            </analog>
            <analog>
                <id>I2</id>
                <name>${devname}.mvar</name>
            </analog>
            <analog>
                <id>I3</id>
                <name>${devname}.mw_max</name>
            </analog>
            <analog>
                <id>I4</id>
                <name>${devname}.mw_min</name>
            </analog>
            <analog>
                <id>I5</id>
                <name>${devname}.mva_base</name>
            </analog>
            <analog>
                <id>I6</id>
                <name>${devname}.freq</name>
            </analog>
            <analog>
                <id>I7</id>
                <name>${devname}.voltage_setpoint</name>
            </analog>
            <analog>
                <id>I8</id>
                <name>${devname}.voltage_angle</name>
            </analog>
            <analog>
                <id>I9</id>
                <name>${devname}.current</name>
            </analog>
% endif
% for register in device.registers:
    % if not register.static:
        <%
        io_name = 'I' + str(register.addr + 100)
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
% endfor
        </input>
        <output>
            <endpoint>${server_endpoint}</endpoint>
% if infra == 'power-transmission':
            <binary>
                <id>O0</id>
                <name>${devname}.active</name>
            </binary>
            <analog>
                <id>O1</id>
                <name>${devname}.voltage</name>
            </analog>
            <analog>
                <id>O2</id>
                <name>${devname}.mw</name>
            </analog>
% endif
% for register in device.registers:
    % if not register.static:
        <%
        io_name = 'O' + str(register.addr + 100)
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
% endfor
        </output>
% if infra == 'power-transmission':
        <logic>
            <![CDATA[
                A = current

                AphA = A / 3
                AphB = A / 3
                AphC = A / 3

                phase_kv = voltage * base_kv * (3 ** 0.5)

                PhVphA = (phase_kv * 1000) / 3
                PhVphB = (phase_kv * 1000) / 3
                PhVphC = (phase_kv * 1000) / 3

                Hz = freq
                W = mw * 1_000_000
                VAr = mvar * 1_000_000

                mw = WMaxLim_Ena != 0 ? WRtg * (WMaxLimPct / 100.0) : mw

                q = VArPct_Ena != 0 ? VARtg * (VArMaxPct / 100.0) : mvar
                voltage = q / mva_base
            ]]>
        </logic>
% endif
    </field-device>
</SCEPTRE>
