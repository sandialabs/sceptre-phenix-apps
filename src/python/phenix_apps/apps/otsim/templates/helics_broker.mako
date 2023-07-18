<% type = '--dynamic' if cfg['dynamic'] else '-f{}'.format(cfg['feds']) %>\
helics_broker ${type} --ipv4 --loglevel ${cfg['log-level']} --logfile ${cfg['log-file']} --autorestart &
