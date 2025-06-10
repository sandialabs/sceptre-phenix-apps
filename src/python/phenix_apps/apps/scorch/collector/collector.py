import configparser
import sys
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import logger, utils
from .csv_gen import gen_csv

# TODO: "self.name" is the name of the stage I think, not the component
#   Need a way to handle stages that don't match the names of their components
# TODO: only collect data for components that are enabled for the run
#   can iterate over the scorch app data from the Scenario config
# TODO: make what's saved configurable (like the experiment)
# TODO: migrate CSV generation functionality to harmonize (csv_gen.py)


class Collector(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, 'collector')
        self.execute_stage()

    def stop(self):
        logger.log('INFO', f'Stopping user component: {self.name}')

        record = {}

        results_dir = Path(self.base_dir, "experiment_results")
        results_dir.mkdir()

        meta_dir = Path(results_dir, "metadata")
        meta_dir.mkdir()

        # sceptre: topology, scenario, experiment
        sceptre_topo = self.experiment.metadata.annotations.topology
        sceptre_scenario = self.experiment.metadata.annotations.scenario

        topo_data = utils.run_command(f"phenix config get topology/{sceptre_topo}")
        sc_data = utils.run_command(f"phenix config get scenario/{sceptre_scenario}")
        exp_data = utils.run_command(f"phenix config get experiment/{self.exp_name}")
        assert topo_data and sc_data and exp_data

        Path(meta_dir, "topology.yaml").write_text(topo_data)
        Path(meta_dir, "scenario.yaml").write_text(sc_data)
        Path(meta_dir, "experiment.yaml").write_text(exp_data)

        # vmstats
        vms_src = self._comp_dir("vmstats") / "vm_stats.jsonl"
        self.print("copying vmstats data")
        utils.copy_file(vms_src, meta_dir)

        # hoststats
        hs_src = self._comp_dir("hoststats") / "host_stats.jsonl"
        self.print("copying hoststats data")
        utils.copy_file(hs_src, meta_dir)

        # miniccc logs
        if self.metadata.get("collect_miniccc", False):
            self.print("collecting miniccc data")
            mc_dir = Path(self.base_dir, "miniccc")
            vm_names = self.extract_node_names()
            for vm in vm_names:
                node = self.extract_node(vm)
                m_dest = str(mc_dir / f"{vm}_miniccc.log")
                if node.hardware.os_type == "windows":
                    self.recv_file(vm, "/minimega/miniccc.log", m_dest)
                elif node.hardware.os_type == "linux" and node.type != "Router":
                    self.recv_file(vm, "/miniccc.log", m_dest)

        # iperf: client, server, histograms
        iperf_dest = None
        if self.metadata.get("collect_iperf", False):
            iperf_src = self._comp_dir("iperf")
            iperf_dest = Path(results_dir, "iperf")
            self.print("copying iperf data")
            shutil.copytree(iperf_src, iperf_dest)

        # disruption: attack_results, scenario_results, scenario_*
        s_src = self._comp_dir("disruption")
        s_dest = Path(results_dir, "disruption")
        self.print("copying disruption data")
        shutil.copytree(s_src, s_dest)

        # qos: what values were applied
        qos_file = self._comp_dir("qos") / "qos_values_applied.json"
        self.print("copying qos data")
        utils.copy_file(qos_file, meta_dir)

        # Use duration for the configured disruption
        disruption_metadata = self._get_component("disruption").metadata
        configured_duration = float(disruption_metadata.run_duration)

        # disruption start time
        start_time_fmt = Path(s_src, "disruption_start_time.txt").read_text()
        start_time = datetime.fromisoformat(start_time_fmt)
        assert start_time.tzinfo.tzname(start_time) == "UTC"
        start_time_kibana = utils.kibana_format_time(start_time)
        self.print(f"disruption start time: {start_time_fmt} (kibana format: '{start_time_kibana}')")

        # disruption stop time
        actual_stop_time_fmt = Path(s_src, "disruption_stop_time.txt").read_text()
        actual_stop_time = datetime.fromisoformat(actual_stop_time_fmt)
        assert actual_stop_time.tzinfo.tzname(actual_stop_time) == "UTC"
        actual_stop_time_kibana = utils.kibana_format_time(actual_stop_time)
        self.print(f"disruption stop time (actual): {actual_stop_time_fmt} (kibana format: '{actual_stop_time_kibana}')")

        # clamp the stop time to be start_time + configured duration
        stop_time_modified = start_time + timedelta(seconds=configured_duration)  # type: datetime
        assert stop_time_modified <= actual_stop_time
        assert stop_time_modified.tzinfo.tzname(actual_stop_time) == "UTC"
        stop_time_modified_fmt = stop_time_modified.isoformat()
        stop_time_modified_kibana = utils.kibana_format_time(stop_time_modified)
        self.print(f"disruption stop time (modified): {stop_time_modified_fmt} (kibana format: '{stop_time_modified_kibana}')")

        # duration of the disruption (stop - start)
        duration_actual = (actual_stop_time - start_time).total_seconds()
        self.print(f"disruption duration (actual)     : {duration_actual}")
        self.print(f"disruption duration (configured) : {configured_duration}")
        if duration_actual < configured_duration:
            self.eprint(f"actual duration of {duration_actual:.2f} was less than the configured duration of {configured_duration}, something might have gone wrong...")
            sys.exit(1)

        # pcap: pcap files
        pcap_src = self._comp_dir("pcap")
        pcap_dest = Path(results_dir, "pcaps")
        self.print("copying pcap data")
        shutil.copytree(pcap_src, pcap_dest)

        # NOTE: pcap durations for several of the PCAPs may be shorter than the configured duration
        # This is due to the low packet rate, e.g. one packet every 9 seconds, may end up with a capture
        # duration of 21 seconds instead of 30 seconds (because capture duration is based on last packet timestamp)
        pcap_meta_file = pcap_dest / "pcap_metadata.json"
        pcap_metadata = utils.read_json(pcap_meta_file)

        expected_cap_duration = float(pcap_metadata["merged.pcap"]["Capture duration (seconds)"])
        if (expected_cap_duration + 6.0) < configured_duration:
            self.eprint(f"Capture duration {expected_cap_duration} seconds is more than 6.0 seconds less than configured disruption duration of {configured_duration} seconds")
            sys.exit(1)

        # Record (experiment_record.json)
        self.print("generating experiment record")

        current_disruption = str(disruption_metadata.current_disruption)  # baseline, dos, physical
        permutation = int(disruption_metadata.permutation)
        record["experiment"] = {
            "disruption": current_disruption,
            "permutation": permutation,
            "iteration": self.count,
            "start": start_time_fmt,
            "end": stop_time_modified_fmt,
            "duration": configured_duration,
            "kibana_format_start_time": start_time_kibana,
            "kibana_format_end_time": stop_time_modified_kibana,
            "duration_actual": duration_actual,
            "end_time_actual": actual_stop_time_fmt,
        }

        # sceptre: names of scenario, topology, experiment, and scorch metadata
        record["sceptre"] = {
            "experiment": self.exp_name,
            "topology": sceptre_topo,
            "scenario": sceptre_scenario,
            "minimega_version": self.mm.version()[0]["Response"],
            "phenix_version": utils.run_command("phenix version").strip(),
        }
        record["scorch"] = {
            "run": self.run,
            "loop": self.loop,
            "count": self.count,
        }

        # disruptions
        record["disruption"] = {}

        if current_disruption not in ["baseline", "dos", "physical", "cyber_physical"]:
            self.eprint(f"bad disruption name: {current_disruption}")
            sys.exit(1)

        if current_disruption == "baseline":
            record["disruption"]["baseline"] = {}

        if current_disruption in ["dos", "cyber_physical"]:
            dos_config = disruption_metadata.dos
            ares_name = Path(dos_config.get("results_path", "attacker_results.json")).name
            dos_att_results = utils.read_json(Path(s_src, ares_name))

            record["disruption"]["dos"] = {
                "configuration": dict(dos_config),
                "results": dos_att_results,
            }
            record["disruption"]["dos"]["configuration"]["attacker"]["ip"] = self.extract_node_ip(
                name=dos_config.attacker.hostname,
                iface=dos_config.attacker.get("interface", "eth0")
            )

        if current_disruption in ["physical", "cyber_physical"]:
            scn_res_name = Path(disruption_metadata.physical.results_path).name
            scn_results = utils.read_json(Path(s_src, scn_res_name))

            record["disruption"]["physical"] = {
                **dict(disruption_metadata.physical),
                "results": scn_results,
            }

        # qos
        record["qos"] = utils.read_json(qos_file)

        # Power system data from provider (RTDS, OPALRT, etc.)
        record["provider"] = self._collect_provider_data(results_dir, meta_dir)

        # all_hosts
        # map hostnames to IP addresses
        all_hosts = {}  # hostname: ip
        for node in self.extract_node_names():
            ifaces = self.extract_node(node).network.interfaces
            # skip hosts with only management interface, like power provider
            if len(ifaces) > 1:
                all_hosts[node] = ifaces[0].address
        record["all_hosts"] = all_hosts

        # pcap metadata
        record["pcap_metadata"] = pcap_metadata

        # save record to file
        record_path = Path(results_dir, "experiment_record.json")
        self.print(f"Saving experiment record to {record_path}")
        utils.write_json(record_path, record)


        # === CSV file (experiment_results.csv) ===
        # Uses Elasticsearch configuration from the 'rtds' component metadata
        # TODO: move to harmonize, just do basic validation of data here
        # TODO: run count query to verify number of expected docs
        if self.metadata.get("generate_csv", True):
            rtds_metadata = self._get_component("rtds").metadata
            gen_csv(
                record=record,
                csv_path=self.results_dir / "experiment_results.csv",
                es_server=rtds_metadata.elasticsearch.server,
                es_index=rtds_metadata.elasticsearch.index,
                iperf_dir=iperf_dest,
            )

        logger.log('INFO', f'Stopped user component: {self.name}')

    def _collect_provider_data(self, results_dir: Path, meta_dir: Path) -> dict:
        """
        Collect data from the 'providerdata' or 'rtds' components.

        Args:
            results_dir: top-level directory in the final collection of files
            meta_dir: "metadata" sub-directory in results directory
        """

        data = {
            "simulator": "",
            "pmus": {},
            "gtnet_skt_tags": [],
            "modbus_registers": [],
        }

        # provider: YAML config, log files, CSV files, tags, PMU metadata
        if self._get_component("providerdata"):
            prov_src = self._comp_dir("providerdata")
        elif self._get_component("rtds"):
            prov_src = self._comp_dir("rtds")
        else:
            self.eprint("WARNING: No provider data configured for experiment, either 'providerdata' or 'rtds' component should be configured, skipping...")
            return {}

        dest = Path(results_dir, "provider_data")
        self.print(f"copying provider data from '{prov_src}'")
        utils.rglob_copy("*.csv", prov_src, dest)
        utils.rglob_copy("*.yaml", prov_src, meta_dir)
        utils.rglob_copy("*.txt", prov_src, meta_dir)
        utils.rglob_copy("*.json", prov_src, meta_dir)
        utils.rglob_copy("*.err", prov_src, meta_dir)
        utils.rglob_copy("*.out", prov_src, meta_dir)
        utils.rglob_copy("*.ini", prov_src, meta_dir)

        # Read Provider config
        ini_path = meta_dir / "config.ini"
        if not ini_path.is_file() and ini_path.read_text():
            self.eprint("Non-existent or empty config.ini from provider")
            sys.exit(1)

        pconf = configparser.ConfigParser()
        pconf.read(ini_path)

        # check if this is an updated config
        if not pconf.has_option("power-solver-service", "config-file"):
            self.eprint(
                "Old-style provider config detected (non-YAML). This is not "
                "supported by this version of collector, use an older version."
            )
            # exit error here because this shouldn't happen
            sys.exit(1)

        data["simulator"] = pconf.get("power-solver-service", "solver-type")

        # parse new-style YAML-formatted config
        self.print("Parsing YAML provider config")
        config_file = Path(pconf.get("power-solver-service", "config-file")).name
        yaml_path = Path(meta_dir, config_file)
        with yaml_path.open() as yf:
            yaml_conf = yaml.safe_load(yf)

        if yaml_conf.get("pmu", {}).get("pmus"):
            # {PMU1: BUS7, ...}
            for p in yaml_conf["pmu"]["pmus"]:
                data["pmus"][p["name"]] = p["label"]
            self.print(f"PMUs: {data['pmus']}")
        else:
            self.print(f"WARNING: No PMUs defined for {data['simulator']} Provider, skipping...")

        if yaml_conf.get("gtnet_skt", {}).get("tags"):
            # [G1CB1, G2CB2, ...]
            for gt in yaml_conf["gtnet_skt"]["tags"]:
                data["gtnet_skt_tags"].append(gt["name"].split(".")[0])
            self.print(f"GTNET-SKT tags: {data['gtnet_skt_tags']}")
        elif data["simulator"].upper().strip() == "RTDS":
            self.print("WARNING: No GTNET-SKT tags defined for RTDS Provider, skipping...")

        if yaml_conf.get("modbus", {}).get("registers"):
            for mb in yaml_conf["modbus"]["registers"]:
                data["modbus_registers"].append(mb["name"])
            self.print(f"Modbus registers: {data['modbus_registers']}")
        else:
            self.print(f"WARNING: No Modbus registers defined for {data['simulator']} Provider, skipping...")

        return data

    def _comp_dir(self, component_name: str) -> Path:
        pth = Path(self.files_dir, f"scorch/run-{self.run}/{component_name}/loop-{self.loop}-count-{self.count}")
        if not pth.is_dir():
            self.eprint(f"Output directory for component '{component_name}' doesn't exist: {pth}")
            sys.exit(1)
        return pth

    def _get_component(self, name: str):
        for component in self.extract_app("scorch").metadata.components:
            if component.type == name:
                return component


def main():
    Collector()


if __name__ == '__main__':
    main()
