# Command And Control Dropper (cc-dropper)

```
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@&        @@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@*             *@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@&                  (@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@*                     @@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@&/*#@&                       #@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@&                              &@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@.         Command and Contol   (@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@                 Agents       @@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@.                          (@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@.                        @@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@&   &@@@                   *@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@,  *@@@@@@@@(                ,@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@   @@@@@@@@@@@@@@             @@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@,  *@@@@@@@@@@@@@@@@(         /@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@&   @@@@@@@@@@@@@@@@@   (@@@@&@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@,  *@@@@@@@@@@@@@@@@(   @@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@%   &@@@@@@@@@@@@@@@@   #@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@.  *@@@@@@@@@@@@@@@@(   @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@%   &@@@@@@@@@@@@@@@@.  #@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@.  *@@@@@@@@@@@@@@@@(  .@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@%   &@@@@@@@@@@@@@@@@   #@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@.  *@@@@@@@@@@@@@@@@(   @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@,  @@@@@@@@@@@@@@@@@   #@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@.  @@@@@@@@@@@@@@@/   @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@&  #@@@@@@@@@@@@@   #@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@%  #@@@@@@@@@@@/   @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@,  @@@@@@@%.     %@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@    #@@,     *&@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@.    .@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@%@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
```

Phenix user application that will determine operating system from node
topology and inject a command and control agent along with auto start scripts
based on configuration in scenario.

Special thanks to @zach-r-long for the initial development of this app.

## Configuration

Configuration is done in the scenario file loaded into phenix.

App metadata includes the following:

* `agentDir`: path to directory for application to find agents

Host metadata includes the following:

* `agent`: name of agent to add to the host from the `agentDir`.

* `agentArgs`: string passed to `agent` at runtime.

* `autoStart`: boolean that determines if agent auto starts on boot.

* `serviceType`: type of service to use for `autoStart` on Linux. Can be
  `sysinitv, systemd, custom`.

* `customService`: settings used when `serviceType` is `custom`.

    * `injectPath`: path in host where startup script will land.

    * `scriptPath`: path to script whose contents should be prepended to the
      default Linux startup script. Can be left blank.

In the below example VMs with `router` in the name will use the 2nd
configuration, VMs with `site_B_workstation` will use the 1st configuration,
and all other VMs will use the 3rd configuration.

The 2nd configuration is custom and will grab all lines from `scriptPath`
"/phenix/userdata/ccDropper/custom/vyatta.sh" and append then to the starup file
which will be placed in the `injectPath` "/opt/vyatta/etc/config/scripts ..." 
of any VM with a name that matches `.*router`.

## Example w/ miniccc agent:

```
spec:
  apps:
  - name: cc-dropper
    metadata:
      agentDir: /phenix/userdata/ccDropper/agents
    hosts:
    - hostname: site_B_workstation
      metadata:
        agent: miniccc
        agentArgs: "-parent 172.16.10.254"
        autoStart: true
        serviceType: systemd
    - hostname: ".*router"
      metadata:
        agent: miniccc
        agentArgs: "-serial /dev/virtio-ports/cc"
        autoStart: true
        serviceType: custom
        customService:
          injectPath: "/opt/vyatta/etc/config/scripts/vyatta-postconfig-bootup.script"
          scriptPath: "/phenix/userdata/ccDropper/custom/vyatta.sh"
    - hostname: "*"
      metadata:
        agent: miniccc
        agentArgs: "-serial /dev/virtio-ports/cc"
        autoStart: true
        serviceType: sysinitv
```