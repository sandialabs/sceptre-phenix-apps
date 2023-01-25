import os, subprocess, sys, time

from datetime import datetime

from phenix_apps.apps.scorch import ComponentBase


class MM(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, 'mm')

        self.execute_stage()


    def configure(self):
        self.__run('configure')


    def start(self):
        self.__run('start')


    def stop(self):
        self.__run('stop')


    def cleanup(self):
        self.__run('cleanup')


    def __run(self, stage):
        mm = self.mm_init()

        commands = self.metadata.get(stage, [])

        for cmd in commands:
            # TODO: ensure bridge capture gets run on each namespace host

            if cmd.type == 'start_capture':
                cap = cmd.get('capture', None)

                if not cap:
                    self.eprint(f'no bridge capture details provided')
                    sys.exit(1)

                bridge = cap.get('bridge', None)

                if not bridge:
                    self.eprint(f'bridge to capture traffic on not provided')
                    sys.exit(1)

                now = datetime.utcnow()
                filename = os.path.basename(cap.get('filename', f'{bridge}-{now:%Y-%m-%dT%H:%M:%SZ}.pcap'))

                if not filename.lower().endswith('.pcap'):
                    filename += '.pcap'

                filter = cap.get('filter', None)

                if filter:
                    mm.capture_pcap_filter(filter)

                snaplen = cap.get('snaplen', None)

                if snaplen:
                    mm.capture_pcap_snaplen(snaplen)

                try:
                    self.print(f'starting pcap capture for bridge {bridge}')
                    mm.mesh_send('all', f'shell mkdir -p {self.base_dir}')
                    mm.capture_pcap_bridge(bridge, os.path.join(self.base_dir, filename))
                    self.print(f'started pcap capture for bridge {bridge}')
                except Exception as ex:
                    self.eprint(f'unable to start pcap capture for bridge {bridge}: {ex}')
                    sys.exit(1)
                finally:
                    mm.capture_pcap_filter(None)
                    mm.capture_pcap_snaplen(None)
            elif cmd.type == 'stop_capture':
                cap = cmd.get('capture', None)

                if not cap:
                    self.eprint(f'no bridge capture details provided')
                    sys.exit(1)

                bridge = cap.get('bridge', None)

                if not bridge:
                    self.eprint(f'bridge to stop capture traffic on not provided')
                    sys.exit(1)
                try:
                    self.print(f'stopping pcap capture on bridge {bridge}')
                    mm.capture_pcap_delete_bridge(bridge)
                    self.print(f'stopped pcap capture on bridge {bridge}')

                    mm.file_get(os.path.relpath(self.root_dir, self.base_dir))

                    if cap.get('convert', False):
                        self.print('Waiting for transfer of pcap files to head node to complete.')

                        # wait for file transfer back to head node to be done
                        while True:
                            time.sleep(2)

                            status = mm.file_status()
                            done   = True

                            for host in status:
                                done &= len(host['Tabular']) == 0

                            if done: break

                        self.print('Transfer of pcap files to head node has completed.')

                        # convert pcap files
                        for f in os.listdir(self.base_dir):
                            if f.endswith('.pcap'):
                                self.print(f'Starting PCAP --> JSON conversion of {f}.')

                                pcap_out = os.path.join(self.base_dir, f)
                                json_out = pcap_out + '.jsonl'

                                subprocess.run(
                                    f"bash -c 'tshark -r {pcap_out} -T ek > {json_out} 2>/dev/null'",
                                    shell=True,
                                )

                                self.print(f'PCAP --> JSON conversion of {f} complete.')
                except Exception as ex:
                    self.eprint(f'unable to stop pcap capture on bridge {bridge}: {ex}')
                    sys.exit(1)

        vms = self.metadata.get('vms', [])

        for vm in vms:
            commands = vm.get(stage, [])

            for cmd in commands:
                if cmd.type == 'start':
                    try:
                        self.print(f'starting VM {vm.hostname}')
                        mm.vm_start(vm.hostname)
                        self.print(f'started VM {vm.hostname}')
                    except Exception as ex:
                        self.eprint(f'unable to start vm {vm.hostname}: {ex}')
                        sys.exit(1)
                elif cmd.type == 'stop':
                    try:
                        self.print(f'stopping VM {vm.hostname}')
                        mm.vm_stop(vm.hostname)
                        self.print(f'stopped VM {vm.hostname}')
                    except Exception as ex:
                        self.eprint(f'unable to stop vm {vm.hostname}: {ex}')
                        sys.exit(1)
                elif cmd.type == 'connect':
                    conn = cmd.get(cmd.type, None)

                    if not conn:
                        self.eprint(f'no connect details provided for vm {vm.hostname}')
                        sys.exit(1)

                    iface = conn.get('interface', None)

                    if iface is None:
                        self.eprint(f'interface to connect not provided for vm {vm.hostname}')
                        sys.exit(1)

                    vlan = conn.get('vlan', None)

                    if not vlan:
                        self.eprint(f'VLAN to connect interface {iface} to not provided for vm {vm.hostname}')
                        sys.exit(1)

                    bridge = conn.get('bridge', None)

                    try:
                        self.print(f'connecting interface {iface} on {vm.hostname} to VLAN {vlan}')
                        mm.vm_net_connect(vm.hostname, iface, vlan, bridge)
                        self.print(f'connected interface {iface} on {vm.hostname} to VLAN {vlan}')
                    except Exception as ex:
                        self.eprint(f'unable to connect interface {iface} on {vm.hostname} to VLAN {vlan}: {ex}')
                        sys.exit(1)
                elif cmd.type == 'disconnect':
                    conn = cmd.get(cmd.type, None)

                    if not conn:
                        self.eprint(f'no disconnect details provided for vm {vm.hostname}')
                        sys.exit(1)

                    iface = conn.get('interface', None)

                    if iface is None:
                        self.eprint(f'interface to disconnect not provided for vm {vm.hostname}')
                        sys.exit(1)

                    try:
                        self.print(f'disconnecting interface {iface} on {vm.hostname}')
                        mm.vm_net_disconnect(vm.hostname, iface)
                        self.print(f'disconnected interface {iface} on {vm.hostname}')
                    except Exception as ex:
                        self.eprint(f'unable to disconnect interface {iface} on {vm.hostname}: {ex}')
                        sys.exit(1)
                elif cmd.type == 'start_capture':
                    cap = cmd.get('capture', None)

                    if not cap:
                        self.eprint(f'no capture details provided for vm {vm.hostname}')
                        sys.exit(1)

                    iface = cap.get('interface', None)

                    if iface is None:
                        self.eprint(f'interface to capture traffic on not provided for vm {vm.hostname}')
                        sys.exit(1)

                    now = datetime.utcnow()
                    filename = os.path.basename(cap.get('filename', f'{vm.hostname}-{iface}-{now:%Y-%m-%dT%H:%M:%SZ}.pcap'))

                    if not filename.lower().endswith('.pcap'):
                        filename += '.pcap'

                    filter = cap.get('filter', None)

                    if filter:
                        mm.capture_pcap_filter(filter)

                    snaplen = cap.get('snaplen', None)

                    if snaplen:
                        mm.capture_pcap_snaplen(snaplen)

                    try:
                        self.print(f'starting pcap capture for interface {iface} on {vm.hostname}')
                        mm.mesh_send('all', f'shell mkdir -p {self.base_dir}')
                        mm.capture_pcap_vm(vm.hostname, iface, os.path.join(self.base_dir, filename))
                        self.print(f'started pcap capture for interface {iface} on {vm.hostname}')
                    except Exception as ex:
                        self.eprint(f'unable to start pcap capture for interface {iface} on {vm.hostname}: {ex}')
                        sys.exit(1)
                    finally:
                        mm.capture_pcap_filter(None)
                        mm.capture_pcap_snaplen(None)
                elif cmd.type == 'stop_capture':
                    cap = cmd.get('capture', None)

                    try:
                        self.print(f'stopping pcap capture(s) on VM {vm.hostname}')
                        mm.capture_pcap_delete_vm(vm.hostname)
                        self.print(f'stopped pcap capture(s) on VM {vm.hostname}')

                        mm.file_get(os.path.relpath(self.root_dir, self.base_dir))

                        if cap and cap.get('convert', False):
                            self.print('Waiting for pcap transfers to head node to complete.')

                            # wait for file transfer back to head node to be done
                            while True:
                                time.sleep(2)

                                status = mm.file_status()
                                done   = True

                                for host in status:
                                    done &= len(host['Tabular']) == 0

                                if done: break

                            # convert pcap files
                            for f in os.listdir(self.base_dir):
                                if f.endswith('.pcap'):
                                    self.print(f'starting PCAP --> JSON conversion of {f}')

                                    pcap_out = os.path.join(self.base_dir, f)
                                    json_out = pcap_out + '.jsonl'

                                    subprocess.run(
                                        f"bash -c 'tshark -r {pcap_out} -T ek > {json_out} 2>/dev/null'",
                                        shell=True,
                                    )

                                    self.print(f'PCAP --> JSON conversion of {f} complete')
                    except Exception as ex:
                        self.eprint(f'unable to stop pcap capture(s) on vm {vm.hostname}: {ex}')
                        sys.exit(1)


def main():
    MM()


if __name__ == '__main__':
    main()
