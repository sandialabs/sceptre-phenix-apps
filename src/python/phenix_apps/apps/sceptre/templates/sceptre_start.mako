% if os == 'linux':
    % for interface in ips:
        % if interface['vlan']:
echo 'ListenAddress ${interface['address']}' >> /etc/ssh/sshd_config
        % endif
    % endfor
service ssh restart
sleep 10s
    % if 'simulink-provider' in name.lower() or metadata.get('simulator', '').lower() == 'simulink':
cd /etc/sceptre/
        % if 'helics-federate' in metadata.get('labels', []):
bennu-simulink-provider-helics --config /etc/sceptre/helics.json 2>&1 > /etc/sceptre/log/provider.log &
        % else:
bennu-simulink-provider --server-endpoint '${server_endpoint}' --publish-endpoint '${publish_endpoint}' 2>&1 > /etc/sceptre/log/provider.log &
        % endif
./simulinksolver -tf inf 2>&1 > /etc/sceptre/log/solver.log &
        % if metadata.get('gt'):
./simulinkgt -addr :8080 -file groundTruth.txt -tmpl main.tmpl 2>&1 > /etc/sceptre/log/gt.log &
        % endif
    % elif metadata.get('simulator','').lower() == 'alicanto':
pybennu-alicanto -c /etc/sceptre/alicanto.json -d DEBUG > /etc/sceptre/log/alicanto.log 2>&1 &
    % elif 'provider' in name.lower() or metadata.get('simulator', '').lower().startswith('powerworld') or metadata.get('simulator', '').lower() in ['pypower', 'siren', 'opalrt', 'rtds']:
        % if needsleep:
sleep 60s
        % endif
ps cax | grep pybennu > /dev/null
if [ $? -eq 0 ]; then
  pybennu-power-solver restart -c /etc/sceptre/config.ini -e pybennu -d
else
  pybennu-power-solver start -c /etc/sceptre/config.ini -e pybennu -d
fi
    % elif name.lower() == 'openplc':
cd /root/OpenPLC_v2
./iec2c st_files/openplc.st
mv -f POUS.c POUS.h LOCATED_VARIABLES.h VARIABLES.csv Config0.c Config0.h Res0.c ./core/
./build_core.sh
    % elif name.lower() == 'sunspec':
echo -e "LD_LIBRARY_PATH=/usr/local/lib\nGOBENNU_CONFIG_FILE=/etc/sceptre/config.xml" > /etc/gobennu-environment
systemctl start gobennu
    % elif name.lower() == 'field-device':
echo "[Hashes]
reghash = `sha256sum /usr/bin/bennu-field-deviced | awk '{print $1}'`
shellhashA = `sed 's/\x5f\x53\x48\x45\x4c\x4c\x5f\x30/\x5f\x53\x48\x45\x4c\x4c\x5f\x31/g' /usr/bin/bennu-field-deviced > /tmp/foo && sha256sum /tmp/foo | awk '{print $1}' && rm /tmp/foo`
shellhashB = `python3 -c "f1=open('/usr/bin/bennu-field-deviced','rb').read();f2=open('/tmp/foo','wb');f2.write(f1.replace(b'SHELL_0',b'SHELL_1'));f2.close()" && sha256sum /tmp/foo | awk '{print $1}' && rm /tmp/foo`
" > /etc/sceptre/watcher.ini
cp /usr/bin/bennu-field-deviced /etc/sceptre/config.xml /home/sceptre/
chown sceptre:sceptre /home/sceptre/*
bennu-watcherd restart --f /etc/sceptre/config.xml --b /home/sceptre/bennu-field-deviced.firmware --w /etc/sceptre/watcher.ini
        % if needrestart:
sleep 60s
bennu-field-deviced --c restart --env default --file /etc/sceptre/config.xml
        % endif
    % endif
% elif os == 'windows' and ('provider' in name.lower() or metadata.get('simulator', '').lower().startswith('powerworld') or metadata.get('simulator', '').lower() == 'pypower'):
function Phenix-StartupComplete {
  $key = Get-Item -LiteralPath 'HKLM:\Software\phenix' -ErrorAction SilentlyContinue

  if ($key) {
    $val = $key.GetValue('startup')

    if ($val) {
      return $val -eq 'done'
    }

    return $false
  }

  return $false
}
if (-Not (Phenix-StartupComplete)) {
    exit
}
Start-Sleep -s 90 #need to wait for helics broker
python.exe 'C:/sceptre/pybennu-power-solver.py' start -c 'C:/sceptre/config.ini' -e 'power-solver'
% endif
