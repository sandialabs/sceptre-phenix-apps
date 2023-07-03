<%namespace name="opc_tag" file="opc_tag_template.mako"/>\
<%def name="create(device)">\
				<servermain:Device>
					<servermain:Name>Device${device.fd_name.title().replace('-', '_')}</servermain:Name>
					<servermain:DiagsIdentifier>123456789</servermain:DiagsIdentifier>
					<servermain:Enabled>true</servermain:Enabled>
					<servermain:Simulated>false</servermain:Simulated>
<% driver = "" %>
					% if device.protocol == 'dnp3' or device.protocol == 'dnp3-serial':
<% driver = "dnp_master_ethernet" %>
					<servermain:ModelInfo xmlns:${driver}="http://www.kepware.com/schemas/${driver}">
						<${driver}:Model>DNP Master Ethernet</${driver}:Model>
					% elif device.protocol == 'modbus' or device.protocol == 'modbus-serial':
					<servermain:ModelInfo xmlns:modbus_ethernet="http://www.kepware.com/schemas/modbus_ethernet">
						<modbus_ethernet:Model>Modbus</modbus_ethernet:Model>
					% elif device.protocol == 'iec60870':
					<servermain:ModelInfo xmlns:iec_60870_5_104_master="http://www.kepware.com/schemas/iec_60870_5_104_master">
						<iec_60870_5_104_master:Model>IEC 60870-5-104 Master</iec_60870_5_104_master:Model>
					% elif device.protocol == 'bacnet':
					<servermain:ModelInfo xmlns:bacnet="http://www.kepware.com/schemas/bacnet">
						<bacnet:Model>BACnet</bacnet:Model>
					% endif
					</servermain:ModelInfo>
					% if device.protocol == 'dnp3' or device.protocol == 'dnp3-serial':
					<servermain:ID Format="Decimal">0</servermain:ID>
					% elif device.protocol == 'modbus' or device.protocol == 'modbus-serial':
					<servermain:ID Format="String">&lt;${device.fd_ip}&gt;.1</servermain:ID>
					% elif device.protocol == 'iec60870':
					<servermain:ID Format="String"/>
					% elif device.protocol == 'bacnet':
					<servermain:ID Format="String">1.${device.fd_counter}</servermain:ID>
					% endif
					% if device.protocol == 'iec60870':
					<servermain:ScanMode>UseClientRate</servermain:ScanMode>
					% else:
					<servermain:ScanMode>ForceAllToFloorRate</servermain:ScanMode>
					% endif
					<servermain:ScanFloorMs>5000</servermain:ScanFloorMs>
					% if device.protocol in ['modbus', 'modbus-serial', 'bacnet']:
					<servermain:Timing>
						<servermain:ConnectionTimeoutSeconds>3</servermain:ConnectionTimeoutSeconds>
						<servermain:ResponseTimeoutMilliseconds>1000</servermain:ResponseTimeoutMilliseconds>
						<servermain:FailAfter>3</servermain:FailAfter>
						<servermain:InterRequestDelayMilliseconds>0</servermain:InterRequestDelayMilliseconds>
					</servermain:Timing>
					% endif
					<servermain:AutoDemotion>
						<servermain:Enabled>false</servermain:Enabled>
						<servermain:DemoteAfter>3</servermain:DemoteAfter>
						<servermain:DemoteForMilliseconds>10000</servermain:DemoteForMilliseconds>
						<servermain:DiscardWrites>false</servermain:DiscardWrites>
					</servermain:AutoDemotion>
					% if device.protocol == 'bacnet':
                    <servermain:AutoTagGeneration>
                        <servermain:Startup>Do not generate on startup</servermain:Startup>
                        <servermain:DuplicateTagAction>Delete on create</servermain:DuplicateTagAction>
                        <servermain:Group/>
                        <servermain:AllowSubGroups>true</servermain:AllowSubGroups>
                    </servermain:AutoTagGeneration>
					% elif device.protocol != 'iec60870':
					<servermain:AutoTagGeneration>
						<servermain:Startup>Do not generate on startup</servermain:Startup>
						<servermain:DuplicateTagAction>Delete on create</servermain:DuplicateTagAction>
						<servermain:Group/>
						<servermain:AllowSubGroups>true</servermain:AllowSubGroups>
					</servermain:AutoTagGeneration>
					% endif
					% if device.protocol == 'iec60870':
					<servermain:TimeSync>
						<servermain:TimeZone>UTC</servermain:TimeZone>
						<servermain:UsingDST>false</servermain:UsingDST>
						<servermain:TimeSyncMethod>0</servermain:TimeSyncMethod>

					% endif
					% if device.protocol == 'dnp3' or device.protocol == 'dnp3-serial':
					<servermain:CustomDeviceProperties  xmlns:${driver}="http://www.kepware.com/schemas/${driver}">
						<${driver}:DeviceCommunications>
							<${driver}:MasterAddress>1</${driver}:MasterAddress>
							<${driver}:SlaveAddress>10</${driver}:SlaveAddress>
							<${driver}:RequestTimeoutMilliseconds>30000</${driver}:RequestTimeoutMilliseconds>
							<${driver}:MaxTimeouts>1</${driver}:MaxTimeouts>
                                                        % if device.protocol == 'dnp3':
							<${driver}:KeepAliveIntervalSeconds>0</${driver}:KeepAliveIntervalSeconds>
                                                        % endif
							<${driver}:TimeBaseUsingUTC>true</${driver}:TimeBaseUsingUTC>
							<${driver}:TimeBaseTimeZone>UTC</${driver}:TimeBaseTimeZone>
							<${driver}:TimeBaseUsingDST>false</${driver}:TimeBaseUsingDST>
                                                        % if device.protocol == 'dnp3':
							<${driver}:TimeSynchronizationStyle>TIMESYNCSTYLE_LAN</${driver}:TimeSynchronizationStyle>
                                                        % else:
							<${driver}:AllowTimeSyncRequests>true</${driver}:AllowTimeSyncRequests>
							<${driver}:TimeSynchronizationStyle>TIMESYNCSTYLE_SERIAL</${driver}:TimeSynchronizationStyle>
                                                        % endif
							<${driver}:UseDelayMeasureInTimeSync>false</${driver}:UseDelayMeasureInTimeSync>
						</${driver}:DeviceCommunications>
						<${driver}:ClassPolling>
							<${driver}:EventClass1PollIntervalSeconds>5</${driver}:EventClass1PollIntervalSeconds>
							<${driver}:EventClass2PollIntervalSeconds>5</${driver}:EventClass2PollIntervalSeconds>
							<${driver}:EventClass3PollIntervalSeconds>5</${driver}:EventClass3PollIntervalSeconds>
							<${driver}:IntegrityPollIntervalSeconds>3600</${driver}:IntegrityPollIntervalSeconds>
							<${driver}:IssueIntegrityPollOnRestart>true</${driver}:IssueIntegrityPollOnRestart>
							<${driver}:IssueIntegrityPollOnSlaveOnline>false</${driver}:IssueIntegrityPollOnSlaveOnline>
							<${driver}:IssueIntegrityPollOnBufferOverflow>false</${driver}:IssueIntegrityPollOnBufferOverflow>
						</${driver}:ClassPolling>
						<${driver}:Unsolicited>
							<${driver}:UnsolicitedModeClass1>UNSOLICITEDMODE_AUTOMATIC</${driver}:UnsolicitedModeClass1>
							<${driver}:UnsolicitedModeClass2>UNSOLICITEDMODE_AUTOMATIC</${driver}:UnsolicitedModeClass2>
							<${driver}:UnsolicitedModeClass3>UNSOLICITEDMODE_AUTOMATIC</${driver}:UnsolicitedModeClass3>
							<${driver}:DisableUnsolicitedDuringStartup>false</${driver}:DisableUnsolicitedDuringStartup>
						</${driver}:Unsolicited>
						<${driver}:EventPlayback>
							<${driver}:EnableEventBuffer>false</${driver}:EnableEventBuffer>
							<${driver}:MaxEventsPerPoint>100</${driver}:MaxEventsPerPoint>
							<${driver}:EventBufferPlaybackRateMilliseconds>2000</${driver}:EventBufferPlaybackRateMilliseconds>
						</${driver}:EventPlayback>
						<${driver}:Advanced>
							<${driver}:OperateMode>OPERATEMODE_DIRECT</${driver}:OperateMode>
							<${driver}:EnableFeedbackPollAfterWrite>true</${driver}:EnableFeedbackPollAfterWrite>
							<${driver}:ConvertUTCTimestampToLocalTime>false</${driver}:ConvertUTCTimestampToLocalTime>
							<${driver}:IgnoreRemoteForceFlag>false</${driver}:IgnoreRemoteForceFlag>
							<${driver}:IgnoreLocalForceFlag>false</${driver}:IgnoreLocalForceFlag>
							<${driver}:ExchangeDataSetsOnRestart>false</${driver}:ExchangeDataSetsOnRestart>
							<${driver}:EnableDeviceRestartIINInfoLogging>false</${driver}:EnableDeviceRestartIINInfoLogging>
							<${driver}:EnableNeedTimeIINInfoLogging>false</${driver}:EnableNeedTimeIINInfoLogging>
						</${driver}:Advanced>
						<${driver}:TagImport>
							<${driver}:AutoGenerateDeviceAttributes>false</${driver}:AutoGenerateDeviceAttributes>
							<${driver}:AutoGenerateUserDefinedAttributes>false</${driver}:AutoGenerateUserDefinedAttributes>
							<${driver}:AutoGenerateDataSets>false</${driver}:AutoGenerateDataSets>
							<${driver}:GenerateExplicitDataSetTags>false</${driver}:GenerateExplicitDataSetTags>
							<${driver}:GenerateValueDataSetTags>true</${driver}:GenerateValueDataSetTags>
						</${driver}:TagImport>
						<${driver}:Authentication>
							<${driver}:EnableAuthentication>false</${driver}:EnableAuthentication>
							<${driver}:EnableAggressiveModeSupport>true</${driver}:EnableAggressiveModeSupport>
							<${driver}:MaxAuthErrorCount>2</${driver}:MaxAuthErrorCount>
							<${driver}:MaxAuthKeyChangeCount>1000</${driver}:MaxAuthKeyChangeCount>
							<${driver}:AuthKeyChangeIntervalSeconds>900</${driver}:AuthKeyChangeIntervalSeconds>
							<${driver}:AuthReplyTimeoutMS>2000</${driver}:AuthReplyTimeoutMS>
							<${driver}:AuthCurrentUserNumber>1</${driver}:AuthCurrentUserNumber>
							<${driver}:UpdateKeyList>
								<${driver}:UpdateKeyPair>
									<${driver}:UserNumber>1</${driver}:UserNumber>
									<${driver}:Encrypted>true</${driver}:Encrypted>
									<${driver}:UpdateKey>f4204e26b7f59cf998f8be2394490886b04053bb522ce1dc089da41870488b7568d3807688d935342729fa300610f5df37e36a021e90bd90368e6d273eaafde6a1f7</${driver}:UpdateKey>
								</${driver}:UpdateKeyPair>
								% for i in range(9):
								<${driver}:UpdateKeyPair>
									<${driver}:UserNumber>0</${driver}:UserNumber>
									<${driver}:Encrypted>true</${driver}:Encrypted>
									<${driver}:UpdateKey>f4204e26b7f59cf998f8be2394490886b04053bb522ce1dc089da41870488b7568d3807688d935342729fa300610f5df37e36a021e90bd90368e6d273eaafde6a1f7</${driver}:UpdateKey>
								</${driver}:UpdateKeyPair>
								% endfor
							</${driver}:UpdateKeyList>
						</${driver}:Authentication>
						<${driver}:FileControl>
							<${driver}:EnableInformationalLogging>false</${driver}:EnableInformationalLogging>
							<${driver}:EnableFileNameWrites>false</${driver}:EnableFileNameWrites>
							<${driver}:ActivateConfigObjects/>
							<${driver}:FileIndexCount>10</${driver}:FileIndexCount>
							% for i in range(10):
							<${driver}:FileIndex>
								<${driver}:Index>${i}</${driver}:Index>
								<${driver}:LocalFilePath/>
								<${driver}:LocalFileName/>
								<${driver}:LocalFileOpenMode>LOCALFILEOPENMODE_OVERWRITE</${driver}:LocalFileOpenMode>
								<${driver}:RemoteFilePath/>
								<${driver}:RemoteFileName/>
								<${driver}:FileAuthUsername/>
								<${driver}:Encrypted>true</${driver}:Encrypted>
								<${driver}:FileAuthPassword/>
								<${driver}:MaxFileSizeKB>1000</${driver}:MaxFileSizeKB>
							</${driver}:FileIndex>
							% endfor
						</${driver}:FileControl>
					% elif device.protocol == 'modbus' or device.protocol == 'modbus-serial':
					<servermain:CustomDeviceProperties xmlns:modbus_ethernet="http://www.kepware.com/schemas/modbus_ethernet">
						<modbus_ethernet:Communications>
							<modbus_ethernet:Port>502</modbus_ethernet:Port>
							<modbus_ethernet:Protocol>TCP/IP</modbus_ethernet:Protocol>
							<modbus_ethernet:CloseTCPSocketOnTimeout>true</modbus_ethernet:CloseTCPSocketOnTimeout>
						</modbus_ethernet:Communications>
						<modbus_ethernet:Settings>
							<modbus_ethernet:ZeroBasedAddressing>true</modbus_ethernet:ZeroBasedAddressing>
							<modbus_ethernet:ZeroBasedBitAddressingRegisters>true</modbus_ethernet:ZeroBasedBitAddressingRegisters>
							<modbus_ethernet:HoldingRegisterBitMaskWrites>true</modbus_ethernet:HoldingRegisterBitMaskWrites>
							<modbus_ethernet:ModbusFunction06SingleRegisterWrites>true</modbus_ethernet:ModbusFunction06SingleRegisterWrites>
							<modbus_ethernet:ModbusFunction05SingleCoilWrites>true</modbus_ethernet:ModbusFunction05SingleCoilWrites>
							<modbus_ethernet:DefaultModbusByteOrder>true</modbus_ethernet:DefaultModbusByteOrder>
							<modbus_ethernet:FirstWordLow32BitDataTypes>true</modbus_ethernet:FirstWordLow32BitDataTypes>
							<modbus_ethernet:FirstDWordLow64BitDataTypes>true</modbus_ethernet:FirstDWordLow64BitDataTypes>
							<modbus_ethernet:ModiconBitOrdering>true</modbus_ethernet:ModiconBitOrdering>
						</modbus_ethernet:Settings>
						<modbus_ethernet:BlockSizes>
							<modbus_ethernet:Output>32</modbus_ethernet:Output>
							<modbus_ethernet:Input>32</modbus_ethernet:Input>
							<modbus_ethernet:Internal>32</modbus_ethernet:Internal>
							<modbus_ethernet:Holding>32</modbus_ethernet:Holding>
							<modbus_ethernet:PerformBlockStringRead>false</modbus_ethernet:PerformBlockStringRead>
						</modbus_ethernet:BlockSizes>
						<modbus_ethernet:VariableImportSettings>
							<modbus_ethernet:VariableImportFile>*.txt</modbus_ethernet:VariableImportFile>
							<modbus_ethernet:DisplayDescriptions>true</modbus_ethernet:DisplayDescriptions>
						</modbus_ethernet:VariableImportSettings>
						<modbus_ethernet:DataBadUntilWrite>false</modbus_ethernet:DataBadUntilWrite>
						<modbus_ethernet:Timeout>0</modbus_ethernet:Timeout>
						<modbus_ethernet:ErrorHandling>
							<modbus_ethernet:DeactivateOnIllegalAddressException>true</modbus_ethernet:DeactivateOnIllegalAddressException>
						</modbus_ethernet:ErrorHandling>
					% elif device.protocol == 'iec60870':
					<servermain:CustomDeviceProperties xmlns:iec_60870_5_104_master="http://www.kepware.com/schemas/iec_60870_5_104_master">
						<iec_60870_5_104_master:DeviceCommunications>
							<iec_60870_5_104_master:CommonAddress>1</iec_60870_5_104_master:CommonAddress>
							<iec_60870_5_104_master:TimeSyncInitOption>End of Initialization</iec_60870_5_104_master:TimeSyncInitOption>
							<iec_60870_5_104_master:GiInitOption>End of Initialization</iec_60870_5_104_master:GiInitOption>
							<iec_60870_5_104_master:CiInitOption>End of Initialization</iec_60870_5_104_master:CiInitOption>
							<iec_60870_5_104_master:PeriodicGiIntervalMin>0</iec_60870_5_104_master:PeriodicGiIntervalMin>
							<iec_60870_5_104_master:PeriodicCiIntervalMin>0</iec_60870_5_104_master:PeriodicCiIntervalMin>
							<iec_60870_5_104_master:EventPlayback>true</iec_60870_5_104_master:EventPlayback>
							<iec_60870_5_104_master:PlaybackBuffer>100</iec_60870_5_104_master:PlaybackBuffer>
							<iec_60870_5_104_master:PlaybackRate>2000</iec_60870_5_104_master:PlaybackRate>
							<iec_60870_5_104_master:PolledReads>true</iec_60870_5_104_master:PolledReads>
							<iec_60870_5_104_master:TestProcedure>false</iec_60870_5_104_master:TestProcedure>
							<iec_60870_5_104_master:TestProcedurePeriod>15</iec_60870_5_104_master:TestProcedurePeriod>
							<iec_60870_5_104_master:RequestTimeout>10000</iec_60870_5_104_master:RequestTimeout>
							<iec_60870_5_104_master:IntRequestTimeout>60000</iec_60870_5_104_master:IntRequestTimeout>
							<iec_60870_5_104_master:AttemptCount>3</iec_60870_5_104_master:AttemptCount>
							<iec_60870_5_104_master:IntAttemptCount>3</iec_60870_5_104_master:IntAttemptCount>
						</iec_60870_5_104_master:DeviceCommunications>
					% elif device.protocol == 'bacnet':
                    <servermain:CustomDeviceProperties xmlns:bacnet="http://www.kepware.com/schemas/bacnet">
                        <bacnet:APDU>
                            <bacnet:MaximumSegmentsAccepted>Unspecified</bacnet:MaximumSegmentsAccepted>
                            <bacnet:MaximumWindowSize>1</bacnet:MaximumWindowSize>
                            <bacnet:MaximumAPDULength>1476 (fits ISO 8802-3 frame)</bacnet:MaximumAPDULength>
                            <bacnet:NumberItemsPerRequest>16</bacnet:NumberItemsPerRequest>
                        </bacnet:APDU>
                        <bacnet:Command>
                            <bacnet:Priority>8</bacnet:Priority>
                        </bacnet:Command>
                        <bacnet:COV>
                            <bacnet:Mode>Do not use COV</bacnet:Mode>
                            <bacnet:SPIDZero>false</bacnet:SPIDZero>
                            <bacnet:CancelOnShutdown>true</bacnet:CancelOnShutdown>
                            <bacnet:AwaitACKOnShutdown>false</bacnet:AwaitACKOnShutdown>
                            <bacnet:ResubscriptionInterval>3600</bacnet:ResubscriptionInterval>
                        </bacnet:COV>
                        <bacnet:TagImportSettings>
                            <bacnet:ImportMethod>Device</bacnet:ImportMethod>
                            <bacnet:ImportFile>*.csv</bacnet:ImportFile>
                            <bacnet:AnalogInputs>true</bacnet:AnalogInputs>
                            <bacnet:AnalogOutputs>true</bacnet:AnalogOutputs>
                            <bacnet:AnalogValue>false</bacnet:AnalogValue>
                            <bacnet:BinaryInputs>true</bacnet:BinaryInputs>
                            <bacnet:BinaryOutputs>true</bacnet:BinaryOutputs>
                            <bacnet:BinaryValue>false</bacnet:BinaryValue>
                            <bacnet:Calendar>false</bacnet:Calendar>
                            <bacnet:Command_1>false</bacnet:Command_1>
                            <bacnet:Device>false</bacnet:Device>
                            <bacnet:EventEnrollment>false</bacnet:EventEnrollment>
                            <bacnet:File>false</bacnet:File>
                            <bacnet:Group>false</bacnet:Group>
                            <bacnet:Loop>false</bacnet:Loop>
                            <bacnet:MultiStateInput>false</bacnet:MultiStateInput>
                            <bacnet:MultiStateOutput>false</bacnet:MultiStateOutput>
                            <bacnet:NotificationClass>false</bacnet:NotificationClass>
                            <bacnet:Program>false</bacnet:Program>
                            <bacnet:Schedule>false</bacnet:Schedule>
                            <bacnet:Averaging>false</bacnet:Averaging>
                            <bacnet:MultiStateValue>false</bacnet:MultiStateValue>
                            <bacnet:TrendLog>false</bacnet:TrendLog>
                            <bacnet:LifeSafetyPoint>false</bacnet:LifeSafetyPoint>
                            <bacnet:LifeSafetyZone>false</bacnet:LifeSafetyZone>
                            <bacnet:FilterOptionalProperties>true</bacnet:FilterOptionalProperties>
                            <bacnet:CreateAllAsReadWrite>true</bacnet:CreateAllAsReadWrite>
                            <bacnet:UseObjectNames>true</bacnet:UseObjectNames>
                        </bacnet:TagImportSettings>
                        <bacnet:Discovery>
                            <bacnet:UseWhoIsIAm>false</bacnet:UseWhoIsIAm>
                            <bacnet:Scope>Local</bacnet:Scope>
                            <bacnet:IPAddress>255.255.255.255</bacnet:IPAddress>
                            <bacnet:ManualIP>${device.fd_ip}</bacnet:ManualIP>
                            <bacnet:RemoteDataLink>0</bacnet:RemoteDataLink>
                            <bacnet:BACnetMAC/>
                        </bacnet:Discovery>
					% endif
					</servermain:CustomDeviceProperties>
					<servermain:TagList>
					% for tag in device.tags:
                                            % if tag.protocol == device.protocol:
${opc_tag.create(tag)}\
                                            % endif
					% endfor
					</servermain:TagList>
				</servermain:Device>
</%def>\
