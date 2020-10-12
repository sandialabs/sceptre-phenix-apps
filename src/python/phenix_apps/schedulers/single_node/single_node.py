import sys

from phenix_apps.schedulers import SchedulerBase


class SingleNode(SchedulerBase):
    def __init__(self):
        SchedulerBase.__init__(self, 'single-node')

        spec  = self.experiment.spec
        hosts = self.experiment.hosts

        for vm in spec.topology.nodes:
            hostname = vm.general.hostname

            if hostname in spec.schedules:
                continue

            spec.schedules.hostname = hosts[0].name

        print(self.experiment.to_json())


def main():
    SingleNode()


if __name__ == "__main__":
    main()
