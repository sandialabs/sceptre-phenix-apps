import timeit
from datetime import timedelta
from pathlib import Path
from time import sleep
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    model_validator,
)

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import (
    Args,
    FilePath,
    Hostname,
    Interface,
    MetadataBlock,
    PositiveSeconds,
    Seconds,
)
from phenix_apps.common import utils
from phenix_apps.common.logger import logger

# A DoS attack shorter than this (seconds) may end before the script has
# started properly, so the metadata check warns about it.
SHORT_ATTACK_SECONDS = 5.0


class Attacker(MetadataBlock):
    hostname: Hostname
    interface: Interface = "eth0"
    script_path: FilePath
    # Extra arguments appended to the script's command line.
    args: Args = ""
    results_path: FilePath
    # The attacker's OS picks the commands used to kill processes, take
    # interfaces down and up, and delete the results file.
    os_type: Literal["linux", "windows"] = "linux"


class Target(MetadataBlock):
    hostname: Hostname
    interface: Interface = "eth0"


class Dos(MetadataBlock):
    attack_duration: PositiveSeconds
    start_delay: Seconds
    # The attack finishes this long before run_duration ends, so its results
    # can be collected.
    wrapup: Seconds = 60.0
    # The component waits this long past start_delay plus the attack before
    # treating the script as hung.
    wait_margin: Seconds = 5.0
    attacker: Attacker
    targets: list[Target] = Field(min_length=1)

    def budget(self, run_duration: float) -> float:
        """Seconds the attack may run after its start delay."""
        return run_duration - self.wrapup - self.start_delay - 1.0

    def run_for(self, run_duration: float) -> float:
        """How long the attack runs: attack_duration, cut to fit the budget."""
        return min(self.attack_duration, self.budget(run_duration))


class Physical(MetadataBlock):
    start_delay: Seconds
    opc_hostname: Hostname
    opc_port: int = Field(4840, ge=1, le=65535)
    script_path: FilePath
    results_path: FilePath
    scenario_path: FilePath
    log_path: FilePath
    # The script's timeout is start_delay plus this.
    timeout_margin: Seconds = 15.0
    python_path: FilePath = (
        "/users/wwuser/appdata/local/programs/python/python38/python.exe"
    )

    def timeout(self, run_duration: float) -> float:
        """Seconds the script may run: start_delay plus the margin, cut to
        fit inside run_duration."""
        timeout = self.start_delay + self.timeout_margin
        return run_duration - 1.0 if timeout > run_duration else timeout


class DisruptionMetadata(BaseModel):
    """Metadata for the disruption component; see README.md for each field."""

    model_config = ConfigDict(extra="allow")

    current_disruption: Literal["baseline", "dos", "physical", "cyber_physical"]
    run_duration: PositiveSeconds
    permutation: NonNegativeInt | None = None
    dos: Dos | None = None
    physical: Physical | None = None

    @model_validator(mode="after")
    def _check_disruption(self) -> Self:
        uses_dos = self.current_disruption in ("dos", "cyber_physical")
        uses_physical = self.current_disruption in ("physical", "cyber_physical")

        if uses_dos and self.dos is None:
            raise ValueError(f"'{self.current_disruption}' needs a dos block")
        if uses_physical and self.physical is None:
            raise ValueError(f"'{self.current_disruption}' needs a physical block")

        if uses_dos and self.dos:
            if self.dos.budget(self.run_duration) <= 0:
                raise ValueError(
                    f"dos.start_delay ({self.dos.start_delay}) leaves no time to attack: "
                    f"run_duration must exceed start_delay + {self.dos.wrapup + 1:g} seconds"
                )
            run_for = self.dos.run_for(self.run_duration)
            if run_for < SHORT_ATTACK_SECONDS:
                logger.warning(
                    f"the dos attack would run for only {run_for:g} seconds; an attack "
                    f"under {SHORT_ATTACK_SECONDS:g} seconds may end before the script "
                    "has started properly, and the run then fails"
                )
        if (
            uses_physical
            and self.physical
            and self.physical.start_delay >= self.run_duration
        ):
            raise ValueError(
                f"physical.start_delay ({self.physical.start_delay}) must be less "
                f"than run_duration ({self.run_duration})"
            )
        # a zero timeout would make the command wait forever
        if (
            uses_physical
            and self.physical
            and self.physical.timeout(self.run_duration) <= 0
        ):
            raise ValueError(
                "physical script timeout is not positive: raise "
                "physical.timeout_margin or run_duration"
            )
        return self


class Disruption(ComponentBase):
    metadata_model = DisruptionMetadata
    config: DisruptionMetadata

    def __init__(self):
        ComponentBase.__init__(self, "disruption")
        self.execute_stage()

    @property
    def dos(self) -> Dos:
        if self.config.dos is None:
            raise ValueError(f"component '{self.name}' has no dos block")
        return self.config.dos

    @property
    def physical(self) -> Physical:
        if self.config.physical is None:
            raise ValueError(f"component '{self.name}' has no physical block")
        return self.config.physical

    def _kill_dos_processes(self):
        a_host = self.dos.attacker.hostname
        logger.info(f"ensuring dos processes are killed on attacker (vm={a_host})")
        os_type = self.dos.attacker.os_type
        script_name = Path(self.dos.attacker.script_path).name
        hping = "hping3.exe" if os_type == "windows" else "hping3"
        utils.mm_kill_process(self.mm, f"name={a_host}", script_name, os_type)
        utils.mm_kill_process(self.mm, f"name={a_host}", hping, os_type)

    def _kill_phys_process(self):
        opc_host = self.physical.opc_hostname
        logger.info(
            f"killing python.exe process on {opc_host} (for physical disruption)"
        )
        utils.mm_kill_process(
            self.mm, f"name={opc_host}", "python.exe", os_type="windows"
        )

    def _attacker_extra_interfaces(self) -> list[str]:
        """Attacker interfaces other than the attack and management ones."""
        a_iface = self.dos.attacker.interface
        a_node = self.require_node(self.dos.attacker.hostname)
        return [
            iface.name
            for iface in a_node.network.interfaces
            if iface.name != a_iface and iface.name.lower() != "mgmt"
        ]

    def _attacker_iface_cmd(self, iface: str, up: bool) -> str:
        """Command that brings an attacker interface up or down."""
        if self.dos.attacker.os_type == "windows":
            state = "enabled" if up else "disabled"
            return f"netsh interface set interface name={iface} admin={state}"
        return f"ip link set {iface} {'up' if up else 'down'}"

    def _build_dos_cmd(self, start_delay: float, dos_run_duration: float) -> str:
        t_ips = [
            self.extract_node_ip(target.hostname, target.interface)
            for target in self.dos.targets
        ]

        extra = f"{self.dos.attacker.args} " if self.dos.attacker.args else ""
        return (
            f"{self.dos.attacker.script_path} "
            f"{extra}"
            f"--wait-for {start_delay} "
            f"--run-for {dos_run_duration} "
            f"--target-ips {' '.join(t_ips)} "
            f"--interface {self.dos.attacker.interface} "
            f"--results-file {self.dos.attacker.results_path}"
        )

    def _run_physical_disruption(self) -> float:
        timer_start = timeit.default_timer()

        opc_host = self.physical.opc_hostname

        # TODO: specify --endpoint tcp://{power_provider_ip}:5555
        # Running the script path directly exits -1 under miniccc, so the
        # absolute path to the python binary is required.
        scn_cmd = (
            f"{self.physical.python_path} {self.physical.script_path} "
            f"--url opc.tcp://{opc_host}:{self.physical.opc_port} "
            f"--scenario-file {self.physical.scenario_path}"
        )

        # the timeout never exceeds experiment duration
        scn_timeout = self.physical.timeout(self.config.run_duration)

        logger.info(
            f"Running disruption command on {opc_host}: {scn_cmd} "
            f"(timeout={scn_timeout})"
        )
        scn_output = self.run_and_check_command(
            opc_host, scn_cmd, timeout=scn_timeout, debug=False
        )
        if not scn_output["stdout"]:
            raise RuntimeError(
                "Failed to run 'cyber_physical' disruption: no stdout from command "
                f"(output={scn_output})"
            )

        elapsed = timeit.default_timer() - timer_start
        logger.info(f"Finished running physical disruption in {elapsed:.2f} seconds")
        logger.info(
            f"=== Physical command output ===\n{scn_output['stdout']}\n"
            "=== End physical command output ==="
        )

        return elapsed

    def _sleep_out(self, used: float) -> None:
        """Sleep through whatever is left of run_duration."""
        remaining = self.config.run_duration - used
        if remaining > 0.1:
            logger.info(
                f"{remaining:.2f} seconds remaining out of configured run_duration "
                f"{self.config.run_duration}, sleeping for that many seconds..."
            )
            sleep(remaining)

    def configure(self):
        logger.info(f"Configuring user component: {self.name}")

        if self.config.current_disruption in ("dos", "cyber_physical"):
            logger.info(
                f"Running checks for '{self.config.current_disruption}' disruption"
            )

            a_host = self.dos.attacker.hostname
            self.ensure_vm_running(a_host)

            for target in self.dos.targets:
                self.ensure_vm_running(target.hostname)

            self._kill_dos_processes()

            # verify hping3 and dos script are installed
            # NOTE: cannot use bash builtins like "command -v" here
            if self.loop < 2 and self.count < 2:
                logger.info(f"Checking if hping3 is installed on '{a_host}'")
                self.run_and_check_command(a_host, "hping3 --version")

                script_path = self.dos.attacker.script_path
                logger.info(f"Checking if {script_path} is installed on '{a_host}'")
                self.run_and_check_command(a_host, f"{script_path} --help")
            else:
                logger.info(
                    f"skipping tool checks after the first loop and count "
                    f"(loop={self.loop}, count={self.count})"
                )

            # disable all interfaces not in use by attacker
            for iface in self._attacker_extra_interfaces():
                logger.info(f"disabling interface {iface} on {a_host}")
                utils.mm_exec_wait(
                    self.mm,
                    a_host,
                    self._attacker_iface_cmd(iface, up=False),
                    timeout=10.0,
                    poll_rate=0.5,
                )

        logger.info(f"Configured user component: {self.name}")

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        # NOTE: Because we have to wait on the dos process, or do a sleep (for
        # baseline), it doesn't make sense to split functionality across
        # start/stop stages (really, it belongs more in an "execution" stage).
        # The "art" scorch component does this as well, with everything in
        # "start" stage.

        # start on the next whole second
        base_start = utils.utc_now()
        rounded_start = (base_start + timedelta(seconds=1)).replace(microsecond=0)
        sleep((rounded_start - base_start).total_seconds())
        start_fmt = rounded_start.isoformat()
        logger.info(f"disruption start time: {start_fmt}")
        Path(self.base_dir, "disruption_start_time.txt").write_text(start_fmt)

        logger.info(
            f"Running '{self.config.current_disruption}' disruption "
            f"(loop={self.loop}, run_duration={self.config.run_duration})"
        )

        if self.config.current_disruption == "baseline":
            logger.info(f"baseline: sleeping for {self.config.run_duration} seconds...")
            sleep(self.config.run_duration)

        elif self.config.current_disruption == "dos":
            run_for = self.dos.run_for(self.config.run_duration)
            cmd = self._build_dos_cmd(self.dos.start_delay, run_for)

            # the script sleeps start_delay before attacking, so wait for both
            timeout = self.dos.start_delay + run_for + self.dos.wait_margin

            a_host = self.dos.attacker.hostname
            logger.info(f"Running DoS command on {a_host}: {cmd} (timeout={timeout})")
            timer_start = timeit.default_timer()
            output = self.run_and_check_command(
                a_host, cmd, timeout=timeout, debug=False
            )
            if not output["stdout"]:
                raise RuntimeError(
                    "Failed to run 'dos' disruption: no stdout from command "
                    f"(output={output})"
                )

            elapsed = timeit.default_timer() - timer_start
            logger.info(f"Finished running DoS command in {elapsed} seconds")
            logger.info(
                f"=== Command output ===\n{output['stdout']}\n"
                "=== End command output ==="
            )

            self._sleep_out(elapsed)

        elif self.config.current_disruption == "physical":
            logger.info(f"sleeping for {self.physical.start_delay} seconds")
            sleep(self.physical.start_delay)

            elapsed = self._run_physical_disruption()

            # sleep until run_duration is up if physical ended early
            self._sleep_out(elapsed + self.physical.start_delay)

        elif self.config.current_disruption == "cyber_physical":
            # run dos attack with its start delay as a background process
            logger.info(
                "Kicking off DoS script in background with start delay of "
                f"{self.dos.start_delay}"
            )
            dos_cmd = self._build_dos_cmd(
                self.dos.start_delay, self.dos.run_for(self.config.run_duration)
            )
            self.mm.cc_filter(f"name={self.dos.attacker.hostname}")
            self.mm.cc_background(dos_cmd)
            self.mm.clear_cc_filter()

            logger.info(f"sleeping for {self.physical.start_delay} seconds")
            sleep(self.physical.start_delay)

            # the physical attack runs in the foreground
            physical_elapsed_time = self._run_physical_disruption()

            # sleep until run_duration is up if physical or dos ended early
            self._sleep_out(physical_elapsed_time + self.physical.start_delay)

        logger.info(f"'{self.config.current_disruption}' disruption complete!")

        # record disruption stop time
        stop_time = utils.utc_now().isoformat()
        logger.info(f"disruption stop time: {stop_time}")
        Path(self.base_dir, "disruption_stop_time.txt").write_text(stop_time)

        if self.config.current_disruption in ("dos", "cyber_physical"):
            self._kill_dos_processes()

            logger.info("saving attacker results")
            self.recv_file(
                vm=self.dos.attacker.hostname,
                src=[self.dos.attacker.results_path, self.dos.attacker.script_path],
            )

        if self.config.current_disruption in ("physical", "cyber_physical"):
            self._kill_phys_process()

            logger.info("saving physical disruption results")
            self.recv_file(
                vm=self.physical.opc_hostname,
                src=[
                    self.physical.script_path,
                    self.physical.results_path,
                    self.physical.scenario_path,
                    self.physical.log_path,
                ],
            )

            logger.info("verifying disruption results")
            scn_path = Path(self.base_dir, Path(self.physical.results_path).name)
            logger.info(f"disruption results path: {scn_path}")
            check_physical_results(utils.read_json(scn_path))

        self.mm.clear_cc_filter()

        logger.info(f"Started user component: {self.name}")

    def cleanup(self):
        logger.info(f"Cleaning up user component: {self.name}")

        if self.config.current_disruption in ("dos", "cyber_physical"):
            # ensure processes are killed for an aborted run
            self._kill_dos_processes()

            # delete result file
            a_host = self.dos.attacker.hostname
            logger.info(f"deleting attacker results (vm={a_host})")
            utils.mm_delete_file(
                self.mm,
                f"name={a_host}",
                self.dos.attacker.results_path,
                os_type=self.dos.attacker.os_type,
            )

            # reset attacker interfaces (the filter is still the attacker)
            for iface in self._attacker_extra_interfaces():
                logger.info(f"bringing up interface {iface} on {a_host}")
                self.mm.cc_exec_once(self._attacker_iface_cmd(iface, up=True))

            sleep(1.0)
            self.mm.clear_cc_filter()

        if self.config.current_disruption in ("physical", "cyber_physical"):
            self._kill_phys_process()

            opc_host = self.physical.opc_hostname
            logger.info(f"deleting physical disruption results on {opc_host}")
            for path in (self.physical.results_path, self.physical.log_path):
                utils.mm_delete_file(
                    self.mm, f"name={opc_host}", path, os_type="windows"
                )

            sleep(1.0)
            self.mm.clear_cc_filter()

        logger.info(f"Cleaned up user component: {self.name}")


def check_physical_results(results: dict) -> None:
    """Fail unless the physical scenario ran and every non-OPC stage succeeded."""

    duration = results.get("scenario_duration", 0)
    if duration <= 1.0:
        raise RuntimeError(
            f"physical disruption did not run: scenario_duration={duration}"
        )
    failed = [
        f"'{stage['name']}': {stage['status']}"
        for stage in results["stages"].values()
        if stage.get("method", "") != "opc" and not stage["successful"]
    ]
    if failed:
        raise RuntimeError(
            f"{len(failed)} disruption stage(s) failed: " + "; ".join(failed)
        )


def main():
    Disruption()


if __name__ == "__main__":
    main()
