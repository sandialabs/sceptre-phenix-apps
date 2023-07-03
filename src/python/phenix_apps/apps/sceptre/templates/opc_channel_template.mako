<%namespace name="opc_device" file="opc_device_template.mako"/>\
<%def name="create(channel)">\
		<servermain:Channel>
			<servermain:Name>${channel.name}</servermain:Name>
			% if channel.protocol == 'dnp3' or channel.protocol == 'dnp3-serial':
			<servermain:Driver>DNP Master Ethernet</servermain:Driver>
			% elif channel.protocol == 'modbus' or channel.protocol == 'modbus-serial':
			<servermain:Driver>Modbus Ethernet</servermain:Driver>
			% elif channel.protocol == 'iec60870':
			<servermain:Driver>IEC 60870-5-104 Master</servermain:Driver>
			% elif channel.protocol == 'bacnet':
			<servermain:Driver>BACnet</servermain:Driver>
			% endif
			<servermain:Ethernet>
				<servermain:NetworkAdapter>Intel(R) PRO/1000... [${channel.opc_ip}]</servermain:NetworkAdapter>
			</servermain:Ethernet>
			<servermain:WriteOptimizations>
				<servermain:Method>Write last value only</servermain:Method>
				<servermain:WritesToRead>10</servermain:WritesToRead>
			</servermain:WriteOptimizations>
			<servermain:NonNormalizedFloatHandlingType>Unmodified</servermain:NonNormalizedFloatHandlingType>
			<servermain:CommunicationSerialization>
				<servermain:VirtualNetwork>None</servermain:VirtualNetwork>
				<servermain:TransactionsPerCycle>1</servermain:TransactionsPerCycle>
			</servermain:CommunicationSerialization>
			<servermain:InterDeviceDelay>
				<servermain:DelayMS>0</servermain:DelayMS>
			</servermain:InterDeviceDelay>
			<servermain:Diagnostics>
				<servermain:Enabled>false</servermain:Enabled>
				<servermain:Identifier>123456789</servermain:Identifier>
			</servermain:Diagnostics>
			% if channel.protocol == 'dnp3' or channel.protocol == 'dnp3-serial':
			<servermain:CustomChannelProperties xmlns:dnp_master_ethernet="http://www.kepware.com/schemas/dnp_master_ethernet">
				<dnp_master_ethernet:ChannelCommunications>
					<dnp_master_ethernet:Protocol>PROTOCOL_TCP</dnp_master_ethernet:Protocol>
					<dnp_master_ethernet:SourcePort>0</dnp_master_ethernet:SourcePort>
					<dnp_master_ethernet:DestinationIP>${channel.fd_ip}</dnp_master_ethernet:DestinationIP>
					<dnp_master_ethernet:DestinationPort>20000</dnp_master_ethernet:DestinationPort>
				</dnp_master_ethernet:ChannelCommunications>
				<dnp_master_ethernet:Timing>
					<dnp_master_ethernet:ConnectTimeoutSeconds>3</dnp_master_ethernet:ConnectTimeoutSeconds>
					<dnp_master_ethernet:ResponseTimeoutMilliseconds>10000</dnp_master_ethernet:ResponseTimeoutMilliseconds>
				</dnp_master_ethernet:Timing>
			% elif channel.protocol == 'modbus' or channel.protocol == 'modbus-serial':
			<servermain:CustomChannelProperties xmlns:modbus_ethernet="http://www.kepware.com/schemas/modbus_ethernet">
				<modbus_ethernet:UseMultipleSockets>true</modbus_ethernet:UseMultipleSockets>
				<modbus_ethernet:MaxSocketsPerDevice>1</modbus_ethernet:MaxSocketsPerDevice>
			% elif channel.protocol == 'iec60870':
			<servermain:CustomChannelProperties xmlns:iec_60870_5_104_master="http://www.kepware.com/schemas/iec_60870_5_104_master">
				<iec_60870_5_104_master:ChannelCommunications>
					<iec_60870_5_104_master:DestinationHost>${channel.fd_ip}</iec_60870_5_104_master:DestinationHost>
					<iec_60870_5_104_master:DestinationPort>2404</iec_60870_5_104_master:DestinationPort>
					<iec_60870_5_104_master:ConnectTimeout>3</iec_60870_5_104_master:ConnectTimeout>
				</iec_60870_5_104_master:ChannelCommunications>
				<iec_60870_5_104_master:IEC60870Settings>
					<iec_60870_5_104_master:OriginatorAddress>0</iec_60870_5_104_master:OriginatorAddress>
					<iec_60870_5_104_master:COTSize>Two Octets</iec_60870_5_104_master:COTSize>
					<iec_60870_5_104_master:t1>15000</iec_60870_5_104_master:t1>
					<iec_60870_5_104_master:t2>10000</iec_60870_5_104_master:t2>
					<iec_60870_5_104_master:t3>20000</iec_60870_5_104_master:t3>
					<iec_60870_5_104_master:k>12</iec_60870_5_104_master:k>
					<iec_60870_5_104_master:w>8</iec_60870_5_104_master:w>
					<iec_60870_5_104_master:RxBufferSize>253</iec_60870_5_104_master:RxBufferSize>
					<iec_60870_5_104_master:IncrementalTimeout>30000</iec_60870_5_104_master:IncrementalTimeout>
					<iec_60870_5_104_master:FirstCharWait>0</iec_60870_5_104_master:FirstCharWait>
				</iec_60870_5_104_master:IEC60870Settings>
			% elif channel.protocol == 'bacnet':
            <servermain:CustomChannelProperties xmlns:bacnet="http://www.kepware.com/schemas/bacnet">
                <bacnet:NetworkSettings>
                    <bacnet:Port>47808</bacnet:Port>
                    <bacnet:NetworkNumber>1</bacnet:NetworkNumber>
                </bacnet:NetworkSettings>
                <bacnet:ForeignDeviceSettings>
                    <bacnet:ForeignDevice>false</bacnet:ForeignDevice>
                    <bacnet:RemoteBBMDIP>10.113.5.222</bacnet:RemoteBBMDIP>
                    <bacnet:RegistrationTTL>60</bacnet:RegistrationTTL>
                </bacnet:ForeignDeviceSettings>
                <bacnet:AdvancedSettings>
                    <bacnet:AllowCOVWithEmptyNPDU>false</bacnet:AllowCOVWithEmptyNPDU>
                </bacnet:AdvancedSettings>
			% endif
			</servermain:CustomChannelProperties>
			<servermain:DeviceList>
			% for device in channel.devices:
                            % if device.protocol == channel.protocol:
${opc_device.create(device)}\
                            % endif
			% endfor
			</servermain:DeviceList>
		</servermain:Channel>
</%def>\
