import os
import subprocess as sp

sp.call("ssh root@${ip} 'bash /etc/phenix/startup/sceptre-start.sh'", shell=True)
