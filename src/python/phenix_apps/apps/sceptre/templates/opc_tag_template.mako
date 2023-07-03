<%def name="create(register)">\
<%
REG_TAG = {}
REG_TAG['analog-input']     = {'base_addr': '30.5.',   'datatype': 'Float',   'access': 'Read Only'}
REG_TAG['analog-output']    = {'base_addr': '40.3.',   'datatype': 'Float',   'access': 'Read/Write'}
REG_TAG['binary-input']     = {'base_addr': '1.1.',    'datatype': 'Boolean', 'access': 'Read Only'}
REG_TAG['binary-output']    = {'base_addr': '10.0.',   'datatype': 'Boolean', 'access': 'Read/Write'}
REG_TAG['input-register']   = {'base_addr': 300001,    'datatype': 'Word',    'access': 'Read Only'}
REG_TAG['holding-register'] = {'base_addr': 400001,    'datatype': 'Word',    'access': 'Read/Write'}
REG_TAG['discrete-input']   = {'base_addr': 100001,    'datatype': 'Boolean', 'access': 'Read Only'}
REG_TAG['coil']             = {'base_addr': 1,         'datatype': 'Boolean', 'access': 'Read/Write'}
REG_TAG['float-point']      = {'base_addr': 'M_ME_FV', 'datatype': 'Float',   'access': 'Read Only'}
REG_TAG['single-point']     = {'base_addr': 'M_SP',    'datatype': 'Boolean', 'access': 'Read Only'}
PROTO_REGS = {
    'dnp3':          ['analog-input', 'analog-output', 'binary-input', 'binary-output'],
    'dnp3-serial':   ['analog-input', 'analog-output', 'binary-input', 'binary-output'],
    'modbus':        ['input-register', 'holding-register', 'discrete-input', 'coil'],
    'modbus-serial': ['input-register', 'holding-register', 'discrete-input', 'coil'],
    'iec60870':      ['float-point', 'single-point']
}

name = f'{register.devname}_{register.regtype}_{register.field}'.replace('-', '_')
datatype = REG_TAG[register.regtype]['datatype']
access = REG_TAG[register.regtype]['access']
if register.regtype in PROTO_REGS['dnp3'] or register.regtype in PROTO_REGS['dnp3-serial']:
    addr = f"{REG_TAG[register.regtype]['base_addr']}{str(register.addr)}.Value"
    if register.regtype == 'binary-output':
        addr2 = f"{REG_TAG[register.regtype]['base_addr']}{str(register.addr)}.Operate.Set"
        addr3 = f"{REG_TAG[register.regtype]['base_addr']}{str(register.addr)}.Operate.OpType"
if register.regtype in PROTO_REGS['modbus'] or register.regtype in PROTO_REGS['modbus-serial']:
    addr = REG_TAG[register.regtype]['base_addr'] + register.addr
    addr = str(addr).zfill(6)
if register.regtype in PROTO_REGS['iec60870']:
    name = name + '_read'
    addr = f"{REG_TAG[register.regtype]['base_addr']}.{register.addr}.CURRENTVALUE"
    if register.regtype == 'float-point':
        addr2 = f'C_SE_FV.{register.addr}.DIRECTVALUE'
    else:
        addr2 = f'C_SC.{register.addr}.DIRECTVALUE'
if register.protocol == 'bacnet':
    addr = f"{register.regtype.title().replace('-','')}.{register.addr}.PresentValue"
%>\
						<servermain:Tag>
							<servermain:Name>${name}</servermain:Name>
							<servermain:Address>${addr}</servermain:Address>
							<servermain:DataType>${datatype}</servermain:DataType>
							<servermain:ReadWriteAccess>${access}</servermain:ReadWriteAccess>
							<servermain:RespectGUIDataType>true</servermain:RespectGUIDataType>
							% if register.regtype in ('float-point', 'single-point'):
							<servermain:ScanRateMilliseconds>5000</servermain:ScanRateMilliseconds>
							% endif
							% if register.regtype == 'holding-register' or register.regtype == 'input-register':
							<servermain:Scaling>
								<servermain:Type>Linear</servermain:Type>
								<servermain:RawLow>0.000000</servermain:RawLow>
								<servermain:RawHigh>65535</servermain:RawHigh>
								<servermain:ScaledDataType>Float</servermain:ScaledDataType>
								<servermain:ScaledLow>${register.range[0]}</servermain:ScaledLow>
								<servermain:ScaledHigh>${register.range[1]}</servermain:ScaledHigh>
								<servermain:ClampLow>true</servermain:ClampLow>
								<servermain:ClampHigh>true</servermain:ClampHigh>
								<servermain:Units/>
								<servermain:NegateValue>false</servermain:NegateValue>
							</servermain:Scaling>
							% endif
						</servermain:Tag>
						% if register.regtype in ('float-point', 'single-point'):
						<servermain:Tag>
							<servermain:Name>${name}_write</servermain:Name>
							<servermain:Address>${addr2}</servermain:Address>
							<servermain:DataType>${datatype}</servermain:DataType>
							<servermain:ReadWriteAccess>Read/Write</servermain:ReadWriteAccess>
							<servermain:RespectGUIDataType>true</servermain:RespectGUIDataType>
							<servermain:ScanRateMilliseconds>5000</servermain:ScanRateMilliseconds>
						</servermain:Tag>
						% endif
						% if register.regtype == 'binary-output':
                                                <servermain:Tag>
                                                        <servermain:Name>${name}_opset</servermain:Name>
                                                        <servermain:Address>${addr2}</servermain:Address>
                                                        <servermain:DataType>Boolean</servermain:DataType>
                                                        <servermain:ReadWriteAccess>Read/Write</servermain:ReadWriteAccess>
                                                        <servermain:RespectGUIDataType>true</servermain:RespectGUIDataType>
                                                </servermain:Tag>
                                                <servermain:Tag>
                                                        <servermain:Name>${name}_optype</servermain:Name>
                                                        <servermain:Address>${addr3}</servermain:Address>
                                                        <servermain:DataType>Byte</servermain:DataType>
                                                        <servermain:ReadWriteAccess>Read/Write</servermain:ReadWriteAccess>
                                                        <servermain:RespectGUIDataType>true</servermain:RespectGUIDataType>
                                                </servermain:Tag>
                                                % endif
</%def>\
