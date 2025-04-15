import sys
import timeit
from time import sleep
from pathlib import Path

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import logger, utils

# TODO: user-configurable script path + script arguments for dos
# TODO: allow dos attacks to be executed on Windows


class Disruption(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, 'disruption')
        self.execute_stage()

    def _kill_dos_processes(self):
        a_host = self.metadata.dos.attacker.hostname  # type: str
        self.print(f"ensuring dos processes are killed on attacker (vm={a_host})")
        script_name = Path(self.metadata.dos.attacker.script_path).name
        utils.mm_kill_process(self.mm, f"name={a_host}", script_name)
        utils.mm_kill_process(self.mm, f"name={a_host}", "hping3")

    def _kill_phys_process(self):
        opc_host = self.metadata.physical.opc_hostname
        self.print(f"killing python.exe process on {opc_host} (for physical disruption)")
        utils.mm_kill_process(self.mm, f"name={opc_host}", "python.exe", os_type='windows')

    def _build_dos_cmd(self, start_delay: float, dos_run_duration: float) -> str:
        t_ips = []
        for target in self.metadata.dos.targets:
            t_iface = target.get("interface", "eth0")
            t_ips.append(self.extract_node_ip(target.hostname, t_iface))

        cmd = (
            f"{self.metadata.dos.attacker.script_path} "
            f"--wait-for {start_delay} "
            f"--run-for {dos_run_duration} "
            f"--target-ips {' '.join(t_ips)} "
            f"--interface {self.metadata.dos.attacker.get('interface', 'eth0')} "
            f"--results-file {self.metadata.dos.attacker.results_path}"
        )

        return cmd

    def _run_physical_disruption(self) -> float:
        timer_start = timeit.default_timer()

        opc_host = self.metadata.physical.opc_hostname
        opc_port = int(self.metadata.physical.get('opc_port', 4840))

        # TODO: specify --endpoint tcp://{power_provider_ip}:5555
        # Unfortunately, simply running the script path directly results in exit code -1 when running via miniccc
        # So, we're forced to use the absolute path to the python binary
        python_path = self.metadata.physical.get("python_path", "/users/wwuser/appdata/local/programs/python/python38/python.exe")
        scn_cmd = (
            f"{python_path} {self.metadata.physical.script_path} "
            f"--url opc.tcp://{opc_host}:{opc_port} "
            f"--scenario-file {self.metadata.physical.scenario_path}"
        )

        scn_timeout = float(self.metadata.physical.start_delay) + 15.0
        run_duration = float(self.metadata.run_duration)
        # ensure timeout doesn't exceed experiment duration
        if scn_timeout > run_duration:
            scn_timeout = run_duration - 1.0

        # Run physical disruption
        self.print(f"Running disruption command on {opc_host}: {scn_cmd} (timeout={scn_timeout})")
        scn_output = self.run_and_check_command(opc_host, scn_cmd, timeout=scn_timeout, debug=False)
        if not scn_output["stdout"]:
            self.eprint(f"Failed to run 'cyber_physical' disruption: no stdout from command (output={scn_output})")
            sys.exit(1)

        elapsed = timeit.default_timer() - timer_start
        self.print(f"Finished running physical disruption in {elapsed:.2f} seconds")
        self.print(f"=== Physical command output ===\n{scn_output['stdout']}\n=== End physical command output ===")

        return elapsed

    def configure(self):
        logger.log('INFO', f'Configuring user component: {self.name}')

        if self.metadata.current_disruption in ["dos", "cyber_physical"]:
            self.print(f"Running checks for '{self.metadata.current_disruption}' disruption")

            a_host = self.metadata.dos.attacker.hostname
            self.ensure_vm_running(a_host)

            for target in self.metadata.dos.targets:
                self.ensure_vm_running(target.hostname)

            self._kill_dos_processes()

            # verify hping3 and dos script are installed
            # NOTE: cannot use bash builtins like "command -v" here
            if self.loop < 2 and self.count < 2:
                self.print(f"Checking if hping3 is installed on '{a_host}'")
                self.run_and_check_command(a_host, "hping3 --version")

                script_path = self.metadata.dos.attacker.script_path
                self.print(f"Checking if {script_path} is installed on '{a_host}'")
                self.run_and_check_command(a_host, f"{script_path} --help")
            else:
                self.print(f"skipping tool checks since loop {self.loop} < 2 and count {self.count} < 2")

            # disable all interfaces not in use by attacker
            a_iface = self.metadata.dos.attacker.get("interface", "eth0")
            a_node = self.extract_node(a_host)
            for interface in a_node.network.interfaces:
                if interface.name not in [a_iface, "MGMT", "mgmt"]:
                    self.print(f"disabling interface {interface.name} on {a_host}")
                    utils.mm_exec_wait(self.mm, a_host, f"ip link set {interface.name} down", timeout=10.0, poll_rate=0.5)

        logger.log('INFO', f'Configured user component: {self.name}')

    def start(self):
        logger.log('INFO', f'Starting user component: {self.name}')

        # NOTE: Because we have to wait on the dos process, or do a sleep (for baseline),
        # it doesn't make sense to split functionality across start/stop stages
        # (really, it belongs more in an "execution" stage).
        # The "art" scorch component does this as well, with everything in "start" stage.

        # record disruption start time
        base_start = utils.utc_now()

        # Round up to nearest second
        if base_start.second >= 59:
            rounded_start = base_start.replace(minute=base_start.minute + 1, second=0, microsecond=0)
        else:
            rounded_start = base_start.replace(second=base_start.second + 1, microsecond=0)

        # wait until we've reached the rounded up time
        sleep((rounded_start - base_start).total_seconds())
        start_fmt = rounded_start.isoformat()
        self.print(f"disruption start time: {start_fmt}")
        Path(self.base_dir, "disruption_start_time.txt").write_text(start_fmt)

        run_duration = float(self.metadata.run_duration)

        self.print(f"Running '{self.metadata.current_disruption}' disruption (loop={self.loop}, run_duration={run_duration})")

        if self.metadata.current_disruption == "baseline":
            self.print(f"baseline: sleeping for {run_duration} seconds...")
            sleep(run_duration)

        elif self.metadata.current_disruption == "dos":
            start_delay = float(self.metadata.dos.start_delay)
            attack_duration = float(self.metadata.dos.attack_duration)

            timeout = attack_duration + start_delay + 5.0 # type: float
            tmp_run_duration = run_duration - 60.0
            # ensure timeout doesn't exceed experiment duration
            if timeout > tmp_run_duration:
                timeout = tmp_run_duration - start_delay - 1.0
                timeout = float(abs(timeout))
            else:
                timeout = attack_duration

            cmd = self._build_dos_cmd(start_delay, timeout)

            a_host = self.metadata.dos.attacker.hostname
            self.print(f"Running DoS command on {a_host}: {cmd} (timeout={timeout})")
            timer_start = timeit.default_timer()
            output = self.run_and_check_command(a_host, cmd, timeout=timeout, debug=False)
            if not output["stdout"]:
                self.eprint(f"Failed to run 'dos' disruption: no stdout from command (output={output})")
                sys.exit(1)

            elapsed = timeit.default_timer() - timer_start
            self.print(f"Finished running DoS command in {elapsed} seconds")
            self.print(f"=== Command output ===\n{output['stdout']}\n=== End command output ===")

            remaining = run_duration - elapsed
            if remaining > 0.1:
                self.print(f"{remaining:.2f} seconds remaining out of configured run_duration {run_duration}, sleeping for that many seconds...")
                sleep(remaining)

        elif self.metadata.current_disruption == "physical":
            # run physical attack with start delay
            physical_start_delay = float(self.metadata.physical.start_delay)
            
            # start delay
            self.print(f"sleeping for {physical_start_delay} seconds")
            sleep(physical_start_delay)

            # physical duration
            elapsed = self._run_physical_disruption()

            # sleep until experiment run_duration time is up, physical ended early
            remaining = run_duration - elapsed - physical_start_delay
            if remaining > 0.1:
                self.print(f"{remaining:.2f} seconds remaining out of configured run_duration {run_duration}, sleeping for that many seconds...")
                sleep(remaining)

        elif self.metadata.current_disruption == "cyber_physical":
            # get config data
            physical_start_delay = float(self.metadata.physical.start_delay)
            dos_start_delay = float(self.metadata.dos.start_delay)
            dos_attack_duration = float(self.metadata.dos.attack_duration)

            # make sure total dos attack run time does not exceed total run_duration
            dos_run_duration = dos_attack_duration + dos_start_delay + 5.0
            tmp_run_duration = run_duration - 60.0
            if dos_run_duration > tmp_run_duration:
                dos_run_duration = tmp_run_duration - dos_start_delay - 1.0
                dos_run_duration = float(abs(dos_run_duration))
            else:
                dos_run_duration = dos_attack_duration

            # Kick off DoS process, have it sleep for number of seconds that puts it between line outage and load shedding
            # delay: 6.0 = 2.0 + 4.0 + 60.0 = 66.0
            # using config data dos_start_delay instead

            # run dos attack with start delay as a background process
            self.print(f"Kicking off DoS script in background with start delay of {dos_start_delay}")
            dos_cmd = self._build_dos_cmd(dos_start_delay, dos_run_duration)
            self.mm.cc_filter(f"name={self.metadata.dos.attacker.hostname}")
            self.mm.cc_background(dos_cmd)
            self.mm.clear_cc_filter()

            # Run physical disruption
            # open breaker for generator 1
            # ... wait 2 seconds
            # open transmission line T4 (T4SE and T4RE)
            # ... wait 7 seconds
            # apply 60% load shedding to loads 5 and 6

            # physical start delay sleep
            self.print(f"sleeping for {physical_start_delay} seconds")
            sleep(physical_start_delay)

            # run physical attack not as a background process
            physical_elapsed_time = self._run_physical_disruption()

            # calculate how early everything finished and how much sleep time is needed
            remaining_time = run_duration - physical_elapsed_time - physical_start_delay

            # sleep until experiment run_duration time is up, physical or dos ended early
            if remaining_time > 0.1:
                self.print(f"{remaining_time:.2f} seconds remaining out of configured run_duration {run_duration}, sleeping for that many seconds...")
                sleep(remaining_time)
        else:
            raise ValueError(f"Invalid disruption: {self.metadata.current_disruption}")

        self.print(f"'{self.metadata.current_disruption}' disruption complete!")

        # record disruption stop time
        stop_time = utils.utc_now().isoformat()
        self.print(f"disruption stop time: {stop_time}")
        Path(self.base_dir, "disruption_stop_time.txt").write_text(stop_time)

        if self.metadata.current_disruption in ["dos", "cyber_physical"]:
            self._kill_dos_processes()

            self.print("saving attacker results")
            self.recv_file(
                vm=self.metadata.dos.attacker.hostname,
                src=[
                    self.metadata.dos.attacker.results_path,
                    self.metadata.dos.attacker.script_path,
                ]
            )

        if self.metadata.current_disruption in ["physical", "cyber_physical"]:
            self._kill_phys_process()

            self.print("saving physical disruption results")
            self.recv_file(
                vm=self.metadata.physical.opc_hostname,
                src=[
                    self.metadata.physical.script_path,
                    self.metadata.physical.results_path,
                    self.metadata.physical.scenario_path,
                    self.metadata.physical.log_path,
                ]
            )

            # verify disruption executed correctly
            self.print("verifying disruption results")
            fname = Path(self.metadata.physical.results_path).name
            scn_path = Path(self.base_dir, fname)
            self.print(f"disruption results path: {scn_path}")
            results = utils.read_json(scn_path)
            assert results["scenario_duration"] > 1.0
            self.print(f"{type(results['stages'])}")
            for stage in results["stages"].values():
                if stage.get("method", "") != "opc" and not stage["successful"]:
                    self.eprint(f"failed disruption stage '{stage['name']}': {stage['status']}")
                    sys.exit(1)

        self.mm.clear_cc_filter()

        logger.log('INFO', f'Started user component: {self.name}')

    def cleanup(self):
        logger.log('INFO', f'Cleaning up user component: {self.name}')

        if self.metadata.current_disruption in ["dos", "cyber_physical"]:
            # ensure processes are killed for an aborted run
            self._kill_dos_processes()

            # delete result file
            a_host = self.metadata.dos.attacker.hostname
            self.print(f"deleting attacker results (vm={a_host})")
            self.mm.cc_filter(f"name={a_host}")
            self.mm.cc_exec_once(f"rm -f {self.metadata.dos.attacker.results_path}")

            # reset attacker interfaces
            a_iface = self.metadata.dos.attacker.get("interface", "eth0")
            a_node = self.extract_node(a_host)
            for interface in a_node.network.interfaces:
                if interface.name not in [a_iface, "MGMT", "mgmt"]:
                    self.print(f"bringing up interface {interface.name} on {a_host}")
                    self.mm.cc_exec_once(f"ip link set {interface.name} up")

            sleep(1.0)
            self.mm.clear_cc_filter()

        if self.metadata.current_disruption in ["physical", "cyber_physical"]:
            self._kill_phys_process()

            opc_host = self.metadata.physical.opc_hostname
            self.print(f"deleting physical disruption results on {opc_host})")
            utils.mm_delete_file(self.mm, f"name={opc_host}", self.metadata.physical.results_path, os_type='windows')
            utils.mm_delete_file(self.mm, f"name={opc_host}", self.metadata.physical.log_path, os_type='windows')

            sleep(1.0)
            self.mm.clear_cc_filter()

        logger.log('INFO', f'Cleaned up user component: {self.name}')


def main():
    Disruption()


if __name__ == '__main__':
    main()

