import sys
from collections import defaultdict
from pathlib import Path

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import utils
from phenix_apps.common.logger import logger


class QoS(ComponentBase):
    """
    Implements minimega's "qos" API for applying quality of service (QoS) limits.
    """

    def __init__(self):
        ComponentBase.__init__(self, 'qos')
        self.execute_stage()

    def start(self):
        logger.info(f'Starting user component: {self.name}')

        values_applied = defaultdict(dict)
        vms = self.metadata.vms
        self.print(f"applying qos to {len(vms)} VMs")

        for i, vm in enumerate(vms):
            hostname, interface = self.get_host_and_iface(vm)

            values_applied[hostname]["interface"] = interface

            loss = vm.get('loss')
            delay = vm.get('delay')
            rate = vm.get('rate')

            # at least one must be specified
            if delay is None and loss is None and rate is None:
                self.eprint(f'must specify one of loss, delay, or rate in config for node {hostname} (node config={vm})')
                sys.exit(1)

            # rate cannot be combined with loss or delay
            if rate is not None and (loss is not None or delay is not None):
                self.eprint(f'cannot use rate limit at the same time as loss or delay for node {hostname} (node config={vm})')
                sys.exit(1)

            # apply loss
            if loss is not None:
                loss = float(loss)
                # TODO: manual specification of what variable loss is multiplied by
                if vm.get('variable_loss') is not None:
                    loss = float(vm.variable_loss) * self.count  # type: float
                    self.print(f"variable_loss is set, {vm.variable_loss} * {self.count} => {loss} loss for run iteration {self.count} for interface {interface} on node {hostname}")

                self.print(f'adding loss of {loss} to interface {interface} on node {hostname} ({i+1} of {len(vms)})')
                if loss < 0.0 or loss > 99.9:
                    self.eprint(f"loss of {loss} for {hostname} is not between 0.0 - 99.9 (note: 100% loss is not possible with minimega)")
                    sys.exit(1)
                self.mm.qos_add_loss(hostname, interface, loss)
                values_applied[hostname]["loss"] = loss

            # apply delay
            if delay is not None:
                delay = delay.strip().lower()  # duration of delay
                self.print(f'adding delay of {delay} to interface {interface} on node {hostname} ({i+1} of {len(vms)})')
                self.mm.qos_add_delay(hostname, interface, delay)
                values_applied[hostname]["delay"] = delay

            # apply rate limit
            if rate is not None:
                bw, unit = rate.strip().lower().split(' ')

                if unit not in ['kbit', 'mbit', 'gbit']:
                    self.eprint(f'rate limit unit must be one of kbit, mbit, or gbit, not {unit} for node {hostname} (node config={vm})')
                    sys.exit(1)

                self.print(f'adding rate limit of {bw} {unit} to interface {interface} on node {hostname} ({i+1} of {len(vms)})')
                self.mm.qos_add_rate(hostname, interface, bw, unit)
                values_applied[hostname]["rate"] = f"{bw} {unit}"

        qos_path = Path(self.base_dir, "qos_values_applied.json")
        self.print(f"saving qos values applied to {qos_path}")
        utils.write_json(qos_path, values_applied)

        logger.info(f'Started user component: {self.name}')

    def stop(self):
        logger.info(f'Stopping user component: {self.name}')

        vms = self.metadata.vms  # type: list
        self.print(f"clearing qos from {len(vms)} VMs")
        for i, vm in enumerate(vms):
            hostname, interface = self.get_host_and_iface(vm)
            self.print(f'clearing qos for interface {interface} on node {hostname} ({i+1} of {len(vms)})')
            self.mm.clear_qos(hostname, interface)

        logger.info(f'Stopped user component: {self.name}')


def main():
    QoS()


if __name__ == '__main__':
    main()
