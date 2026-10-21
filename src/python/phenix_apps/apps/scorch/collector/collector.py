import configparser
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import MetadataBlock, Seconds
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

from .csv_gen import gen_csv

# TODO: make what's saved configurable (like the experiment)
# TODO: migrate CSV generation functionality to harmonize (csv_gen.py)
# TODO: configuration option to specify what components to collect from explicitly
# TODO: extend the stop-order check to the other components it collects from


class CollectorMetadata(MetadataBlock):
    """Metadata for the collector component; see README.md for each field."""

    collect_iperf: bool = False
    collect_miniccc: bool = False
    generate_csv: bool = False
    # tolerated shortfall of the merged capture against the disruption duration
    pcap_duration_margin: Seconds = 6.0


class Collector(ComponentBase):
    metadata_model = CollectorMetadata
    config: CollectorMetadata

    def __init__(self):
        ComponentBase.__init__(self, "collector")

        # results_dir: top-level directory in the final collection of files
        self.results_dir = Path(self.base_dir, "experiment_results")

        # meta_dir: "metadata" sub-directory in results directory
        self.meta_dir = Path(self.results_dir, "metadata")

        # Determine what scorch components are enabled, and enable lookups
        # by component type (for cases when name and type differ).
        components = self.extract_app("scorch").metadata.components
        self.all_components = {c.type: c for c in components}
        self.run_config = self.extract_app("scorch").metadata.runs[self.run]
        self.enabled_components = enabled_by_type(components, self.run_config)
        if self.config.collect_iperf:
            check_iperf_before_collector(components, self.run_config)

        self.execute_stage()

    def stop(self):
        logger.info(f"Stopping user component: {self.name}")

        record = {}

        # Check what the record needs from the disruption component before
        # copying anything, so a missing piece fails in seconds, not at the end.
        disruption_metadata = self._disruption_metadata()

        self.results_dir.mkdir()
        self.meta_dir.mkdir()

        # sceptre: topology, scenario, experiment
        sceptre_topo = self.get_annotation("topology")
        sceptre_scenario = self.get_annotation("scenario")
        if not sceptre_topo or not sceptre_scenario:
            raise ValueError(
                "experiment metadata.annotations must name its topology and scenario"
            )

        topo_data = utils.run_command(
            ["phenix", "config", "get", f"topology/{sceptre_topo}"]
        )
        sc_data = utils.run_command(
            ["phenix", "config", "get", f"scenario/{sceptre_scenario}"]
        )
        exp_data = utils.run_command(
            ["phenix", "config", "get", f"experiment/{self.exp_name}"]
        )
        assert topo_data
        assert sc_data
        assert exp_data

        Path(self.meta_dir, "topology.yaml").write_text(topo_data)
        Path(self.meta_dir, "scenario.yaml").write_text(sc_data)
        Path(self.meta_dir, "experiment.yaml").write_text(exp_data)

        self._collect_vmstats()
        self._collect_hoststats()

        # miniccc logs
        if self.config.collect_miniccc:
            logger.info("collecting miniccc data")
            mc_dir = Path(self.base_dir, "miniccc")
            vm_names = self.extract_node_names()
            for vm in vm_names:
                os_type = self.extract_node_os_type(vm)
                m_dest = str(mc_dir / f"{vm}_miniccc.log")
                if os_type == "windows":
                    self.recv_file(vm, "/minimega/miniccc.log", m_dest)
                elif os_type == "linux" and self.require_node(vm).type != "Router":
                    self.recv_file(vm, "/miniccc.log", m_dest)

        # iperf: client, server, histograms
        iperf_dest = None
        if self.config.collect_iperf:
            if self._check_component("iperf"):
                iperf_src = self._comp_dir("iperf")
                iperf_dest = Path(self.results_dir, "iperf")
                logger.info("copying iperf data")
                shutil.copytree(iperf_src, iperf_dest)
                for log in iperf_dest.rglob("*.log"):
                    if log.stat().st_size == 0:
                        log.unlink()
            else:
                logger.error(
                    f"'collect_iperf' is set but 'iperf' component isn't enabled in run/loop stages for run {self.run}"
                )

        # disruption: attack_results, scenario_results, scenario_*
        s_src = self._comp_dir("disruption")
        s_dest = Path(self.results_dir, "disruption")
        logger.info("copying disruption data")
        shutil.copytree(s_src, s_dest)

        # Use duration for the configured disruption
        configured_duration = float(disruption_metadata.run_duration)

        # disruption start time
        start_time_fmt = Path(s_src, "disruption_start_time.txt").read_text()
        start_time = _utc_time(start_time_fmt, "disruption_start_time.txt")
        start_time_kibana = utils.kibana_format_time(start_time)
        logger.info(
            f"disruption start time: {start_time_fmt} (kibana format: '{start_time_kibana}')"
        )

        # disruption stop time
        actual_stop_time_fmt = Path(s_src, "disruption_stop_time.txt").read_text()
        actual_stop_time = _utc_time(actual_stop_time_fmt, "disruption_stop_time.txt")
        actual_stop_time_kibana = utils.kibana_format_time(actual_stop_time)
        logger.info(
            f"disruption stop time (actual): {actual_stop_time_fmt} (kibana format: '{actual_stop_time_kibana}')"
        )

        # clamp the stop time to be start_time + configured duration
        stop_time_modified = start_time + timedelta(seconds=configured_duration)
        stop_time_modified_fmt = stop_time_modified.isoformat()
        stop_time_modified_kibana = utils.kibana_format_time(stop_time_modified)
        logger.info(
            f"disruption stop time (modified): {stop_time_modified_fmt} (kibana format: '{stop_time_modified_kibana}')"
        )

        # duration of the disruption (stop - start); the check below also
        # covers a stop time earlier than start + run_duration
        duration_actual = (actual_stop_time - start_time).total_seconds()
        logger.info(f"disruption duration (actual)     : {duration_actual}")
        logger.info(f"disruption duration (configured) : {configured_duration}")
        if duration_actual < configured_duration:
            raise RuntimeError(
                f"actual duration of {duration_actual:.2f} was less than the configured duration of {configured_duration}, something might have gone wrong..."
            )

        # Record (experiment_record.json)
        logger.info("generating experiment record")

        current_disruption = str(
            disruption_metadata.current_disruption
        )  # baseline, dos, physical
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
            raise ValueError(f"bad disruption name: {current_disruption}")

        if current_disruption == "baseline":
            record["disruption"]["baseline"] = {}

        if current_disruption in ["dos", "cyber_physical"]:
            dos_config = disruption_metadata.dos
            ares_name = Path(
                dos_config.get("results_path", "attacker_results.json")
            ).name
            dos_att_results = utils.read_json(Path(s_src, ares_name))

            record["disruption"]["dos"] = {
                "configuration": dict(dos_config),
                "results": dos_att_results,
            }
            record["disruption"]["dos"]["configuration"]["attacker"]["ip"] = (
                self.extract_node_ip(
                    name=dos_config.attacker.hostname,
                    iface=dos_config.attacker.get("interface", "eth0"),
                )
            )

        if current_disruption in ["physical", "cyber_physical"]:
            scn_res_name = Path(disruption_metadata.physical.results_path).name
            scn_results = utils.read_json(Path(s_src, scn_res_name))

            record["disruption"]["physical"] = {
                **dict(disruption_metadata.physical),
                "results": scn_results,
            }

        # qos: store in the record what QoS values were applied
        record["qos"] = self._collect_qos()

        # Power system data from provider (RTDS, OPALRT, etc.)
        record["provider"] = self._collect_provider_data()

        # all_hosts
        # map hostnames to IP addresses
        all_hosts = {}  # hostname: ip
        for node in self.extract_node_names():
            ifaces = (self.require_node(node).get("network") or {}).get(
                "interfaces"
            ) or []
            # skip hosts with only management interface, like power provider
            if len(ifaces) > 1:
                all_hosts[node] = ifaces[0].address
        record["all_hosts"] = all_hosts

        # pcap metadata
        record["pcap_metadata"] = self._collect_pcap()

        # save record to file
        record_path = Path(self.results_dir, "experiment_record.json")
        logger.info(f"Saving experiment record to {record_path}")
        utils.write_json(record_path, record)

        # TODO: update for providerdata/opalrt
        # === CSV file (experiment_results.csv) ===
        # Uses Elasticsearch configuration from the 'rtds' component metadata
        # TODO: move to harmonize, just do basic validation of data here
        # TODO: run count query to verify number of expected docs
        if self.config.generate_csv:
            if not self._check_component("rtds"):
                raise ValueError(
                    "'generate_csv' is true but 'rtds' component not enabled (CSV generation only works for RTDS)"
                )

            rtds_metadata = self.enabled_components["rtds"].metadata
            gen_csv(
                record=record,
                csv_path=self.results_dir / "experiment_results.csv",
                es_server=rtds_metadata.elasticsearch.server,
                es_index=rtds_metadata.elasticsearch.index,
                iperf_dir=iperf_dest,
            )

        logger.info(f"Stopped user component: {self.name}")

    def _collect_provider_data(self) -> dict:
        """
        Collect data from the 'providerdata' or 'rtds' components.
        """

        data = {
            "simulator": "",
            "pmus": {},
            "gtnet_skt_tags": [],
            "modbus_registers": [],
        }

        # provider: YAML config, log files, CSV files, tags, PMU metadata
        if self._check_component("providerdata"):
            prov_src = self._comp_dir("providerdata")
        elif self._check_component("rtds"):
            prov_src = self._comp_dir("rtds")
        else:
            logger.error(
                "WARNING: No provider data configured for experiment, "
                "either 'providerdata' or 'rtds' component should be "
                "configured, skipping..."
            )
            return {}

        dest = Path(self.results_dir, "provider_data")
        logger.info(f"copying provider data from '{prov_src}'")
        utils.rglob_copy("*.csv", prov_src, dest)
        utils.rglob_copy("*.yaml", prov_src, self.meta_dir)
        utils.rglob_copy("*.txt", prov_src, self.meta_dir)
        utils.rglob_copy("*.json", prov_src, self.meta_dir)
        utils.rglob_copy("*.err", prov_src, self.meta_dir)
        utils.rglob_copy("*.out", prov_src, self.meta_dir)
        utils.rglob_copy("*.ini", prov_src, self.meta_dir)

        # Read Provider config
        ini_path = self.meta_dir / "config.ini"
        if not ini_path.is_file() or not ini_path.read_text().strip():
            raise RuntimeError("Non-existent or empty config.ini from provider")

        pconf = configparser.ConfigParser()
        pconf.read(ini_path)

        # check if this is an updated config
        if not pconf.has_option("power-solver-service", "config-file"):
            raise RuntimeError(
                "Old-style provider config detected (non-YAML). This is not "
                "supported by this version of collector, use an older version."
            )

        data["simulator"] = pconf.get("power-solver-service", "solver-type")

        # parse new-style YAML-formatted config
        logger.info("Parsing YAML provider config")
        config_file = Path(pconf.get("power-solver-service", "config-file")).name
        yaml_path = Path(self.meta_dir, config_file)
        with yaml_path.open() as yf:
            yaml_conf = yaml.safe_load(yf)

        if yaml_conf.get("pmu", {}).get("pmus"):
            # {PMU1: BUS7, ...}
            for p in yaml_conf["pmu"]["pmus"]:
                data["pmus"][p["name"]] = p["label"]
            logger.info(f"{len(data['pmus'])} PMUs")
        else:
            logger.info(
                f"WARNING: No PMUs defined for {data['simulator']} Provider, skipping adding PMU names to record..."
            )

        if yaml_conf.get("gtnet_skt", {}).get("tags"):
            # [G1CB1, G2CB2, ...]
            for gt in yaml_conf["gtnet_skt"]["tags"]:
                data["gtnet_skt_tags"].append(gt["name"].split(".")[0])
            logger.info(f"{len(data['gtnet_skt_tags'])} GTNET-SKT tags")
        elif data["simulator"].upper().strip() == "RTDS":
            logger.info(
                "WARNING: No GTNET-SKT tags defined for RTDS Provider, skipping adding those tags to record..."
            )

        if yaml_conf.get("modbus", {}).get("registers"):
            for mb in yaml_conf["modbus"]["registers"]:
                data["modbus_registers"].append(mb["name"])
            logger.info(f"{len(data['modbus_registers'])} Modbus registers")
        else:
            logger.info(
                f"WARNING: No Modbus registers defined for {data['simulator']} Provider, skipping adding register names to record..."
            )

        return data

    def _collect_qos(self) -> dict:
        """
        'qos' scorch component. Collect what QoS values were applied.
        """
        if not self._check_component("qos"):
            return {}

        qos_file = self._comp_dir("qos") / "qos_values_applied.json"
        logger.info("copying qos data")
        utils.copy_file(qos_file, self.meta_dir)

        return utils.read_json(qos_file)

    def _collect_vmstats(self) -> None:
        """
        'vmstats' scorch component.
        """
        if not self._check_component("vmstats"):
            return

        vms_src = self._comp_dir("vmstats") / "vm_stats.jsonl"
        logger.info("copying vmstats data")
        utils.copy_file(vms_src, self.meta_dir)

    def _collect_hoststats(self) -> None:
        """
        'hoststats' scorch component.
        """
        if not self._check_component("hoststats"):
            return

        hs_src = self._comp_dir("hoststats") / "host_stats.jsonl"
        logger.info("copying hoststats data")
        utils.copy_file(hs_src, self.meta_dir)

    def _collect_pcap(self):
        """
        'pcap' scorch component. Collects PCAP files and extracts their metadata
        to store in the experiment record
        """
        if not self._check_component("pcap"):
            return None

        pcap_src = self._comp_dir("pcap")
        pcap_dest = Path(self.results_dir, "pcaps")
        logger.info("copying pcap data")
        shutil.copytree(pcap_src, pcap_dest)

        # NOTE: pcap durations for several of the PCAPs may be shorter than the configured duration
        # This is due to the low packet rate, e.g. one packet every 9 seconds, may end up with a capture
        # duration of 21 seconds instead of 30 seconds (because capture duration is based on last packet timestamp)
        pcap_meta_file = pcap_dest / "pcap_metadata.json"
        pcap_metadata = utils.read_json(pcap_meta_file)

        if self._check_component("disruption"):
            dis_configured_duration = float(
                self.enabled_components["disruption"].metadata.run_duration
            )
            merged = pcap_metadata.get("merged.pcap")
            if merged is None:
                logger.warning(
                    "no merged.pcap (pcap's create_merged_pcap is off), "
                    "skipping the capture duration check"
                )
                return pcap_metadata
            expected_cap_duration = float(merged["Capture duration (seconds)"])

            if (
                expected_cap_duration + self.config.pcap_duration_margin
            ) < dis_configured_duration:
                raise RuntimeError(
                    f"Capture duration {expected_cap_duration} seconds is "
                    f"more than {self.config.pcap_duration_margin} seconds less than configured disruption "
                    f"duration of {dis_configured_duration} seconds"
                )

        return pcap_metadata

    def _comp_dir(self, component_type: str) -> Path:
        """
        NOTE: the output dir is the components *name*, not the *type*.
        Have to lookup name from the type.
        """
        # the enabled instance, when there is one: a scenario often defines
        # several components of a type (one disruption per permutation)
        component = self.enabled_components.get(
            component_type, self.all_components[component_type]
        )
        component_name = component.name

        # Components run in configure, before any loop starts, write to the
        # run-level folder (loop-0-count-0), so fall back to it.
        run_dir = Path(self.files_dir, f"scorch/run-{self.run}/{component_name}")
        pth = run_dir / f"loop-{self.loop}-count-{self.count}"
        if not pth.is_dir():
            pth = run_dir / "loop-0-count-0"
        if not pth.is_dir():
            raise RuntimeError(
                f"Output directory doesn't exist for scorch component '{component_type}' (name={component_name}): {run_dir}/loop-{self.loop}-count-{self.count}"
            )

        return pth

    def _disruption_metadata(self):
        """The enabled disruption component's metadata, checked for what the
        experiment record reads from it."""

        disruption = self.enabled_components.get("disruption")
        if not disruption:
            raise ValueError(
                "the collector needs a 'disruption' component in this run's "
                "stages, but none is enabled"
            )
        md = disruption.get("metadata") or {}
        missing = [
            k
            for k in ("current_disruption", "permutation", "run_duration")
            if md.get(k) is None
        ]
        if missing:
            raise ValueError(
                f"disruption component '{disruption.name}' is missing "
                f"{', '.join(missing)}, which the collector's experiment record needs"
            )
        return md

    def _check_component(self, component_type: str) -> bool:
        """Check if component is enabled for this run, and if not, log the fact."""
        if not self.enabled_components.get(component_type):
            logger.info(
                f"NOTE: skipping '{component_type}' collection as its not defined in scorch metadata or set in any run/loop stage for run {self.run}"
            )
            return False
        return True


def enabled_by_type(components: list, run_config) -> dict:
    """The component of each type that this run uses, keyed by type.

    A component is used if its name is in one of the run's stage lists,
    including the loop's. A scenario often defines several of a type (one
    disruption per permutation) and enables one per run; if a run enables
    several, the first listed in the scenario wins.
    """

    stages = [s for s in run_config.values() if isinstance(s, list)]
    stages += [s for s in run_config.get("loop", {}).values() if isinstance(s, list)]
    used = {name for stage in stages for name in stage}

    enabled: dict = {}
    for comp in components:
        if comp.name in used:
            enabled.setdefault(comp.type, comp)
    return enabled


def check_iperf_before_collector(components: list, run_config) -> None:
    """iperf writes its results in `stop`, so with `collect_iperf` it must be
    listed before the collector in every `stop` list that has both."""

    types = {c.name: c.type for c in components}
    stops = [run_config.get("stop") or [], run_config.get("loop", {}).get("stop") or []]
    for stop in stops:
        kinds = [types.get(n) for n in stop]
        if "collector" in kinds and "iperf" in kinds:
            last_iperf = len(kinds) - 1 - kinds[::-1].index("iperf")
            if last_iperf > kinds.index("collector"):
                raise ValueError(
                    "'collect_iperf' is set but 'iperf' is listed after "
                    f"'collector' in the stop stage {stop}: the collector would "
                    "copy iperf's results before they are written; list iperf first"
                )


def _utc_time(text: str, source: str) -> datetime:
    """Parse a disruption timestamp file, which must hold a UTC ISO time."""

    when = datetime.fromisoformat(text.strip())
    if when.utcoffset() != timedelta(0):
        raise RuntimeError(f"{source} is not a UTC time: {text!r}")
    return when


def main():
    Collector()


if __name__ == "__main__":
    main()
