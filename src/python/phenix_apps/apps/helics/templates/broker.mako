<%
    if cfg.get('parent', None):
        opts = ' --broker {} --local_interface {}'.format(cfg['parent'], cfg['endpoint'])
    elif cfg.get('subs', None):
        opts = ' --subbrokers {}'.format(cfg['subs'])
    else:
        opts = ''
%>\
helics_broker${opts} -f${cfg['feds']} --ipv4 --loglevel ${cfg['log-level']} --logfile ${cfg['log-file']} --autorestart &
