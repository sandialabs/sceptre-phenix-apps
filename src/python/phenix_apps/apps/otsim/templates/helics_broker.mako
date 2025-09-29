<% type = '--dynamic' if cfg['dynamic'] else '-f{}'.format(cfg['feds']) %>\
helics_broker ${type} --ipv4 --web --http_server_args="--http_port=8080 --external" --loglevel ${cfg['log-level']} --logfile ${cfg['log-file']} --autorestart &
