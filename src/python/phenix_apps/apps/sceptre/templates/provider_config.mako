<%page args="solver, server_endpoint, publish_endpoint, debug='False', config_helics=None, case_file=None, oneline_file=None, pwds_endpoint=None, config_file=None, **kwargs"/>
[power-solver-service]
solver-type       = ${solver}
debug             = ${debug}
% if config_helics:
config-file       = ${config_helics}
% endif
% if solver != 'PowerWorldHelics':
server-endpoint   = ${server_endpoint}
publish-endpoint  = ${publish_endpoint}
% endif
% if solver == 'PowerWorld':
noise             = normal
% endif
% if solver in ['PowerWorld', 'PowerWorldDynamics']:
objects-file      = C:/sceptre/objects.txt
% endif
% if solver in ['PowerWorld', 'PowerWorldHelics']:
case-file         = C:/sceptre/${case_file}
    % if oneline_file:
oneline-file      = C:/sceptre/${oneline_file}
    % endif
% elif solver == 'PowerWorldDynamics':
pwds-endpoint     = ${pwds_endpoint}
objects-file      = /etc/sceptre/objects.txt
% elif solver in ['OpenDSS', 'PyPower']:
case-file         = /etc/sceptre/${case_file}
% endif
% if solver in ['RTDS', 'OPALRT'] or config_file:
config-file       = ${config_file}
% endif
