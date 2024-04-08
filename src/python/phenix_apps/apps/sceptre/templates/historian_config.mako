:(Mode)update${'\r'}
:(IODriver)ComputerName	AltComputerName	StoreForwardMode	StoreForwardPath	MinMBThreshold	Enabled	StoreForwardDuration	AutonomousStartupTimeout	BufferCount	FileChunkSize	ForwardingDelay	ConnectionTimeout${'\r'}
$local		Off		16	Yes	180	60	128	65536	0	60${'\r'}
:(IOServer)ComputerName	ApplicationName	AltComputerName	IDASComputerName	ProtocolType${'\r'}
% if hist_config.opc_ip != "":
${hist_config.opc_ip}	server_runtime		$local	SuiteLink${'\r'}
% endif
:(Topic)Name	ApplicationName	ComputerName	TimeOut	LateData	IdleDuration	ProcessingInterval${'\r'}
% for topic in hist_config.tags.keys():
${topic}	server_runtime	${hist_config.opc_ip}	60000	No	60	120${'\r'}
% endfor
:(SystemParameter)Name	Value	Description${'\r'}
AIAutoResize	1	Active image auto resize option. (1=Enabled - 0=Disabled)${'\r'}
AIResizeInterval	5	Active image resize interval (minutes)${'\r'}
AllowOriginals	0	Allow/Disallow manual original data insert for IO Server tags${'\r'}
AnalogSummaryTypeAbbreviation		Type abbreviation to be used in generating Analog Summary tags${'\r'}
AutoStart	0	When set to 1 the system starts automatically${'\r'}
DataImportPath	C:\Historian\Data\DataImport	File path for CSV files containing old data${'\r'}
EventStorageDuration	168	Max Event History Storage Duration (hours)${'\r'}
HeadroomAnalog2	100	Number of 2-byte delta analog tags to pre-allocate${'\r'}
HeadroomAnalog4	100	Number of 4-byte delta analog tags to pre-allocate${'\r'}
HeadroomAnalog8	0	Number of 8-byte delta analog tags to pre-allocate${'\r'}
HeadroomDiscrete	100	Number of discrete tags to pre-allocate${'\r'}
HeadroomString	20	Number of string tags to pre-allocate${'\r'}
HistoryCacheSize	0	Allocated memory for history block information (MB)${'\r'}
HistoryDaysAlwaysCached	0	Duration for which history block information is always loaded (days)${'\r'}
HoursPerBlock	24	History block duration (hours)${'\r'}
InterpolationTypeInteger	0	Interpolation type for integers (0=Stair, 1=Linear)${'\r'}
InterpolationTypeReal	1	Interpolation type for reals (0=Stair, 1=Linear)${'\r'}
LateDataPathThreshold	125	Control SF for Late data${'\r'}
ManualDataPathThreshold	125	Control SF for Old data${'\r'}
ModLogTrackingStatus	0	Configures modification logging${'\r'}
OldDataSynchronizationDelay	60	Time period in seconds describing how often the changes in Tier-1 old data (inserts/updates/Store Forward Data) must be sent to the Tier-2 server${'\r'}
QualityRule	0	Use Good and Uncertain points (0), or Good points only (1)${'\r'}
RealTimeWindow	60	Maximum delay, relative to current time, for which data will be considered real-time, when processing swinging door and late data (seconds)${'\r'}
ReplicationConcurrentOperations	50	Limits the total number of retrieval client objects performing calculations in a retrieval based calculations for a time cycle${'\r'}
ReplicationDefaultPrefix	${hist_name.upper()}	Used for prefixing when configuring the Tier-2 tags${'\r'}
ReplicationTcpPort	32568	Replication TCP Port Address${'\r'}
RevisionLogPath	C:\Historian\Data\Logs\Revision	File path of the write-ahead log for tier-2 insert/update transactions${'\r'}
SimpleReplicationNamingScheme	<ReplicationDefaultPrefix>.<SourceTagName>	Naming scheme used for configuring simple replication tags${'\r'}
StateSummaryTypeAbbreviation	S	Type abbreviation to be used in generating State Summary tags${'\r'}
SuiteLinkTimeSyncInterval	60	Number of minutes between SuiteLink time synchronizations (0 = no time sync)${'\r'}
SummaryCalculationTimeout	15	Maximum expected delay in minutes for calculating summary data for replicated tags${'\r'}
SummaryReplicationNamingScheme	<ReplicationDefaultPrefix>.<SourceTagName>.<TypeAbbreviation><GroupAbbreviation>	Naming scheme for configuring summary replication tags${'\r'}
SummaryStorageDuration	336	Max Summary History Storage Duration (hours)${'\r'}
SysPerfTags	1	System Performance Tags acquisition (0 = Off, 1 = On)${'\r'}
TimeStampRule	1	Time stamp at start (0), or end (1) of time interval${'\r'}
TimeSyncIODrivers	1	When set to 1, this Historian will send time synchronization commands to all its remote IDASs${'\r'}
TimeSyncMaster		Server Time Synchronization source. (Must contain the machine name from which this Historian should time sync.)${'\r'}
:(StorageLocation)StorageType	Path	MaxMBSize	MinMBThreshold	MaxAgeThreshold${'\r'}
1	C:\Historian\Data\Circular	0	125	0${'\r'}
2	rr:\OverflowData	0	125	0${'\r'}
3	C:\Historian\Data\Buffer	0	125	0${'\r'}
4	C:\Historian\Data\Permanent	0	125	0${'\r'}
:(EngineeringUnit)Unit	DefaultTagRate	IntegralDivisor${'\r'}
%%	10000	1${'\r'}
None	10000	1${'\r'}
Second	10000	1${'\r'}
Minute	10000	1${'\r'}
Hour	10000	1${'\r'}
Day	10000	1${'\r'}
Month	10000	1${'\r'}
Year	10000	1${'\r'}
Mb	10000	1${'\r'}
Bytes	10000	1${'\r'}
ft	10000	1${'\r'}
in	10000	1${'\r'}
cm	10000	1${'\r'}
m	10000	1${'\r'}
ft/s	10000	1${'\r'}
ft/min	10000	60${'\r'}
m/s	10000	1${'\r'}
m/min	10000	60${'\r'}
gal	10000	1${'\r'}
m3	10000	1${'\r'}
l	10000	1${'\r'}
hl	10000	1${'\r'}
gal/min	10000	60${'\r'}
gal/h	10000	3600${'\r'}
gal/d	10000	86400${'\r'}
m3/min	10000	60${'\r'}
l/s	10000	1${'\r'}
l/min	10000	60${'\r'}
hl/min	10000	60${'\r'}
l/h	10000	3600${'\r'}
hl/h	10000	3600${'\r'}
l/d	10000	86400${'\r'}
hl/d	10000	86400${'\r'}
kg	10000	1${'\r'}
t	10000	1${'\r'}
kg/min	10000	60${'\r'}
t/min	10000	60${'\r'}
t/h	10000	3600${'\r'}
t/d	10000	86400${'\r'}
lb	10000	1${'\r'}
lb/s	10000	1${'\r'}
lb/min	10000	60${'\r'}
psi	10000	1${'\r'}
Pa	10000	1${'\r'}
hPa	10000	1${'\r'}
kW	10000	1${'\r'}
MW	10000	1${'\r'}
A	10000	1${'\r'}
V	10000	1${'\r'}
kV	10000	1${'\r'}
## Had to remove the unicode degree symbol from the below 2 lines for the mako template to be created
F	10000	1${'\r'}
C	10000	1${'\r'}
K	10000	1${'\r'}
units	10000	1${'\r'}
rpm	10000	60${'\r'}
units/s	10000	1${'\r'}
units/min	10000	60${'\r'}
units/h	10000	3600${'\r'}
units/d	10000	86400${'\r'}
:(Message)Message0	Message1${'\r'}
OFF	ON${'\r'}
:(AnalogTag)TagName	Description	IOServerComputerName	IOServerAppName	TopicName	ItemName	AcquisitionType	StorageType	AcquisitionRate	StorageRate	TimeDeadband	SamplesInAI	AIMode	EngUnits	MinEU	MaxEU	MinRaw	MaxRaw	Scaling	RawType	IntegerSize	Sign	ValueDeadband	InitialValue	CurrentEditor	RateDeadband	InterpolationType	RolloverValue	ServerTimeStamp	DeadbandType${'\r'}
% for topic in hist_config.tags:
    % for tag in hist_config.tags[topic]:
${tag}	${tag}	${hist_config.opc_ip}	server_runtime	${topic}	${tag}	IOServer	Delta	0	10000	0	0	All	None	0	100	0	100	None	MSFloat	0		0	0	0	0	System Default	0	No	TimeValue${'\r'}
    % endfor
% endfor
:(DiscreteTag)TagName	Description	IOServerComputerName	IOServerAppName	TopicName	ItemName	AcquisitionType	StorageType	AcquisitionRate	TimeDeadband	SamplesInAI	AIMode	Message0	Message1	InitialValue	CurrentEditor	ServerTimeStamp${'\r'}
:(StringTag)TagName	Description	IOServerComputerName	IOServerAppName	TopicName	ItemName	AcquisitionType	StorageType	AcquisitionRate	TimeDeadband	SamplesInAI	MaxLength	Format	InitialValue	CurrentEditor	ServerTimeStamp${'\r'}
:(EventTag)TagName	Description	DetectorType	ActionType	ScanRate	TimeDeadband	Logged	PostDetectorDelay	EdgeDetection	Priority	DetectorString	ActionString	Frequency	Periodicity	StartDateTime	RunTimeDay	RunTimeHour	RunTimeMin	Status${'\r'}
SysStatusEvent	Status Tag snapshot event	Analog Specific Value	Snapshot	60000	0	Yes	0	Leading	Normal	exec dbo.aaEventDetection N'SysTimeMin', '=', 0, N'Leading', 0, '@StartTime', '@EndTime'	exec dbo.aaEventSnapshotInsert @EventLogKey, '@EventTime', '@EventTagName'							Yes${'\r'}
:(SnapshotTag)TagName	EventTag${'\r'}
SysSpaceMain	SysStatusEvent${'\r'}
SysPerfCPUTotal	SysStatusEvent${'\r'}
:(SummaryOperation)EventTagName	CalcType	Duration	Resolution	TimeStamp	Description${'\r'}
:(SummaryTag)TagName	EventTagName	CalcType	Duration	Resolution	TimeStamp	LowerLimit	UpperLimit	Description${'\r'}
:(ReplicationSchedule)ReplicationScheduleName	ReplicationScheduleTypeName	ReplicationScheduleAbbreviation	CreateGroup	Period	Unit	TimesOfDay${'\r'}
1 Minute	Interval	1M	True	1	Minute	${'\r'}
5 Minutes	Interval	5M	True	5	Minute	${'\r'}
15 Minutes	Interval	15M	True	15	Minute	${'\r'}
30 Minutes	Interval	30M	True	30	Minute	${'\r'}
1 Hour	Interval	1H	True	1	Hour	${'\r'}
1 Day	Interval	1D	True	1	Day	${'\r'}
:(ReplicationServer)ReplicationServerName	Description	SFPath	SFFreeSpace	AuthenticateWithAAUser	UserName	TCPPort	SummaryReplicationNamingScheme	SimpleReplicationNamingScheme	BufferCount	Bandwidth	MinSFDuration${'\r'}
Local Replication		C:\Historian\StoreForward\LocalReplication	125	True		32568	<SourceTagName>.<TypeAbbreviation><GroupAbbreviation>		128	-1	180${'\r'}
% for counter, replication_ip in enumerate(hist_config.replication_ips):
${replication_ip}	HistorianBackup${counter}	C:\Historian\StoreForward\${replication_ip}	125	True		32568			128	-1	180${'\r'}
% endfor
:(ReplicationGroup)ReplicationGroupName	ReplicationServerName	ReplicationTypeName	ReplicationScheduleName	SummaryReplicationNamingScheme	GroupAbbreviation${'\r'}
1 Minute	Local Replication	Analog Summary Replication	1 Minute		${'\r'}
1 Minute	Local Replication	State Summary Replication	1 Minute		${'\r'}
5 Minutes	Local Replication	Analog Summary Replication	5 Minutes		${'\r'}
5 Minutes	Local Replication	State Summary Replication	5 Minutes		${'\r'}
15 Minutes	Local Replication	Analog Summary Replication	15 Minutes		${'\r'}
15 Minutes	Local Replication	State Summary Replication	15 Minutes		${'\r'}
30 Minutes	Local Replication	Analog Summary Replication	30 Minutes		${'\r'}
30 Minutes	Local Replication	State Summary Replication	30 Minutes		${'\r'}
1 Hour	Local Replication	Analog Summary Replication	1 Hour		${'\r'}
1 Hour	Local Replication	State Summary Replication	1 Hour		${'\r'}
1 Day	Local Replication	Analog Summary Replication	1 Day		${'\r'}
1 Day	Local Replication	State Summary Replication	1 Day		${'\r'}
% for replication_ip in hist_config.replication_ips:
1 Minute	${replication_ip}	Analog Summary Replication	1 Minute		${'\r'}
1 Minute	${replication_ip}	State Summary Replication	1 Minute		${'\r'}
5 Minutes	${replication_ip}	Analog Summary Replication	5 Minutes		${'\r'}
5 Minutes	${replication_ip}	State Summary Replication	5 Minutes		${'\r'}
15 Minutes	${replication_ip}	Analog Summary Replication	15 Minutes		${'\r'}
15 Minutes	${replication_ip}	State Summary Replication	15 Minutes		${'\r'}
30 Minutes	${replication_ip}	Analog Summary Replication	30 Minutes		${'\r'}
30 Minutes	${replication_ip}	State Summary Replication	30 Minutes		${'\r'}
1 Hour	${replication_ip}	Analog Summary Replication	1 Hour		${'\r'}
1 Hour	${replication_ip}	State Summary Replication	1 Hour		${'\r'}
1 Day	${replication_ip}	Analog Summary Replication	1 Day		${'\r'}
1 Day	${replication_ip}	State Summary Replication	1 Day		${'\r'}
% endfor
:(ReplicationTagEntity)DestinationTagName	SourceTagName	ReplicationServerName	ReplicationGroupName	ReplicationTypeName	MaximumStates	CurrentEditor${'\r'}
% for replication_ip in hist_config.replication_ips:
    % for topic in hist_config.tags:
        % for tag in hist_config.tags[topic]:
HISTORIAN.${tag}	${tag}	${replication_ip}		Simple Replication	0	0${'\r'}
        % endfor
    % endfor
% endfor
${'\r'}
