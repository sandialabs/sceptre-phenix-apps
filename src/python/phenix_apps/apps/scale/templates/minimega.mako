namespace ${config['NAMESPACE']}
ns queueing ${str(config['QUEUEING']).lower()}

clear vm config
vm config vcpus ${config['VCPU']}
vm config memory ${config['MEMORY']}
vm config net ${config['NET_STR']}
vm config filesystem ${'tar:' if config['FILESYSTEM'].endswith('.tgz') else ''}${config['FILESYSTEM']}
vm config init /init

% for i in range(config.get('START_INDEX', 0), config['COUNT'] + config.get('START_INDEX', 0)):
    % for src, dst in config.get('VOLUMES', []):
        <%
            vol_src = src.format(i=i, HOSTNAME=config['HOSTNAME'])
        %>
vm config volume ${dst} ${vol_src}
    % endfor
    <%
        name_tmpl = config.get('CONTAINER_NAME_TEMPLATE', '{}')
        name = name_tmpl.format(i)
    %>
vm launch container ${name}
% endfor

% if config['QUEUEING']:
vm launch
% endif

vm start all

% for i in range(config.get('START_INDEX', 0), config['COUNT'] + config.get('START_INDEX', 0)):
    <%
        name_tmpl = config.get('CONTAINER_NAME_TEMPLATE', '{}')
        name = name_tmpl.format(i)
    %>
cc filter name=${name}
    % for idx, net in enumerate(config['NETS']):
cc exec ip addr add ${str(net['addr']+i)}/${net['prefix']} dev veth${idx}
    % endfor
    % if config['NETS'] and config['GATEWAY']:
cc exec ip route add default via ${config['GATEWAY']}
    % endif
% endfor
