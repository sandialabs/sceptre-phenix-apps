## wind_turbine.mako
namespace ${config['NAMESPACE']}
ns queueing ${str(config['QUEUEING']).lower()}

clear vm config
vm config vcpus ${config['VCPU']}
vm config memory ${config['MEMORY']}
vm config filesystem ${'tar:' if config['FILESYSTEM'].endswith('.tgz') else ''}${config['FILESYSTEM']}
vm config init /init

% for src, dst in config.get('SHARED_VOLUMES', []):
vm config volume ${dst} ${src}
% endfor

% for i in range(config['START_INDEX'], config['COUNT'] + config['START_INDEX']):
<%
  # The index into CONTAINER_NETWORKS/HOSTNAMES is 0-based from the start of this node's containers
  c_idx = i - config['START_INDEX']
  c_name = config['CONTAINER_HOSTNAMES'][c_idx]
  c_net = config['CONTAINER_NETWORKS'][c_idx]
  c_ips = config['CONTAINER_IPS'][c_idx]
  c_gw = config['CONTAINER_GATEWAYS'][c_idx]
%>
vm config hostname ${c_name}
vm config net ${c_net}
% for src, dst in config.get('PER_CONTAINER_VOLUMES', []):
<%
  # The volume source path on the host VM uses the container's index on that VM
  vol_src = src.format(i=i, HOSTNAME=config['HOSTNAME'])
%>
vm config volume ${dst} ${vol_src}
% endfor
vm launch container ${c_name}
% endfor

% if config['QUEUEING']:
vm launch
% endif

vm start all

% for i in range(config['START_INDEX'], config['COUNT'] + config['START_INDEX']):
<%
  c_idx = i - config['START_INDEX']
  c_name = config['CONTAINER_HOSTNAMES'][c_idx]
  c_ips = config['CONTAINER_IPS'][c_idx]
  c_gw = config['CONTAINER_GATEWAYS'][c_idx]
%>
cc filter name=${c_name}
% for idx, ip_addr in enumerate(c_ips):
cc exec ip addr add ${ip_addr} dev veth${idx}
% endfor
% if c_gw:
cc exec ip route add default via ${c_gw}
% endif
% endfor