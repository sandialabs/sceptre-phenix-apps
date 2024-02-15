import copy, json, os, re, stat

from phenix_apps.apps   import AppBase
from phenix_apps.common import error, logger, utils

from phenix_apps.apps.sceptre.configs import configs

class Sceptre(AppBase):
    @staticmethod
    def is_power_provider(provider):
        md = provider.metadata
        return md.get("simulator", None) in ['PowerWorld', 'PowerWorldHelics',
                                             'PowerWorldDynamics', 'PyPower']

    def __init__(self):
        AppBase.__init__(self, 'sceptre')
        self.eprint(self.stage)
        self.startup_dir   = f"{self.exp_dir}/startup"
        self.sceptre_dir   = f"{self.exp_dir}/sceptre"
        self.analytics_dir = f"{self.exp_dir}/analytics"
        self.elk_dir       = f"{self.analytics_dir}/elk"
        os.makedirs(self.startup_dir,   exist_ok=True)
        os.makedirs(self.sceptre_dir,   exist_ok=True)
        os.makedirs(self.analytics_dir, exist_ok=True)
        os.makedirs(self.elk_dir,       exist_ok=True)
        self.mako_path = utils.abs_path(__file__, "templates/sceptre_start.mako")
        self.mako_templates_path = utils.abs_path(__file__, "templates")
        self.execute_stage()
        # We don't (currently) let the parent AppBase class handle this step
        # just in case app developers want to do any additional manipulation
        # after the appropriate stage function has completed.
        print(self.experiment.to_json())

    def find_override(self, filename):
        # Note, asset_dir must be declared in the scenario.yaml to work correctly
        overrideFile = f"{self.asset_dir}/injects/override/{filename}"
        if os.path.exists(overrideFile):
            return {"src": overrideFile}
        else:
            return None

    def configure(self):
        """
        Recieves: json blob like

        Modifiable:
            `ExperimentSpec` (anything in this)
        Returned:
            `Experiment` (what's passed in, then modified)
        """

        logger.log("INFO", f"Configuring user application: {self.name}...")

        ######################## OPC configure ###################################
        opcs = self.extract_nodes_type("opc")

        for opc in opcs:
            opc_directory = f"{self.sceptre_dir}/{opc.hostname}"

            # If a hardware OPC file exists in the metadata do not inject the
            # automatically generated OPC file.  This is used for OPC configs
            # that include HIL devices because those need to be created manually

            # Create OPC config inject
            kwargs = self.find_override(f"{opc.hostname}_opc.xml")
            if kwargs is None:
                kwargs = {"src": f"{opc_directory}/opc.xml"}
            kwargs.update({
                "dst": "Users/wwuser/Documents/Configs/Inject/opc.xml",
                "description": "opc_hardware_file",
            })
            self.add_inject(hostname=opc.hostname, inject=kwargs)

            # Create TopServer startup script injection
            kwargs = self.find_override(f"{opc.hostname}_topserver.ps1")
            if kwargs is None:
                kwargs = {"src": f"{opc_directory}/topserver.ps1"}
            kwargs.update({
                "dst": "/sceptre/startup/30-topserver.ps1",
                "description": "topserver_file",
            })
            self.add_inject(hostname=opc.hostname, inject=kwargs)

            # Create sceptre startup scheduler injections
            # Mirrors the phenix startup scheduler but is needed in order to run things as local user for UI automation
            kwargs = {
                "src": f"{self.startup_dir}/sceptre-startup-scheduler.cmd",
                "dst": "ProgramData/Microsoft/Windows/Start Menu/Programs/Startup/sceptre-startup_scheduler.cmd",
                "description": "sceptre startup scheduler",
            }
            self.add_inject(hostname=opc.hostname, inject=kwargs)

            kwargs = {
                "src": f"{self.startup_dir}/sceptre-startup.ps1",
                "dst": "sceptre/sceptre-startup.ps1",
                "description": "sceptre startup script",
            }
            self.add_inject(hostname=opc.hostname, inject=kwargs)


        ######################## Field device configure ###################################
        # Identify servers, clients, and feps
        fds = self.extract_nodes_type("fd-server")
        fdc = self.extract_nodes_type("fd-client")
        fdf = self.extract_nodes_type("fep")
        for fd_ in fds + fdc + fdf:
            fd_directory = f"{self.sceptre_dir}/{fd_.hostname}"

            # Create sceptre startup script injection
            kwargs = self.find_override(f"{fd_.hostname}_sceptre-start.sh")
            if kwargs is None:
                kwargs = {"src": f"{self.startup_dir}/{fd_.hostname}-start.sh"}
            kwargs.update({
                "dst": "/etc/phenix/startup/sceptre-start.sh",
                "description": f"{fd_.hostname} startup script",
                "permissions": "0744",
            })
            self.add_inject(hostname=fd_.hostname, inject=kwargs)

            # Create field device config injection
            kwargs = self.find_override(f"{fd_.hostname}_config.xml")
            if kwargs is None:
                kwargs = {"src": f"{fd_directory}/config.xml"}
            kwargs.update({
                "dst": "/etc/sceptre/config.xml",
                "description": f"{fd_.hostname} config"
            })
            self.add_inject(hostname=fd_.hostname, inject=kwargs)

        ######################## HMI configure ###################################
        hmis = self.extract_nodes_type("hmi")

        for hmi in hmis:
            hmi_directory = f"{self.sceptre_dir}/{hmi.hostname}"

            # Create startup script injection
            kwargs = self.find_override(f"{hmi.hostname}_hmi.ps1")
            if kwargs is None:
                kwargs = {"src": f"{hmi_directory}/hmi.ps1"}
            kwargs.update({
                "dst": "/sceptre/startup/30-hmi.ps1",
                "description": "hmi",
            })
            self.add_inject(hostname=hmi.hostname, inject=kwargs)

            # Create sceptre startup scheduler injections
            # Mirrors the phenix startup scheduler but is needed in order to run things as local user for UI automation
            kwargs = {
                "src": f"{self.startup_dir}/sceptre-startup-scheduler.cmd",
                "dst": "ProgramData/Microsoft/Windows/Start Menu/Programs/Startup/sceptre-startup_scheduler.cmd",
                "description": "sceptre startup scheduler",
            }
            self.add_inject(hostname=hmi.hostname, inject=kwargs)

            kwargs = {
                "src": f"{self.startup_dir}/sceptre-startup.ps1",
                "dst": "sceptre/sceptre-startup.ps1",
                "description": "sceptre startup script",
            }
            self.add_inject(hostname=hmi.hostname, inject=kwargs)

        ######################## SCADA server configure ###################################
        scada_servers = self.extract_nodes_type("scada-server")
        for scada_server in scada_servers:
            scada_directory = f"{self.sceptre_dir}/{scada_server.hostname}"
            if "metadata" not in scada_server:
                msg = f"No metadata for {scada_server.hostname}"
                logger.log("WARN", msg)
                continue

            # Create SCADA project file injection
            kwargs = {
                "src": f"{scada_server.metadata.project}",
                "dst": "Users/wwuser/Documents/Configs/Inject/myscada.mep",
                "description": "SCADA project file",
            }
            self.add_inject(hostname=scada_server.hostname, inject=kwargs)

            # Create automation injection
            kwargs = {
                "src": f"{scada_server.metadata.automation}",
                "dst": "myscada.exe",
                "description": "Windows automation binary",
            }
            self.add_inject(hostname=scada_server.hostname, inject=kwargs)

            # Create startup script injection
            kwargs = self.find_override(f"{scada_server.hostname}_scada.ps1")
            if kwargs is None:
                kwargs = {"src": f"{scada_directory}/scada.ps1"}
            kwargs.update({
                "dst": "/sceptre/startup/30-scada.ps1",
                "description": "scada",
            })
            self.add_inject(hostname=scada_server.hostname, inject=kwargs)

            # Create sceptre startup scheduler injections
            # Mirrors the phenix startup scheduler but is needed in order to run things as local user for UI automation
            kwargs = {
                "src": f"{self.startup_dir}/sceptre-startup-scheduler.cmd",
                "dst": "ProgramData/Microsoft/Windows/Start Menu/Programs/Startup/sceptre-startup_scheduler.cmd",
                "description": "sceptre startup scheduler",
            }
            self.add_inject(hostname=scada_server.hostname, inject=kwargs)

            kwargs = {
                "src": f"{self.startup_dir}/sceptre-startup.ps1",
                "dst": "sceptre/sceptre-startup.ps1",
                "description": "sceptre startup script",
            }
            self.add_inject(hostname=scada_server.hostname, inject=kwargs)

        ######################## Engineer workstation configure ###################################
        engineer_workstations = self.extract_nodes_type("engineer-workstation")

        for engineer_workstation in engineer_workstations:
            engineer_directory = (f"{self.sceptre_dir}/{engineer_workstation.hostname}")

            # Create putty startup script injection
            kwargs = self.find_override(f"{engineer_workstation.hostname}_putty.ps1")
            if kwargs is None:
                kwargs = {"src": f"{engineer_directory}/putty.ps1"}
            kwargs.update({
                "dst": "/sceptre/startup/30-putty.ps1",
                "description": "engineer_workstation",
            })
            self.add_inject(hostname=engineer_workstation.hostname, inject=kwargs)

            # Create auto putty connection startup script injection
            if "connect_interval" in engineer_workstation.metadata:
                kwargs = self.find_override(f"{engineer_workstation.hostname}_auto_winscp.ps1")
                if kwargs is None:
                    kwargs = {"src": f"{engineer_directory}/auto_winscp.ps1"}
                kwargs.update({
                    "dst": "/sceptre/startup/40-auto_winscp.ps1",
                    "description": "engineer_workstation auto putty connections",
                })
                self.add_inject(hostname=engineer_workstation.hostname, inject=kwargs)

            # Create sceptre startup scheduler injections
            # Mirrors the phenix startup scheduler but is needed in order to run things as local user for UI automation
            kwargs = {
                "src": f"{self.startup_dir}/sceptre-startup-scheduler.cmd",
                "dst": "ProgramData/Microsoft/Windows/Start Menu/Programs/Startup/sceptre-startup_scheduler.cmd",
                "description": "sceptre startup scheduler",
            }
            self.add_inject(hostname=engineer_workstation.hostname, inject=kwargs)

            kwargs = {
                "src": f"{self.startup_dir}/sceptre-startup.ps1",
                "dst": "sceptre/sceptre-startup.ps1",
                "description": "sceptre startup script",
            }
            self.add_inject(hostname=engineer_workstation.hostname, inject=kwargs)

        ######################## Historian configure ###################################
        historians = self.extract_nodes_type("historian")

        for historian in historians:
            historian_directory = f"{self.sceptre_dir}/{historian.hostname}"

            # Create historian config injection
            kwargs = self.find_override(f"{historian.hostname}_historian_config.txt")
            if kwargs is None:
                kwargs = {"src": f"{historian_directory}/historian_config.txt"}
            kwargs.update({
                "dst": "Users/wwuser/Documents/Configs/Inject/historian_config.txt",
                "description": "historian",
            })
            self.add_inject(hostname=historian.hostname, inject=kwargs)

            # Create historian startup script injection
            kwargs = self.find_override(f"{historian.hostname}_historian.ps1")
            if kwargs is None:
                kwargs = {"src": f"{historian_directory}/historian.ps1"}
            kwargs.update({
                "dst": "/sceptre/startup/30-historian.ps1",
                "description": "historian",
            })
            self.add_inject(hostname=historian.hostname, inject=kwargs)

            # Create sceptre startup scheduler injections
            # Mirrors the phenix startup scheduler but is needed in order to run things as local user for UI automation
            kwargs = {
                "src": f"{self.startup_dir}/sceptre-startup-scheduler.cmd",
                "dst": "ProgramData/Microsoft/Windows/Start Menu/Programs/Startup/sceptre-startup_scheduler.cmd",
                "description": "sceptre startup scheduler",
            }
            self.add_inject(hostname=historian.hostname, inject=kwargs)

            kwargs ={ "src": f"{self.startup_dir}/sceptre-startup.ps1",
                "dst": "sceptre/sceptre-startup.ps1",
                "description": "sceptre startup script",
            }
            self.add_inject(hostname=historian.hostname, inject=kwargs)

        ######################## Provider configure ###################################
        providers = self.extract_nodes_type("provider")
        if not providers:
            msg = "No SCEPTRE providers have been configured for this experiment."
            logger.log("ERROR", msg)
            raise error.AppError(msg)

        for provider in providers:
            vm_directory = f"{self.sceptre_dir}/{provider.hostname}"
            if "metadata" not in provider:
                msg = f"No metadata for {provider.hostname}"
                logger.log("WARN", msg)
                continue

            simulator = provider.metadata.get("simulator", "")  # type: str

            # Create power world provider injections
            if simulator in ["PowerWorld", "PowerWorldHelics"]:
                # config
                kwargs = self.find_override(f"{provider.hostname}_config.ini")
                if kwargs is None:
                    kwargs = {"src": f"{vm_directory}/config.ini"}
                kwargs.update({
                    "dst": "sceptre/config.ini",
                    "description": "PowerWorld_config",
                })
                self.add_inject(hostname=provider.hostname, inject=kwargs)

                # objects
                kwargs = self.find_override(f"{provider.hostname}_objects.txt")
                if kwargs is None:
                    kwargs = {"src": f"{vm_directory}/objects.txt"}
                kwargs.update({
                    "dst": "sceptre/objects.txt",
                    "description": "PowerWorld_objects",
                })
                self.add_inject(hostname=provider.hostname, inject=kwargs)
                # case file
                kwargs = {
                    "src": f"{provider.metadata.case}",
                    "dst": "sceptre/case.PWB",
                    "description": "PowerWorld binary file",
                }
                self.add_inject(hostname=provider.hostname, inject=kwargs)
                # oneline file
                kwargs = {
                    "src": f"{provider.metadata.oneline}",
                    "dst": "sceptre/oneline.pwd",
                    "description": "PowerWorld display file",
                }
                self.add_inject(hostname=provider.hostname, inject=kwargs)

            # Create power world dynammics provider injections
            elif simulator == "PowerWorldDynamics":
                # config
                kwargs = self.find_override(f"{provider.hostname}_config.ini")
                if kwargs is None:
                    kwargs = {"src": f"{vm_directory}/config.ini"}
                kwargs.update({
                    "dst": "/etc/sceptre/config.ini",
                    "description": "PowerWorldDynamics_config",
                })
                self.add_inject(hostname=provider.hostname, inject=kwargs)

                # objects
                kwargs = self.find_override(f"{provider.hostname}_objects.txt")
                if kwargs is None:
                    kwargs = {"src": f"{vm_directory}/objects.txt"}
                kwargs.update({
                    "dst": "/etc/sceptre/objects.txt",
                    "description": "PowerWorldDynamics_objects",
                })
                self.add_inject(hostname=provider.hostname, inject=kwargs)

            # Create Simulink provider injections
            elif simulator == "Simulink":
                # solver
                kwargs = {
                    "src": f"{provider.metadata.solver}",
                    "dst": "/etc/sceptre/simulinksolver",
                    "description": "Simulink solver binary",
                    "permissions": "0777",
                }
                self.add_inject(hostname=provider.hostname, inject=kwargs)

                # publish points
                kwargs = {
                    "src": f"{provider.metadata.publish_points}",
                    "dst": "/etc/sceptre/publishPoints.txt",
                    "description": "Simulink solver publish points",
                    "permissions": "0664",
                }
                self.add_inject(hostname=provider.hostname, inject=kwargs)

                # Ground Truth is the concept of having two versions of the
                # same Simulink simulator, one of which can be modified,
                # the other runs unmodified, thus providing "ground truth"
                # as to what the system state should be before being mettled
                # with (e.g. disruption scenarios).
                #
                # This may or may not work properly as of June 2023, YMMV.
                if provider.metadata.get("gt"):
                    # solver ground truth
                    kwargs = {
                        "src": f"{provider.metadata.gt}",
                        "dst": "/etc/sceptre/simulinkgt",
                        "description": "Simulink solver ground truth binary",
                        "permissions": "0777",
                    }
                    self.add_inject(hostname=provider.hostname, inject=kwargs)

                    # solver ground truth web template
                    kwargs = {
                        "src": f"{provider.metadata.gt_template}",
                        "dst": "/etc/sceptre/main.tmpl",
                        "description": "Simulink solver ground truth web template",
                        "permissions": "0664",
                    }
                    self.add_inject(hostname=provider.hostname, inject=kwargs)

            # Create pypower provider injections
            elif simulator == "PyPower":
                # config
                kwargs = self.find_override(f"{provider.hostname}_config.ini")
                if kwargs is None:
                    kwargs = {"src": f"{vm_directory}/config.ini"}
                kwargs.update({
                    "dst": "/etc/sceptre/config.ini",
                    "description": "PyPower_config",
                })
                self.add_inject(hostname=provider.hostname, inject=kwargs)

                # case file
                kwargs = {
                    "src": f"{provider.metadata.case}",
                    "dst": f"/etc/sceptre/{os.path.basename(provider.metadata.case)}",
                    "description": "PyPower case file",
                }
                self.add_inject(hostname=provider.hostname, inject=kwargs)

            # Create default provider injections
            else:
                # config
                kwargs = self.find_override(f"{provider.hostname}_config.ini")
                if kwargs is None:
                    kwargs = {"src": f"{vm_directory}/config.ini"}
                kwargs.update({
                    "dst": "/etc/sceptre/config.ini",
                    "description": "vm_config",
                })
                self.add_inject(hostname=provider.hostname, inject=kwargs)

            # Create provider startup script injections
            win = "phenix/startup/30-sceptre-start.ps1"
            nix = "/etc/phenix/startup/sceptre-start.sh"
            dst = (
                win if provider.topology.hardware.os_type == "windows" else nix
            )
            startup_file = (
                f"{self.startup_dir}/{provider.hostname}-start.{dst.split('.')[1]}"
            )
            kwargs = self.find_override(f"{provider.hostname}_sceptre-start.{dst.split('.')[1]}")
            if kwargs is None:
                kwargs = {"src": startup_file}
            kwargs.update({
                "dst": dst,
                "description": "provider_startup_scripts",
            })
            self.add_inject(hostname=provider.hostname, inject=kwargs)

        ######################## HELICS configure ###################################
        # HELICS federates
        feds = self.extract_nodes_label("helics-federate")

        for fed in feds:
            vm_dir = f"{self.sceptre_dir}/{fed.hostname}"
            # Create HELICS config injection
            win = "sceptre/helics.json"
            nix = "/etc/sceptre/helics.json"
            dst = (
                nix if fed.topology.hardware.os_type == "linux" else win
            )
            helics_config = f"{vm_dir}/helics.json"
            kwargs = self.find_override(f"{fed.hostname}_helics.json")
            if kwargs is None:
                kwargs = {"src": helics_config}
            kwargs.update({
                "dst": dst,
                "description": "HELICS config",
            })
            self.add_inject(hostname=fed.hostname, inject=kwargs)

        # HELICS broker
        brokers = self.extract_nodes_label("helics-broker")
        for bkr in brokers:
            # Create and write startup injection
            if bkr.topology.hardware.os_type == "linux":
                loglevel = bkr.metadata.get('helics_broker_loglevel', 3) # 3 = summary
                logfile = bkr.metadata.get('helics_broker_logfile',
                        '/etc/sceptre/log/helics_broker.log')
                startup_file = f"{self.startup_dir}/{bkr.hostname}-helics.sh"
                with open(startup_file, "w") as file_:
                    file_.write(f"helics_broker --autorestart --ipv4 -f {len(feds)}"
                                f" --logfile={logfile}"
                                f" --fileloglevel={loglevel} &\n")
                st_ = os.stat(startup_file)
                os.chmod(startup_file, st_.st_mode | stat.S_IEXEC)
                kwargs = self.find_override(f"{bkr.hostname}_helics.sh")
                if kwargs is None:
                    kwargs = {"src": startup_file}
                kwargs.update({
                    "dst": "/etc/phenix/startup/helics-broker-start.sh",
                    "description": "HELICS broker start",
                })
                self.add_inject(hostname=bkr.hostname, inject=kwargs)


        ######################## ELK configure ###################################
        vms = self.extract_nodes_label("elk")

        # Create elk startup injections for virtual field devices
        for vm in vms:
            if vm.topology.hardware.os_type == "linux":
                startup_file = f"{self.startup_dir}/{vm.hostname}-elk-start.sh"
                with open(startup_file, "w") as file_:
                    file_.write(
                        "sleep 10s\nservice filebeat start\nservice"
                        " metricbeat start\nservice collectd start\n"
                    )
                st_ = os.stat(startup_file)
                os.chmod(startup_file, st_.st_mode | stat.S_IEXEC)
                kwargs = self.find_override(f"{vm.hostname}_elk-start.sh")
                if kwargs is None:
                    kwargs = {"src": startup_file}
                kwargs.update({
                    "dst": "/etc/phenix/startup/elk-start.sh",
                    "description": "vm_elk_startup",
                    "permissions": "0774",
                })
                self.add_inject(hostname=vm.hostname, inject=kwargs)

        # Create field device list injection for elk box
        elk = self.extract_nodes_type("elk")

        if len(elk) > 1:
            msg = "There are multiple ELK boxes defined for this SCEPTRE experiment"
            logger.log("ERROR", msg)
            raise error.AppError(msg)

        if elk:
            injects = [
                (
                    f"{self.elk_dir}/fdlist.json",
                    "/etc/phenix/analytics/files/fdlist.json",
                ),
                (
                    f"{self.elk_dir}/reg_addrs.json",
                    "/etc/phenix/analytics/files/reg_addrs.json",
                ),
                (
                    f"{self.elk_dir}/sceptre_provider_restart.py",
                    "/etc/phenix/analytics/files/sceptre_provider_restart.py",
                ),
            ]

            for inj in injects:
                elk_filename = inj[0].split('/')[-1]
                kwargs = self.find_override(f"{elk[0].hostname}_{elk_filename}")
                if kwargs is None:
                    kwargs = {"src": inj[0]}
                kwargs.update({
                    "dst": inj[1],
                    "description": "elk"
                })
                self.add_inject(hostname=elk[0].hostname, inject=kwargs)

        logger.log("INFO", f"Configured user application: {self.name}")

    def pre_start(self):
        logger.log("INFO", f"Running pre_start for user application: {self.name}...")

        # Write sceptre startup script injections
        scheduler_file = f"{self.startup_dir}/sceptre-startup-scheduler.cmd"
        scheduler_mako = "sceptre-startup-scheduler.mako"
        with open(scheduler_file, "w") as file_:
            utils.mako_serve_template(scheduler_mako, self.mako_templates_path, file_)
        os.chmod(scheduler_file, 0o0777)

        startup_file = f"{self.startup_dir}/sceptre-startup.ps1"
        startup_mako = "sceptre-startup.mako"
        with open(startup_file, "w") as file_:
            utils.mako_serve_template(startup_mako, self.mako_templates_path, file_)
        os.chmod(startup_file, 0o777)

        fd_configs = []
        # Add hil tags that are listed in the provider metadata
        # Note: This is taken from the hil_tags found in a providers metadata in the scenario file
        hil_object_list = []


        ######################## Provider pre-start ###################################
        providers    = self.extract_nodes_type("provider")
        provider_map = {}
        objects_file_path = None

        for provider in providers:
            if "metadata" not in provider:
                msg = f"No metadata for {provider.hostname}"
                logger.log("WARN", msg)
                continue

            provider_map[provider.hostname] = provider
            md = provider.metadata
            simulator = md.get("simulator", None)
            pub_endpoint = md.get("publish_endpoint", "udp://*;239.0.0.1:40000")
            ipv4_address = provider.topology.network.interfaces[0].address
            srv_endpoint = f"tcp://{ipv4_address}:5555"

            # Write startup script injection
            ext = (
                ".ps1"
                if provider.topology.hardware.os_type == "windows"
                else ".sh"
            )

            startup_file = f"{self.startup_dir}/{provider.hostname}-start{ext}"

            # if ignition hmi is being used, provider needs to sleep
            # labels: - ignition
            ignition = self.extract_nodes_label("ignition")
            needsleep = True if ignition else False

            with open(startup_file, "w") as file_:
                file_.write(
                    utils.mako_render(
                        self.mako_path,
                        sceptre=provider.hostname,
                        ips=provider.topology.network.interfaces,
                        os=provider.topology.hardware.os_type,
                        publish_endpoint=pub_endpoint,
                        server_endpoint=srv_endpoint,
                        needsleep=needsleep,
                        metadata=md
                    )
                )

                st_ = os.stat(startup_file)
                os.chmod(startup_file, st_.st_mode | stat.S_IEXEC)

            # Write provider config file injections
            provider_directory = f"{self.sceptre_dir}/{provider.hostname}"
            os.makedirs(provider_directory, exist_ok=True)
            config_ini = f"{provider_directory}/config.ini"
            case, oneline, pwds_endpoint = None, None, None
            config_helics = None
            if 'PowerWorld' in simulator:
                objects_file_path = f"{provider_directory}/objects.txt"
                case = "case.PWB"
                oneline = "oneline.pwd"
                # Adding HIL tags
                hil_object_list = md.get('hil_tags', [])
            if simulator == "PowerWorldDynamics":
                pwds_endpoint = md.get('pwds_endpoint', '127.0.0.1')
            elif simulator == "PyPower":
                case = os.path.basename(provider.metadata.case)
            elif "Helics" in simulator:
                win = "C:/sceptre/helics.json"
                nix = "/etc/sceptre/helics.json"
                config_helics = (
                    nix if provider.topology.hardware.os_type == "linux" else win
                )
            with open(config_ini, "w") as file_:
                utils.mako_serve_template(
                    "provider_config.mako",
                    self.mako_templates_path,
                    file_,
                    solver=simulator,
                    publish_endpoint=pub_endpoint,
                    server_endpoint=srv_endpoint,
                    case_file=case,
                    oneline_file=oneline,
                    pwds_endpoint=pwds_endpoint,
                    config_helics=config_helics
                )

        ######################## Field-device pre-start ###################################
        fd_server_configs = {}
        fdlist = {}
        power_object_list = []
        reg_config = {}

        # Write injections for fd-server
        # type: fd-server
        fds = self.extract_nodes_type("fd-server")
        fd_counter = 0

        for fd_ in fds:
            fd_counter += 1

            if not fd_.metadata:
                msg = f"No metadata for {fd_.hostname}."
                logger.log("WARN", msg)
                continue

            # get provider information
            provider = provider_map[fd_.metadata.provider]
            pub_endpoint = provider.metadata.get(
                "publish_endpoint", "udp://*;239.0.0.1:40000"
            )

            #get fd info from metadata
            try:
                srv_name = fd_.metadata.get("server_hostname", None)
                fd_logic = fd_.metadata.get("logic", None)
                fd_cycle_time = fd_.metadata.get("cycle_time", None)
                parsed = SceptreMetadataParser(fd_.metadata)

                if self.is_power_provider(provider):
                    fd_objects = [x['name'] for _, v in parsed.devices_by_protocol.items() for x in v]
                    power_object_list.extend(fd_objects)
            except Exception as e:
                msg = f"There was a problem parsing metadata for {fd_.hostname}.\nPROBLEM: {e}"
                logger.log("WARN", msg)
                raise error.AppError(msg)

            fd_directory = f"{self.sceptre_dir}/{fd_.hostname}"
            os.makedirs(fd_directory, exist_ok=True)

            # If server name isn't specified in metadata, assume it's the provider
            provider_ipv4_address = provider.topology.network.interfaces[0].address
            srv_endpoint = f"tcp://{provider_ipv4_address}:5555" if not srv_name else None
            if not srv_endpoint:
                server = self.extract_node(srv_name)
                server_ip = server.network.interfaces[0].address
                srv_endpoint = f"tcp://{server_ip}:5555"

            # sort out experiment vs serial interface and store appropriate data
            ifaces = fd_.topology.network.interfaces
            fd_interfaces = dict()

            for interface in ifaces:
                if not fd_interfaces.get("tcp", ""):
                    if (not interface.type == "serial" and
                        (interface.vlan and interface.vlan.lower() != "mgmt")):
                        fd_interfaces['tcp'] = interface.address
                    elif (len(fd_.topology.network.interfaces) == 2 and interface.type == "serial"):
                        fd_interfaces['tcp'] = interface.address

                # the provider publish_endpoint should look like 'udp://*;127.0.0.1:40000',
                # but the rtu needs to bind specifically to the mgmt interface
                if interface.vlan and interface.vlan.lower() == "mgmt":
                    pub_endpoint = pub_endpoint.replace("*", interface.address)

            serial_interfaces = [x for x in ifaces if x.type == "serial"]
            if serial_interfaces:
                fd_interfaces['serial'] = []
                for serial_interface in serial_interfaces:
                    fd_interfaces['serial'].append(serial_interface.device)

            # get the class of FieldDeviceConfig based on the type of infrastructure
            InfrastructureFieldDeviceConfig = configs.get_fdconfig_class(
                fd_.metadata.infrastructure
            )

            # instantiate the FieldDeviceConfig class
            fd_config = InfrastructureFieldDeviceConfig(
                provider=fd_.metadata.provider,
                name=fd_.hostname,
                interfaces=fd_interfaces,
                devices_by_protocol=parsed.devices_by_protocol,
                publish_endpoint=pub_endpoint,
                server_endpoint=srv_endpoint,
                reg_config=reg_config,
                counter=fd_counter,
            )

            fd_configs.append(fd_config)
            fd_server_configs[fd_.hostname] = fd_config

            # Write fd server config file injection
            config_file = f"{fd_directory}/config.xml"

            sceptre_type = 'field-device'
            if 'sunspec' in parsed.devices_by_protocol:
                sceptre_type = 'sunspec'

            with open(config_file, "w") as file_:
                if sceptre_type == 'sunspec':
                    utils.mako_serve_template(
                        "sunspec.mako",
                        self.mako_templates_path,
                        file_,
                        name=fd_config.name,
                        cycle_time=fd_cycle_time,
                        infra=fd_config.infrastructure_name,
                        device=fd_config.protocols[0].devices[0],
                        ipaddr=fd_config.ipaddr,
                        publish_endpoint=fd_config.publish_endpoint,
                        server_endpoint=fd_config.server_endpoint,
                        devname=fd_config.protocols[0].devices[0].registers[0].devname,
                    )
                else:
                    utils.mako_serve_template(
                        "fd_server.mako",
                        self.mako_templates_path,
                        file_,
                        fd_config=fd_config,
                        logic=fd_logic,
                        cycle_time=fd_cycle_time,
                    )

            startup_file = f"{self.startup_dir}/{fd_.hostname}-start.sh"

            # type: ignition
            ignition = self.extract_nodes_type("ignition")
            needrestart = True if ignition else False

            with open(startup_file, "w") as file_:
                fd_os = fd_.topology.hardware.os_type
                file_.write(
                    utils.mako_render(
                        self.mako_path,
                        sceptre=sceptre_type,
                        ips=fd_.topology.network.interfaces,
                        os=fd_os,
                        needrestart=needrestart,
                    )
                )

            st_ = os.stat(startup_file)
            os.chmod(startup_file, st_.st_mode | stat.S_IEXEC)

            # generate fdlist
            fdlist[fd_.hostname] = {}
            protocol_config_dict = {
                "dnp3": "20000-local",
                "dnp3-serial": "20000-local",
                "modbus": "502-local",
                "modbus-serial": "502-local",
                "bacnet": "47808-local",
                "goose": "61850",
                "iec60870-5-104": "2404-local",
                "sunspec": "502-local",
            }

            for key in fd_.metadata.keys():
                if key in protocol_config_dict:
                    local_config = protocol_config_dict[key]
                    fdlist[fd_.hostname][local_config] = 1

            fdlist[fd_.hostname]["9990-remote"] = len(fdlist[fd_.hostname].keys())

            # backwards compatibility (might not be necessary)
            if "20000-local" not in fdlist[fd_.hostname]:
                fdlist[fd_.hostname]["20000-local"] = 0
            if "502-local" not in fdlist[fd_.hostname]:
                fdlist[fd_.hostname]["502-local"] = 0
            if "47808-local" not in fdlist[fd_.hostname]:
                fdlist[fd_.hostname]["47808-local"] = 0
            if "2404-local" not in fdlist[fd_.hostname]:
                fdlist[fd_.hostname]["2404-local"] = 0

        # Write power objects file for power provider
        if objects_file_path:
            # Add hil_objects_list to power_objects_list
            power_object_list.extend(hil_object_list)
            # remove duplicates and sort list
            power_object_list = sorted(list(dict.fromkeys(power_object_list)))
            with open(objects_file_path, "w") as file_:
                file_.write("\n".join(power_object_list))

        # Write helics federate config file injections
        feds = self.extract_nodes_label("helics-federate")

        for fed in feds:
            vm_dir = f"{self.sceptre_dir}/{fed.hostname}"
            os.makedirs(vm_dir, exist_ok=True)
            helics_config = f"{vm_dir}/helics.json"
            config = {}
            md = fed.metadata
            helics_md = md.get('helics', {})
            broker = helics_md.get('broker', None) # should be hostname
            # If broker isn't specified in metadata, assume it's local
            broker = self.extract_node(broker) if broker else fed.topology
            ip = broker.network.interfaces[0].address
            config['name'] = helics_md.get('name', fed.hostname)
            config['broker_address'] = ip
            config['log_level'] = helics_md.get('log_level', 3) # 3 = summary
            if 'request_time' in helics_md:
                config['request_time'] = ('"max"'
                                          if helics_md['request_time'] == 'max'
                                          else helics_md['request_time'])
            if 'period' in helics_md:
                config['period'] = helics_md['period']
            if 'real_time' in helics_md:
                config['real_time'] = 'true' if helics_md['real_time'] else 'false'
            if 'end_time' in helics_md:
                config['end_time'] = helics_md['end_time']
            input_regs = ['analog-input', 'binary-input', 'input-register',
                          'discrete-input']
            config['subs'] = []
            config['pubs'] = []
            config['ends'] = []
            if md.get('simulator', None) == 'Helics':
                # get all possible [<provider>/]<tag>,<type> from fd configs
                subs = [(
                    f'{f"{c.provider}/" if r.regtype in input_regs else ""}'
                    f'{r.devname}.{r.field},'
                    f'{"bool" if r.fieldtype.split("-")[0] == "binary" else "double"}')
                    for _,c in fd_server_configs.items() \
                        for p in c.protocols \
                            for d in p.devices \
                                for r in d.registers if r.regtype in input_regs]
                # remove duplicates and sort list
                subs = sorted(list(dict.fromkeys(subs)))
                config['subs'] = subs
                # get all possible <tag>,<provider>/<tag> from fd configs
                ends = [(
                    f'{r.devname}.{r.field},'
                    f'{c.provider}/{r.devname}.{r.field}')
                    for _,c in fd_server_configs.items() \
                        for p in c.protocols \
                            for d in p.devices \
                                for r in d.registers]
                # remove duplicates and sort list
                ends = sorted(list(dict.fromkeys(ends)))
                config['ends'] = ends
            else:
                # get all possible <tag>,<type> from fd configs
                pubs = [(
                    f'{r.devname}.{r.field},'
                    f'{"bool" if r.fieldtype.split("-")[0] == "binary" else "double"}')
                    for _,c in fd_server_configs.items() \
                        for p in c.protocols \
                            for d in p.devices \
                                for r in d.registers if c.provider == config['name']]
                # remove duplicates and sort list
                pubs = sorted(list(dict.fromkeys(pubs)))
                config['pubs'] = pubs
                # get all possible <tag> from fd configs
                ends = [f'{r.devname}.{r.field}'
                    for _,c in fd_server_configs.items() \
                        for p in c.protocols \
                            for d in p.devices \
                                for r in d.registers if c.provider == config['name']]
                # remove duplicates and sort list
                ends = sorted(list(dict.fromkeys(ends)))
                config['ends'] = ends
            # add any additional pubs/subs/ends (e.g. new sub for interdependency logic)
            if 'publications' in helics_md:
                config['pubs'].extend(
                    '{key},{type_}'.format(
                    key=pub['key'],
                    type_=pub['type'])
                    for pub in helics_md['publications'])
            if 'subscriptions' in helics_md:
                # not a typo: {info} will add a comma if necessary
                config['subs'].extend(
                    '{key},{type_}{info}'.format(
                    key=sub['key'],
                    type_=sub['type'],
                    info=',' + sub['info'] if 'info' in sub else '')
                    for sub in helics_md['subscriptions'])
            if 'endpoints' in helics_md:
                # not a typo: {dest} will add a comma if necessary
                config['ends'].extend(
                    '{name}{dest}'.format(
                    name=end['name'],
                    dest=',' + end['destination'] if 'destination' in end else '')
                    for end in helics_md['endpoints'])
            # remove any empty config keys
            config = {k: v for k, v in config.items() if v}
            with open(helics_config, "w") as file_:
                utils.mako_serve_template(
                    "helics_config.mako",
                    self.mako_templates_path,
                    file_,
                    config=config
                )

        # Write fd client file injections
        # type: fd-client
        fd_clients = self.extract_nodes_type("fd-client")

        for fd_ in fd_clients:
            if not fd_.metadata:
                msg = f"No metadata for {fd_.hostname}."
                logger.log("WARN", msg)
                continue

            fd_directory = f"{self.sceptre_dir}/{fd_.hostname}"
            os.makedirs(fd_directory, exist_ok=True)

            for _, iface in enumerate(fd_.topology.network.interfaces):
                if not iface.type == "serial" and (
                        iface.vlan and iface.vlan.lower() != "mgmt"
                ):
                    fd_ip = iface.address
                    break
                elif (
                        len(fd_.topology.network.interfaces) == 2
                        and iface.type == "serial"
                ):
                    fd_ip = iface.address

            server_configs = []
            servers = fd_.metadata.get("connected_rtus", [])

            for server in servers:
                if server in fd_server_configs:
                    server_configs.append(fd_server_configs[server])

            # Write fd client config file
            config_file = f"{fd_directory}/config.xml"
            with open(config_file, "w") as file_:
                utils.mako_serve_template(
                    "fd_client.mako",
                    self.mako_templates_path,
                    file_,
                    server_configs=server_configs,
                    command_endpoint=fd_ip,
                    name=fd_.hostname,
                )

            # Write fd client startup script injections
            startup_file = f"{self.startup_dir}/{fd_.hostname}-start.sh"
            with open(startup_file, "w") as file_:
                fd_interfaces = fd_.topology.network.interfaces
                fd_os = fd_.topology.hardware.os_type

                file_.write(
                    utils.mako_render(
                        self.mako_path,
                        sceptre="field-device",
                        ips=fd_interfaces,
                        os=fd_os,
                    )
                )

                st_ = os.stat(startup_file)
                os.chmod(startup_file, st_.st_mode | stat.S_IEXEC)

        # Write fep file injections
        # type: fep
        feps = self.extract_nodes_type("fep")
        fep_counter = 0

        for fd_ in feps:
            fep_counter += 1

            if not fd_.metadata:
                msg = f"No metadata for {fd_.hostname}."
                logger.log("WARN", msg)
                continue

            fd_directory = f"{self.sceptre_dir}/{fd_.hostname}"
            os.makedirs(fd_directory, exist_ok=True)

            parsed = SceptreMetadataParser(fd_.metadata)
            provider = provider_map[parsed.provider_name]
            pub_endpoint = provider.metadata.get(
                "publish_endpoint", "udp://*;239.0.0.1:40000"
            )

            fd_interfaces = {}
            for _, iface in enumerate(fd_.topology.network.interfaces):
                if "upstream" in iface.name.lower():
                    fd_interfaces['tcp'] = iface.address
                    break
                elif not iface.type == "serial" and (
                        iface.vlan and iface.vlan.lower() != "mgmt"
                ):
                    fd_interfaces['tcp'] = iface.address
                elif (
                        len(fd_.topology.network.interfaces) == 2
                        and iface.type == "serial"
                ):
                    if not fd_interfaces.get("tcp", ""):
                        fd_interfaces['tcp'] = iface.address

            for _, iface in enumerate(fd_.topology.network.interfaces):
                # the provider publish_endpoint should look like 'udp://*;127.0.0.1:40000',
                # but the rtu needs to bind specifically to the mgmt interface
                logger.log('INFO', f'PUB {iface.address}')
                if iface.vlan and iface.vlan.lower() == "mgmt":
                    pub_endpoint = pub_endpoint.replace("*", iface.address)
                    srv_endpoint = f"tcp://{iface.address}:1330"
                    cmd_ip = iface.address
                    break

            serial_interfaces = [
                x
                for x in fd_.topology.network.interfaces
                if x.type == "serial"
            ]

            if serial_interfaces:
                fd_interfaces['serial'] = []
                for serial_iface in serial_interfaces:
                    fd_interfaces['serial'].append(serial_iface.device)

            # add underlying field device servers to tracked config
            server_configs = []
            servers = fd_.metadata.get("connected_rtus", [])

            for server in servers:
                if server in fd_server_configs:
                    server_configs.append(fd_server_configs[server])

                    # include server's devices in FEP's devices metadata
                    for protocol in fd_server_configs[server].protocols:
                        for device in protocol.devices:
                            if protocol.protocol not in parsed.devices_by_protocol:
                                parsed.devices_by_protocol.update({
                                    protocol.protocol: [
                                        {
                                            "type": device.device_type,
                                            "name": device.device_name,
                                        }
                                    ]
                                })
                            else:
                                parsed.devices_by_protocol[protocol.protocol].append(
                                    {
                                        "type": device.device_type,
                                        "name": device.device_name,
                                    }
                                )

                    # remove RTU servers from server_configs to exclude them
                    # from OPC config and upstream data
                    fd_server_configs.pop(server, "")

            InfrastructureFieldDeviceConfig = configs.get_fdconfig_class(
                fd_.metadata.infrastructure
            )

            # instantiate the FieldDeviceConfig class
            fep_config = InfrastructureFieldDeviceConfig(
                provider=fd_.metadata.provider,
                name=fd_.hostname,
                interfaces=fd_interfaces,
                devices_by_protocol=parsed.devices_by_protocol,
                publish_endpoint=pub_endpoint,
                server_endpoint=srv_endpoint,
                reg_config=reg_config,
                counter=fep_counter,
            )
            fd_server_configs[fep_config.name] = fep_config

            # Write fep config file injection
            config_file = f"{fd_directory}/config.xml"

            with open(config_file, "w") as file_:
                utils.mako_serve_template(
                    "fep_template.mako",
                    self.mako_templates_path,
                    file_,
                    server_configs=server_configs,
                    command_endpoint=cmd_ip,
                    name=fd_.hostname,
                    fep_config=fep_config,
                )

            # Write fep startup file injection
            startup_file = f"{self.startup_dir}/{fd_.hostname}-start.sh"

            with open(startup_file, "w") as file_:
                file_.write(
                    utils.mako_render(
                        self.mako_path,
                        sceptre="field-device",
                        ips=fd_.topology.network.interfaces,
                        os=fd_.topology.hardware.os_type,
                    )
                )

                st_ = os.stat(startup_file)
                os.chmod(startup_file, st_.st_mode | stat.S_IEXEC)

        ######################## ELK pre-start ###################################
        # Create elk files
        fdlist_file = f"{self.elk_dir}/fdlist.json"

        with open(fdlist_file, "w") as file_:
            json.dump(fdlist, file_)

        st_ = os.stat(fdlist_file)
        os.chmod(fdlist_file, st_.st_mode | stat.S_IEXEC)

        # we already read in all the providers at the start so no need to re-read them
        for provider in providers:
            provider_ip = provider.topology.network.interfaces[0].address
            provider_restart_file = f"{self.elk_dir}/sceptre_provider_restart.py"

            with open(provider_restart_file, "w") as file_:
                utils.mako_serve_template(
                    "elk.mako", self.mako_templates_path, file_, ip=provider_ip
                )

            os.chmod(provider_restart_file, st_.st_mode | stat.S_IEXEC)

        gtmap = []
        for fd_config in fd_server_configs.values():
            for protocol in fd_config.protocols:
                if "modbus" in protocol.protocol:
                    for device in protocol.devices:
                        for register in device.registers:
                            gtmap.append(
                                {
                                    "ip": fd_config.ipaddr,
                                    "register_type": register.regtype,
                                    "address": register.addr,
                                    "name": register.devname,
                                    "field": register.field,
                                }
                            )

        coil_data_file = f"{self.elk_dir}/reg_addrs.json"

        with open(coil_data_file, "w") as _file:
            json.dump(gtmap, _file)

        ######################## ELK pre-start ###################################
        scada_ips = []
        scada_servers = self.extract_nodes_type("scada-server")
        historian_ips = []
        historians = self.extract_nodes_type("historian")

        # move through historians and scada servers and pull out vlans for non "mgmt"
        for historian in historians:
            for iface in historian.topology.network.interfaces:
                if iface.vlan != "mgmt":
                    historian_ips.append(iface.address)
        for scada_server in scada_servers:
            for iface in scada_server.topology.network.interfaces:
                if iface.vlan != "mgmt":
                    scada_ips.append(iface.address)

        # Create a dictionary of opc config objects where the key is the OPC IP and the value
        # is the opc configs.  This is used later when the historians are created so
        # each historian is configured to use only the OPC on its subnet.
        opc_configs = {}
        opcs = self.extract_nodes_type("opc")

        for opc in opcs:
            if not opc.metadata:
                msg = (
                    f"No metadata for {opc.hostname}. It will be configured to "
                    "monitor all RTUs"
                )

                logger.log("WARN", msg)

                opc_fd_configs = fd_server_configs
            else:
                opc_fd_configs = {}
                opc_dict = opc.metadata

                if "connected_rtus" in opc_dict:
                    for rtu in opc_dict.connected_rtus:
                        if rtu in fd_server_configs:
                            opc_fd_configs[rtu] = fd_server_configs[rtu]
                else:
                    msg = (
                        f"No rtus defined for {opc.hostname}. It will be configured to "
                        "monitor all field devices"
                    )

                    logger.log("WARN", msg)

                    opc_fd_configs = fd_server_configs

            opc_directory = f"{self.sceptre_dir}/{opc.hostname}"
            os.makedirs(opc_directory, exist_ok=True)

            opc_file = f"{opc_directory}/opc.xml"
            opc_ifaces = []
            primary_opc = False
            for iface in opc.topology.network.interfaces:
                if iface.vlan != "mgmt":
                    opc_ifaces.append(iface.address)

            opc_ip = opc_ifaces[0]
            opc_config = configs.OpcConfig(opc_fd_configs, opc_ip)

            # Only keep track of OPC configs for primary OPC machines
            if not re.search(r"secondary|bak", opc.hostname):
                opc_configs[opc_ip] = opc_config
                primary_opc = True
            with open(opc_file, "w") as file_:
                utils.mako_serve_template(
                    "opc_template.mako", self.mako_templates_path, file_, opc_config=opc_config
                )

            # Write OPC config file injection
            topserver_file = f"{opc_directory}/topserver.ps1"
            with open(topserver_file, "w") as file_:
                utils.mako_serve_template(
                    "topserver.mako",
                    self.mako_templates_path,
                    file_,
                    scada_ips=scada_ips,
                    historian_ips=historian_ips,
                    opc_ip=opc_ip,
                    primary_opc=primary_opc,
                )

        ######################## SCADA server pre-start ###################################
        # No need to requery here, we already extracted scada-server
        for scada_server in scada_servers:
            scada_directory = f"{self.sceptre_dir}/{scada_server.hostname}"
            os.makedirs(scada_directory, exist_ok=True)

            # Write scada server startup script injection
            scada_file = f"{scada_directory}/scada.ps1"
            scada_mako = "scada.mako"
            with open(scada_file, "w") as file_:
                utils.mako_serve_template(scada_mako, self.mako_templates_path, file_)

        ######################## HMI pre-start ###################################
        # Create hmi files
        hmis = self.extract_nodes_type("hmi")
        scada_servers = self.extract_nodes_type("scada-server")

        for hmi in hmis:
            hmi_ip = hmi.topology.network.interfaces[0].address
            #add scada connection based on metadata or based on subnet if not metadata
            hmi_scada_ips = []
            if "connected_scadas" in hmi.metadata:
                for hmi_scada_server in hmi.metadata.connected_scadas:
                    for scada_server in scada_servers: 
                        if hmi_scada_server == scada_server.hostname:
                            hmi_scada_ips.append(scada_server.topology.network.interfaces[0].address)
            else:
                if len(scada_ips) == 1:
                    hmi_scada_ips = scada_ips
                else:
                    for scada_ip in scada_ips:
                        if scada_ip.split('.')[:-1] == hmi_ip.split('.')[:-1]:
                            hmi_scada_ips.append(scada_ip)
                    
            hmi_directory = f"{self.sceptre_dir}/{hmi.hostname}"
            os.makedirs(hmi_directory, exist_ok=True)

            # Write HMI startup script injection
            hmi_mako = "hmi.mako"
            auto_hmi = f"{hmi_directory}/hmi.ps1"
            with open(auto_hmi, "w") as file_:
                utils.mako_serve_template(
                    hmi_mako,
                    self.mako_templates_path,
                    file_,
                    scada_ips=hmi_scada_ips,
                    hmi_ip=hmi_ip,
                )

        ######################## Engineer Workstation pre-start ###################################
        # Create engineer workstation files
        rtus = self.extract_nodes_type("fd-server")
        eng_fd = []

        engineer_workstations = self.extract_nodes_type(
            "engineer-workstation"
        )

        #get rtus that engineer workstation can connect to. Connect to all if none given. 
        for engineer_workstation in engineer_workstations:
            if "connected_rtus" in engineer_workstation.metadata:
                for engineer_rtu in engineer_workstation.metadata.connected_rtus:
                    for rtu in rtus:
                        if engineer_rtu == rtu.hostname:
                            eng_fd.append(rtu)
            else:
                for rtu in rtus:
                    eng_fd.append(rtu)

            engineer_directory = (
                f"{self.sceptre_dir}/{engineer_workstation.hostname}"
            )
            os.makedirs(engineer_directory, exist_ok=True)

            # Wrtie engineer workstation putty injection
            putty = f"{engineer_directory}/putty.ps1"
            engineer_mako = "putty.mako"
            with open(putty, "w") as file_:
                utils.mako_serve_template(
                    engineer_mako,
                    self.mako_templates_path,
                    file_,
                    scada_ips=scada_ips,
                    eng_fd=eng_fd,
                )

            #automation script to actively create putty connection
            if "connect_interval" in engineer_workstation.metadata:
                auto_winscp = f"{engineer_directory}/auto_winscp.ps1"
                auto_winscp_mako = "auto_winscp.mako"
                with open(auto_winscp, "w") as file_:
                    utils.mako_serve_template(
                        auto_winscp_mako,
                        self.mako_templates_path,
                        file_,
                        eng_fd=eng_fd,
                        connect_interval=engineer_workstation.metadata.connect_interval
                    )


        ######################## Historian pre-start ###################################
        # Determine primary/secondary historian
        secondary_historian_ips = {"historian": []}
        historian_ifaces = []

        for historian in historians:
            for iface in historian.topology.network.interfaces:
                if iface.vlan != "mgmt":
                    historian_ifaces.append(iface)

            iface = historian_ifaces[0]

            if historian.metadata:
                if "primary" in historian.metadata and historian.metadata.primary:
                    if historian.metadata.primary not in secondary_historian_ips:
                        secondary_historian_ips[historian.metadata.primary] = [
                            iface.address
                        ]
                    else:
                        secondary_historian_ips[historian.metadata.primary].append(
                            iface.address
                        )
            else:
                secondary_historian_ips["historian"].append(iface.address)

        # Write historian files
        for historian in historians:
            historian_directory = f"{self.sceptre_dir}/{historian.hostname}"
            os.makedirs(historian_directory, exist_ok=True)

            iface = historian_ifaces[0]
            hist_ip = iface.address

            # Get the IP address and OPC config object associated with the OPC system that
            # is on the same subnet as this historian instance
            opc_config_ip = ""
            for ip_key in opc_configs:
                if hist_ip.split(".")[:-1] == ip_key.split(".")[:-1]:
                    opc_config_ip = ip_key
                    opc_config = opc_configs[opc_config_ip]
                    break

            # Create an empty historian config object for all historians,
            # including backup and secondary historian VMs.
            # Generally, backup historians only need the very basic config info
            # since they will replicate from the primary historian
            hist_config = configs.HistorianConfig()

            # If this is a primary historian create a full historian object based on the historian-SCADA
            # configuration.
            #   - If connecting directly to OPC include the IP address of OPC server,
            #     IP addresses of the backup historians, and a list of the  points that should be stored
            #     in the historian
            #   - If connecting to the SCADA server no need for OPC info, since the historian gets all
            #     it needs from the SCADA server.  This is currently only used for Wonderware SCADA and
            #     historian products.  Just include the IP addresses of the backup historians for replication
            #   - If there is no metadata treat it as if there is no connection to SCADA
            if not re.search(r"secondary|bak", historian.hostname):
                secondary_ips = []

                if historian.hostname in secondary_historian_ips:
                    secondary_ips = secondary_historian_ips[historian.hostname]

                if historian.metadata:
                    # A list of field "types" to include in the historian configuration, if empty
                    # the configuration will include all the fields it gets from OPC.  Is populated
                    # in a historians metadata.
                    hist_fields = []

                    if "fields" in historian.metadata:
                        hist_fields = historian.metadata.fields

                    if historian.metadata.get("connecttoscada", None):
                        hist_config = configs.HistorianConfig(
                            None, "", secondary_ips, True, hist_fields
                        )
                    else:
                        hist_config = configs.HistorianConfig(
                            opc_config, opc_config_ip, secondary_ips, False, hist_fields
                        )
                else:
                    hist_config = configs.HistorianConfig(
                        opc_config, opc_config_ip, secondary_ips, False
                    )

            # Write historian config file injection
            historian_config_file = f"{historian_directory}/historian_config.txt"
            with open(historian_config_file, "w") as file_:
                utils.mako_serve_template(
                    "historian_config.mako",
                    self.mako_templates_path,
                    file_,
                    hist_config=hist_config,
                    hist_name=historian.hostname,
                )

            # Write historian startup script file injection
            historian_file = f"{historian_directory}/historian.ps1"
            with open(historian_file, "w") as file_:
                utils.mako_serve_template(
                    "historian.mako",
                    self.mako_templates_path,
                    file_,
                    hist_config=hist_config,
                    historian_name=historian.hostname.upper(),
                )
        logger.log('INFO', f"Completed pre_start for user application: {self.name}...")


class SceptreMetadataParser():
    protocols = ['bacnet', 'dnp3', 'dnp3-serial', 'modbus', 'sunspec', 'iec60870-5-104']

    def __init__(self, metadata):
        try:
            self.infrastructure_name = metadata.infrastructure
            self.provider_name = metadata.provider
            self.devices_by_protocol = {}

            for p in self.protocols:
                if p in metadata:
                    md = copy.deepcopy(metadata[p])
                    for i in range(len(md)):
                        for k in md[i].keys():
                            if k == "type" or k == "name":
                                continue
                            md[i].pop(k, None)
                    self.devices_by_protocol[p] = md

        except Exception as e:
            raise error.AppError(f"Failed when parsing metadata.\nError: {e}")

    def get_devices_by_protocol(self, protocol):
        if protocol in self.devices_by_protocol.keys():
            return self.devices_by_protocol[protocol]

        return []

    @staticmethod
    def get_reg_map_dict(topo_dir, topology):
        """Load RegMap json into dict.
        """
        supported_protocols = ["dnp3", "modbus", "bacnet"]
        register_map = {}
        config_path = topo_dir + topology + ".json"

        logger.log('DEBUG', "Retriving register mapping from %s" % register_map)

        with open(config_path) as topo:
            config = json.load(topo)

        for i in range(len(config["nodes"])):
            # only parse if its an rtu that is manually configurable
            if (("metadata" in config["nodes"][i].keys()) and "manual_register_config" in config["nodes"][i]["metadata"].keys()) and "true"==config["nodes"][i]["metadata"]["manual_register_config"].lower():
                register_map[config["nodes"][i]["general"]["hostname"]] = {}

                for proto in supported_protocols:
                    if proto in config["nodes"][i]["metadata"].keys():
                        register_map[config["nodes"][i]["general"]["hostname"]][proto] = config["nodes"][i]["metadata"][proto]

        return register_map


def main():
    Sceptre()
