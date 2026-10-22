% for cfg in configs:
  <%
    if cfg.get('parent', None):
        opts = '--broker {} --local_interface {}'.format(cfg['parent'], cfg['endpoint'])
    else:
        opts = '--web --http_server_args="--http_port=8080 --external"'
        if cfg.get('subs', 0):
            opts += ' --subbrokers {}'.format(cfg['subs'])
  %>\
helics_broker \
  --name ${cfg['name']} \
  ${opts} \
  -f${cfg['feds']} \
  --ipv4 \
  --loglevel ${cfg['log-level']} \
  --logfile ${cfg['log-file']} \
  --autorestart &

% endfor
