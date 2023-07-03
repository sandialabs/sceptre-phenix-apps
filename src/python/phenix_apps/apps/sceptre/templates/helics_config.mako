{

    "name": "${config['name']}",
    "broker_address": "${config['broker_address']}",
    "log_level": ${config['log_level']},
% if 'request_time' in config:
    "request_time": ${config['request_time']},
% endif
% if 'period' in config:
    "period": ${config['period']},
% endif
% if 'real_time' in config:
    "real_time": ${config['real_time']},
% endif
% if 'end_time' in config:
    "end_time": ${config['end_time']},
% endif
    "terminate_on_error": true,
% if any(x in config for x in ['subs', 'pubs', 'ends']):
    "only_update_on_change": true,
% else:
    "only_update_on_change": true
% endif
% if 'subs' in config:
    "subscriptions": [
    % for idx, elem in enumerate(config['subs']):
        <% [key, type_, *info] = elem.split(',', maxsplit=3) %>
        {
            "key": "${key}",
        % if info:
            "type": "${type_}",
            "info": "${''.join(info)}"
        % else:
            "type": "${type_}"
        % endif
        % if idx != len(config['subs']) - 1:
        },
        % else:
        }
        % endif
    % endfor
    % if any(x in config for x in ['pubs', 'ends']):
    ],
    % else:
    ]
    % endif
% endif
% if 'pubs' in config:
    "publications": [
    % for idx, elem in enumerate(config['pubs']):
        <% [key, type_] = elem.split(',') %>
        {
            "key": "${key}",
            "type": "${type_}"
        % if idx != len(config['pubs']) - 1:
        },
        % else:
        }
        % endif
    % endfor
    % if 'ends' in config:
    ],
    % else:
    ]
    % endif
% endif
% if 'ends' in config:
    "endpoints": [
    % for idx, elem in enumerate(config['ends']):
        <% [name, *dest] = elem.split(',', maxsplit=2) %>
        {
            % if dest:
            "name": "${name}",
            "destination": "${''.join(dest)}"
            % else:
            "name": "${name}"
            % endif
        % if idx != len(config['ends']) - 1:
        },
        % else:
        }
        % endif
    % endfor
    ]
% endif
}
