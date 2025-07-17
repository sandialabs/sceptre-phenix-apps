import shutil
import sys
from pathlib import Path

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import logger, utils

# TODO: bridge capture functionality from mm.py component
# The issue with bridge captures in phenix is it will capture MGMT traffic,
# which includes traffic from providers to simulators and bennu field devices.
# The workaround for this could be to apply a filter with "capture pcap filter"
# that excludes the IP address ranges used by MGMT and any other undesirable VLANs.
# Additionally, if multiple experiments are running simultaniously on the same
# host, then the capture will pick up traffic from those experiments, if they
# share the same bridge.
# Perhaps a workaround for this would be to add functionality to minimega to
# filter by VLAN during a bridge capture.

# TODO: pcap file retrieval functionality from mm.py component (this assumes one node)
# TODO: allow settings per-vm (or per-bridge) that override the "global" setting,
# e.g. a filter that applies to only one VM. Is this even possible?
# TODO: netflow capture
# TODO: allow tcpdump and/or tshark to be used instead of minimega api

class PCAP(ComponentBase):
    """
    Implements minimega's "capture pcap" API as a Scorch component.
    """

    def __init__(self):
        ComponentBase.__init__(self, "pcap")
        self._check_commands_available()
        self.execute_stage()

    def _check_commands_available(self):
        for command in ["tshark", "capinfos", "editcap", "mergecap"]:
            if not shutil.which(command):
                self.eprint(f"'{command}' is unavailable on this host, which is required for PCAP processing")
                sys.exit(1)

    def start(self):
        logger.log("INFO", f"Starting user component: {self.name}")

        self.print("clearing capture on minimega")
        self.mm.clear_capture("pcap")

        # Berkeley Packet Filter (BPF) syntax: https://biot.com/capstats/bpf.html
        bpf_filter = self.metadata.get("filter")
        if bpf_filter:
            self.print(f"applying pcap BPF filter: '{bpf_filter}'")
            self.mm.capture_pcap_filter(f"'{bpf_filter}'")  # single quotes are needed here

        # https://wiki.wireshark.org/SnapLen
        snaplen = self.metadata.get("snaplen")
        if snaplen is not None:
            try:
                snaplen = int(str(snaplen).strip())
            except Exception:
                self.eprint("snaplen must be a integer")
                sys.exit(1)

            if not snaplen >= 0:
                self.eprint("snaplen must be a positive number")
                sys.exit(1)

            self.print(f"applying pcap snaplen: {snaplen}")
            self.mm.capture_pcap_snaplen(snaplen)

        # TODO: bridge (note: this is implemented in mm.py component)
        # bridge_path = Path(self.base_dir, "phenix.pcap")
        # self.mm.mesh_send('all', f'shell mkdir -p {self.base_dir}')
        # self.mm.capture_pcap_bridge("phenix", str(bridge_path))

        self.print(f"starting capture for {len(self.metadata.vms)} VMs")
        for i, vm in enumerate(self.metadata.vms):
            hostname, interface = self.get_host_and_iface(vm)
            filepath = Path(self.base_dir, f"{hostname}-{interface}.pcap")

            self.print(f"starting capture on '{hostname}' interface '{interface}' to '{filepath}' ({i+1} of {len(self.metadata.vms)})")
            self.mm.capture_pcap_vm(hostname, interface, str(filepath))

        logger.log("INFO", f"Started user component: {self.name}")

    def stop(self):
        logger.log("INFO", f"Stopping user component: {self.name}")

        pcap_paths = []

        self.print(f"stopping captures for {len(self.metadata.vms)} VMs")
        for i, vm in enumerate(self.metadata.vms):
            hostname, interface = self.get_host_and_iface(vm)

            self.print(f"stopping PCAP capture on interface {interface} for VM {hostname} ({i+1} of {len(self.metadata.vms)})")
            self.mm.capture_pcap_delete_vm(hostname)

            pcap_path = Path(self.base_dir, f"{hostname}-{interface}.pcap")
            pcap_paths.append(pcap_path)

        self.print("clearing capture on minimega")
        self.mm.clear_capture("pcap")

        self.print(f"verifying {len(pcap_paths)} PCAP files")
        pcap_metadata = {}
        for pcap_path in pcap_paths:
            if not pcap_path.is_file():
                self.eprint(f"PCAP file doesn't exist: {pcap_path}")
                sys.exit(1)

            try:
                pcap_info = utils.pcap_capinfos(pcap_path)
            except Exception as ex:
                self.eprint(f"failed to run capinfos to verify on PCAP file {pcap_path}: {ex}")
                sys.exit(1)

            # verify pcap files are valid by checking their metadata with capinfos
            if not pcap_info or "pcap" not in pcap_info["File type"]:
                self.eprint(f"failed validation of PCAP metadata for file {pcap_path}\nraw info: {pcap_info}")
                sys.exit(1)

            pcap_metadata[pcap_path.name] = pcap_info

        # merge pcap files together into a single consolidated PCAP
        # the pcaps that were merged will be moved into "raw" sub-directory
        if self.metadata.get("create_merged_pcap", False):
            self.print(f"merging {len(pcap_paths)} PCAP files into a single file (create_merged_pcap=true)")
            merged_path = Path(self.base_dir, "merged.pcap")

            mergecap_cmd = f"mergecap -w {merged_path}"
            for pcap_path in pcap_paths:
                mergecap_cmd += f" {pcap_path}"

            utils.run_command(mergecap_cmd)

            # move all pcaps that were merged into "raw" sub-directory
            new_paths = []
            raw_dir = Path(self.base_dir, "raw")
            raw_dir.mkdir(exist_ok=True)
            for pcap_path in pcap_paths:
                new_path = Path(pcap_path.parent, "raw", pcap_path.name)
                pcap_path.rename(new_path)
                new_paths.append(new_path)

            pcap_paths = new_paths
            pcap_paths.append(merged_path)

            if self.metadata.get("dedupe", True):
                self.print(f"Removing duplicates from '{merged_path.name}'")
                dd_path = Path(self.base_dir, "deduped.pcap")
                utils.run_command(f"editcap -d {merged_path} {dd_path}")
                dd_path.rename(merged_path)  # overwrite merged.pcap with deduped.pcap
            else:
                self.print(f"NOT removing duplicates from '{merged_path.name}' (dedupe=false)")

            pcap_metadata[merged_path.name] = utils.pcap_capinfos(merged_path)

        # Save metadata to JSON file
        m_path = Path(self.base_dir, "pcap_metadata.json")
        self.print(f"saving pcap metadata to {m_path}")
        utils.write_json(m_path, pcap_metadata)

        # Process PCAPs to JSON, once all captures have been stopped
        if self.metadata.get("convertToJSON", False):
            self.print(f"PCAP --> JSON conversion enabled, converting {len(pcap_paths)} files")

            for pcap_path in pcap_paths:
                # load6-0.pcap -> load6-0.jsonl
                json_path = pcap_path.with_suffix(".jsonl")  # .pcap.jsonl could break filters for "*.pcap*"
                self.print(f"running PCAP --> JSON conversion (source={pcap_path.name}, dest={json_path.name})")
                utils.run_command(f"tshark -r {pcap_path} -T ek > {json_path}")
        else:
            self.print("PCAP --> JSON conversion disabled")

        logger.log("INFO", f"Stopped user component: {self.name}")


def main():
    PCAP()


if __name__ == "__main__":
    main()
