import sys
import os
from ipaddress import ip_network, ip_address

from phenix_apps.apps import AppBase
from phenix_apps.common import logger, utils


class DNS(AppBase):
    def __init__(self):
        AppBase.__init__(self, 'dns')

        self.startup_dir = f"{self.exp_dir}/startup"
        self.dns_dir = f"{self.exp_dir}/dns"

        # Create directories in /phenix/experiments/<exp-name>/
        os.makedirs(self.startup_dir, exist_ok=True)
        os.makedirs(self.dns_dir, exist_ok=True)

        self.execute_stage()

        print(self.experiment.to_json())

    # def pre_start(self):
    def configure(self):
        dns_nodes = self.extract_labelled_topology_nodes("dns-server")
        if not dns_nodes:
            logger.log("ERROR", "No DNS server defined, expected at least one topology node with 'dns-server' label")
            sys.exit(1)

        hostname = dns_nodes[0].general.hostname
        # TODO: iface name in topology may not match interface name on host
        dns_iface = dns_nodes[0].labels["dns-server"]
        # TODO: validate it's a valid domain name
        domain = self.metadata.get("domain", "")

        dns_ip_mask = self.extract_node_interface_ip(hostname, dns_iface, include_mask=True)
        if not dns_ip_mask:
            logger.log("ERROR", f"Failed to find interface '{dns_iface}' for DNS server '{hostname}'")
            sys.exit(1)
        dns_ip = dns_ip_mask[0]
        dns_net = ip_network(f'{dns_ip}/{dns_ip_mask[1]}', strict=False)

        # Hosts to configure with dns
        # Use all hosts with an interface
        # - on same subnet as the DNS server's interface, if same_subnet is true
        # - first interface on host, as long as it's not the MGMT interface

        # hosts => ip: hostname
        hosts = {}  # type: dict[str, str]

        for node in self.experiment.spec.topology.nodes:
            if not node.get("network", {}).get("interfaces"):
                continue

            for i in node.network.interfaces:
                # Skip interfaces without an IP
                if not i.get("address"):
                    continue

                # Skip management interfaces
                if i.name.lower() == "mgmt" or i.get("vlan", "").lower() == "mgmt":
                    continue

                # If same_subnet is true, then skip interfaces that don't
                # have an IP in the same subnet as the DNS server.
                if self.metadata.get("same_subnet", False) and ip_address(i.address) not in dns_net:
                    continue

                # Check for duplicate IPs
                if i.address in hosts:
                    logger.log("WARNING", f"duplicate IP {i.address} from host {node.general.hostname}")

                # Add to hosts that will be added to DNS server's hosts file
                # Remove "_" characters to match phenix's behavior ('_' characters are not valid in hostnames)
                hosts[i.address] = node.general.hostname.replace("_", "")

                # If "dns" is unset on interface, set to DNS server's IP
                if not i.get("dns"):
                    i.dns = [dns_ip]
                # If it's already set, add it to the existing list of servers
                elif isinstance(i.dns, list) and dns_ip not in i.dns:
                    i.dns.append(dns_ip)

                # Don't process any more interfaces
                break

        # ... Generate the files ...

        # TODO: not sure if this is needed
        # /etc/phenix/startup/70_stop_resolved.sh
        stop_path = self.render(
            "stop_resolved.sh.mako",
            f"{self.startup_dir}/70_stop_resolved.sh"
        )
        utils.mark_executable(stop_path)
        self.add_inject(hostname, {
            "src": stop_path,
            "dst": "/etc/phenix/startup/70_stop_resolved.sh",
            "description": "script to kill resolved for DNS server",
        })

        # /etc/phenix/startup/71_dnsmasq_start.sh
        start_path = self.render(
            "dnsmasq_start.sh.mako",
            f"{self.startup_dir}/71_dnsmasq_start.sh"
        )
        utils.mark_executable(start_path)
        self.add_inject(hostname, {
            "src": start_path,
            "dst": "/etc/phenix/startup/71_dnsmasqstart.sh",
            "description": "Startup script for dnsmasq for DNS server",
        })

        # /etc/resolv.conf
        resolv_path = self.render(
            "resolv.conf.mako",
            f"{self.dns_dir}/resolv.conf"
        )
        self.add_inject(hostname, {
            "src": resolv_path,
            "dst": "/etc/resolv.conf",
            "description": "resolv.conf for DNS server",
        })

        # /etc/dnsmasq.conf
        dns_conf_path = self.render(
            "dnsmasq.conf.mako",
            f"{self.dns_dir}/dnsmasq.conf",
            domain=domain,
            ip=dns_ip,
            interface=dns_iface,
        )
        self.add_inject(hostname, {
            "src": dns_conf_path,
            "dst": "/etc/dnsmasq.conf",
            "description": "dnsmasq configuration for DNS server",
        })

        # /etc/hosts
        hosts_path = self.render(
            "hosts.mako",
            f"{self.dns_dir}/hosts",
            dns_hostname=hostname,
            hosts=hosts,
        )
        self.add_inject(hostname, {
            "src": hosts_path,
            "dst": "/etc/hosts",
            "description": "hosts file for DNS server",
        })


def main():
    DNS()


if __name__ == '__main__':
    main()
