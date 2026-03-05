import os
import subprocess
import time
from datetime import datetime

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class MM(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, "mm")

        self.execute_stage()

    def configure(self):
        self.__run("configure")

    def start(self):
        self.__run("start")

    def stop(self):
        self.__run("stop")

    def cleanup(self):
        self.__run("cleanup")

    def __run(self, stage: str) -> None:
        mm = self.mm_init()

        commands = self.metadata.get(stage, [])

        for cmd in commands:
            # TODO: ensure bridge capture gets run on each namespace host

            if cmd.type == "start_capture":
                cap = cmd.get("capture", None)

                if not cap:
                    raise ValueError("no bridge capture details provided")

                bridge = cap.get("bridge", None)

                if not bridge:
                    raise ValueError("bridge to capture traffic on not provided")

                now = datetime.utcnow()
                filename = os.path.basename(
                    cap.get("filename", f"{bridge}-{now:%Y-%m-%dT%H:%M:%SZ}.pcap")
                )

                if not filename.lower().endswith(".pcap"):
                    filename += ".pcap"

                cap_filter = cap.get("filter", None)

                if cap_filter:
                    mm.capture_pcap_filter(cap_filter)

                snaplen = cap.get("snaplen", None)

                if snaplen:
                    mm.capture_pcap_snaplen(snaplen)

                try:
                    logger.info(f"starting pcap capture for bridge {bridge}")
                    mm.mesh_send("all", f"shell mkdir -p {self.base_dir}")
                    mm.capture_pcap_bridge(
                        bridge, os.path.join(self.base_dir, filename)
                    )
                    logger.info(f"started pcap capture for bridge {bridge}")
                except Exception as ex:
                    raise RuntimeError(
                        f"unable to start pcap capture for bridge {bridge}: {ex}"
                    ) from ex
                finally:
                    mm.capture_pcap_filter(None)
                    mm.capture_pcap_snaplen(None)
            elif cmd.type == "stop_capture":
                cap = cmd.get("capture", None)

                if not cap:
                    raise ValueError("no bridge capture details provided")

                bridge = cap.get("bridge", None)

                if not bridge:
                    raise ValueError("bridge to stop capture traffic on not provided")
                try:
                    logger.info(f"stopping pcap capture on bridge {bridge}")
                    mm.capture_pcap_delete_bridge(bridge)
                    logger.info(f"stopped pcap capture on bridge {bridge}")

                    mm.file_get(os.path.relpath(self.base_dir, self.root_dir))

                    if cap.get("convert", False):
                        logger.info(
                            "Waiting for transfer of pcap files to head node to complete."
                        )

                        # wait for file transfer back to head node to be done
                        while True:
                            time.sleep(2)

                            status = mm.file_status()
                            done = True

                            for host in status:
                                done &= len(host["Tabular"]) == 0

                            if done:
                                break

                        logger.info(
                            "Transfer of pcap files to head node has completed."
                        )

                        # convert pcap files
                        for file in os.listdir(self.base_dir):
                            if file.endswith(".pcap") and not os.path.exists(
                                f"{file}.jsonl"
                            ):
                                logger.info(
                                    f"starting PCAP --> JSON conversion of {file}"
                                )

                                pcap_in = os.path.join(self.base_dir, file)
                                json_out = f"{pcap_in}.jsonl"

                                subprocess.run(
                                    f"bash -c 'tshark -r {pcap_in} -T ek > {json_out} 2>/dev/null'",
                                    shell=True,
                                )

                                logger.info(
                                    f"PCAP --> JSON conversion of {file} complete"
                                )
                except Exception as ex:
                    raise RuntimeError(
                        f"unable to stop pcap capture on bridge {bridge}: {ex}"
                    ) from ex
            else:
                raise ValueError(f"Unknown command type '{cmd.type}'")

        vms = self.metadata.get("vms", [])

        for vm in vms:
            commands = vm.get(stage, [])

            for cmd in commands:
                if cmd.type == "start":
                    try:
                        logger.info(f"starting VM {vm.hostname}")
                        mm.vm_start(vm.hostname)
                        logger.info(f"started VM {vm.hostname}")
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to start vm {vm.hostname}: {ex}"
                        ) from ex
                elif cmd.type == "stop":
                    try:
                        logger.info(f"stopping VM {vm.hostname}")
                        mm.vm_stop(vm.hostname)
                        logger.info(f"stopped VM {vm.hostname}")
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to stop vm {vm.hostname}: {ex}"
                        ) from ex
                elif cmd.type == "connect":
                    conn = cmd.get(cmd.type, None)

                    if not conn:
                        raise ValueError(
                            f"no connect details provided for vm {vm.hostname}"
                        )

                    iface = conn.get("interface", None)

                    if iface is None:
                        raise ValueError(
                            f"interface to connect not provided for vm {vm.hostname}"
                        )

                    vlan = conn.get("vlan", None)

                    if not vlan:
                        raise ValueError(
                            f"VLAN to connect interface {iface} to not provided for vm {vm.hostname}"
                        )

                    bridge = conn.get("bridge", None)

                    try:
                        logger.info(
                            f"connecting interface {iface} on {vm.hostname} to VLAN {vlan}"
                        )
                        mm.vm_net_connect(vm.hostname, iface, vlan, bridge)
                        logger.info(
                            f"connected interface {iface} on {vm.hostname} to VLAN {vlan}"
                        )
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to connect interface {iface} on {vm.hostname} to VLAN {vlan}: {ex}"
                        ) from ex
                elif cmd.type == "disconnect":
                    conn = cmd.get(cmd.type, None)

                    if not conn:
                        raise ValueError(
                            f"no disconnect details provided for vm {vm.hostname}"
                        )

                    iface = conn.get("interface", None)

                    if iface is None:
                        raise ValueError(
                            f"interface to disconnect not provided for vm {vm.hostname}"
                        )

                    try:
                        logger.info(f"disconnecting interface {iface} on {vm.hostname}")
                        mm.vm_net_disconnect(vm.hostname, iface)
                        logger.info(f"disconnected interface {iface} on {vm.hostname}")
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to disconnect interface {iface} on {vm.hostname}: {ex}"
                        ) from ex
                elif cmd.type == "start_capture":
                    cap = cmd.get("capture", None)

                    if not cap:
                        raise ValueError(
                            f"no capture details provided for vm {vm.hostname}"
                        )

                    iface = cap.get("interface", None)

                    if iface is None:
                        raise ValueError(
                            f"interface to capture traffic on not provided for vm {vm.hostname}"
                        )

                    now = utils.utc_now()
                    filename = os.path.basename(
                        cap.get(
                            "filename",
                            f"{vm.hostname}-{iface}-{now:%Y-%m-%dT%H:%M:%SZ}.pcap",
                        )
                    )

                    if not filename.lower().endswith(".pcap"):
                        filename += ".pcap"

                    cap_filter = cap.get("filter", None)

                    if cap_filter:
                        mm.capture_pcap_filter(cap_filter)

                    snaplen = cap.get("snaplen", None)

                    if snaplen:
                        mm.capture_pcap_snaplen(snaplen)

                    try:
                        logger.info(
                            f"starting pcap capture for interface {iface} on {vm.hostname}"
                        )
                        mm.mesh_send("all", f"shell mkdir -p {self.base_dir}")
                        mm.capture_pcap_vm(
                            vm.hostname, iface, os.path.join(self.base_dir, filename)
                        )
                        logger.info(
                            f"started pcap capture for interface {iface} on {vm.hostname}"
                        )
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to start pcap capture for interface {iface} on {vm.hostname}: {ex}"
                        ) from ex
                    finally:
                        mm.capture_pcap_filter(None)
                        mm.capture_pcap_snaplen(None)
                elif cmd.type == "stop_capture":
                    cap = cmd.get("capture", None)

                    try:
                        logger.info(f"stopping pcap capture(s) on VM {vm.hostname}")
                        mm.capture_pcap_delete_vm(vm.hostname)
                        logger.info(f"stopped pcap capture(s) on VM {vm.hostname}")

                        mm.file_get(os.path.relpath(self.base_dir, self.root_dir))

                        if cap and cap.get("convert", False):
                            logger.info(
                                "Waiting for pcap transfers to head node to complete."
                            )

                            # wait for file transfer back to head node to be done
                            while True:
                                time.sleep(2)

                                status = mm.file_status()
                                done = True

                                for host in status:
                                    done &= len(host["Tabular"]) == 0

                                if done:
                                    break

                            # convert pcap files
                            for file in os.listdir(self.base_dir):
                                if file.endswith(".pcap") and not os.path.exists(
                                    f"{file}.jsonl"
                                ):
                                    logger.info(
                                        f"starting PCAP --> JSON conversion of {file}"
                                    )

                                    pcap_in = os.path.join(self.base_dir, file)
                                    json_out = f"{pcap_in}.jsonl"

                                    subprocess.run(
                                        f"bash -c 'tshark -r {pcap_in} -T ek > {json_out} 2>/dev/null'",
                                        shell=True,
                                    )

                                    logger.info(
                                        f"PCAP --> JSON conversion of {file} complete"
                                    )
                    except Exception as ex:
                        raise RuntimeError(
                            f"unable to stop pcap capture(s) on vm {vm.hostname}: {ex}"
                        ) from ex
                else:
                    raise ValueError(
                        f"Unknown command type for VM '{vm.hostname}': {cmd.type}"
                    )


def main():
    MM()


if __name__ == "__main__":
    main()
