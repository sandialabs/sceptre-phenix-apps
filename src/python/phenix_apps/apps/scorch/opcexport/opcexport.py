import json
import os
import time
import sys
from xml.etree import ElementTree as ET

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import logger, utils


class OPCExport(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, 'opcexport')
        self.execute_stage()

    def configure(self):
        logger.log('INFO', f'Configuring user component: {self.name}')

        host = self.metadata['opc_hostname']  # type: str

        # this will copy all files from opcexport into C:/opcexport/
        # Faster and simpler than copying individual files
        # The few unnecessary .py files that get copied don't matter
        self.print(f"Copying opcexport files to '/opcexport' folder on host '{host}'")
        utils.mm_send(self.mm, host, utils.abs_path(__file__), '/opcexport')

        # get opc config file
        self.print("Looking for OPC XML config file")
        opc_config_file = f'{self.exp_dir}/sceptre/{host}/opc.xml'
        try:
            asset_dir = next(app for app in self.experiment.spec.scenario.apps if app['name'] == 'sceptre')['assetDir']
            override_file = f'{asset_dir}/injects/override/{host}_opc.xml'
            if os.path.exists(override_file):
                self.print(f"Using override for OPC variables file from {override_file}")
                opc_config_file = override_file
        except KeyError:
            self.print("WARNING: 'assetDir' not defined for sceptre app or sceptre app not present, skipping the check for a OPC override file")

        # Generate OPC variables JSON from the source config XML
        opc_json = self.create_opc_variables(opc_config_file)

        # Output path for the JSON
        e_dir = os.path.join(self.exp_dir, 'opcexport')
        if not os.path.exists(e_dir):
            os.mkdir(e_dir)
        opc_variables_file = os.path.join(e_dir, 'opc_variables.json')
        self.print(f"Creating opc_variables file: {opc_variables_file}")

        # write variables to json
        with open(opc_variables_file, 'w') as f:
            json.dump(opc_json, f)

        # Use miniccc to inject opc variables file
        self.print(f"Copying opc_variables.json to host '{host}'")
        utils.mm_send(self.mm, host, opc_variables_file, 'opcexport/opc_variables.json')

        # install stuff
        self.print("Running install script install-python-opc.ps1")
        utils.mm_exec_wait(self.mm, host, 'powershell.exe -File C:/opcexport/install-python-opc.ps1')

        # This is a bit of a dirty hack to auto-add the route out of the tap
        elastic_ip = self.metadata.get('elastic_ip', '172.16.0.254')
        if elastic_ip != '172.16.0.254':
            self.print("configuring route")

            tap_ip = ""
            if self.extract_app("tap"):
                tap = self.extract_app("tap").metadata.taps[0]
                tap_ip = tap.ip.split("/")[0]
            elif self.extract_app("mgmt_tap"):
                tap_ip = "172.16.111.1"
            else:
                self.eprint("no tap app defined and a non-default elastic IP, your mileage may vary")

            # determine target network, assume /24 subnet
            target_subnet = '.'.join(elastic_ip.split('.')[:-1]) + '.0'
            if tap_ip:  # only configure if one of the tap apps was found
                self.print(f"Adding route to {target_subnet} via {tap_ip}")
                utils.mm_exec_wait(self.mm, host, f'route add {target_subnet} MASK 255.255.255.0 {tap_ip}')

        # verify elasticsearch server is pingable
        # Unfortunately, Test-Connection on Windows 7 isn't very capable and
        # can't be used to check TCP ports, just ICMP pings.
        self.print(f"checking if elastic server is reachable at {elastic_ip}")
        self.run_and_check_command(host, f'''powershell.exe -Command "Test-Connection -ComputerName {elastic_ip} -Count 1 -Quiet"''', timeout=10.0)
        # TODO: use miniccc connection testing to test TCP 9200
        #   "mm cc test-conn tcp 10.1.2.15 9200 wait 10s"
        #   self.mm.cc_test_conn_wait()
        # elastic_port = self.metadata.get('elastic_port', '9200')
        # self.mm.cc_test_conn_wait("tcp", elastic_ip, elastic_port, "10s")

        logger.log('INFO', f'Configured user component: {self.name}')

    def start(self):
        logger.log('INFO', f'Starting user component: {self.name}')

        host = self.metadata['opc_hostname']  # type: str
        elastic_ip = self.metadata.get('elastic_ip', '172.16.0.254')
        elastic_port = self.metadata.get('elastic_port', '9200')

        # start dirty elastic
        # open in new powershell window so that it will run in background and scorch can return
        self.print(f"Starting scada_to_elastic.py (host={host}, elastic_ip={elastic_ip}, elastic_port={elastic_port})")

        # after python is installed, the PATH variable is updated, but miniccc.exe doesn't pickup the change
        # because the process is still running. Therefore, absolute paths are needed.
        self.mm.cc_filter(f"name={host}")
        self.mm.cc_background_once(f"C:/Progra~1/Python38/python.exe C:/opcexport/scada_to_elastic.py -u opc.tcp://{host}:4840 -f /opcexport/opc_variables.json -e {elastic_ip}:{elastic_port}")
        self.mm.clear_cc_filter()

        # Verify process is still running and didn't error out
        # Hopefully, there are no other python processes running
        # 10 seconds should be enough for OPC and Elastic to time out
        self.print("Waiting 10 seconds then checking if python.exe is still running")
        time.sleep(10.0)
        running = False
        for _ in range(3):
            self.print("Checking if python is running...")
            if self.check_process_running(host, "python.exe", os_type="windows"):
                self.print("Python is running!")
                running = True
                break
            time.sleep(5.0)

        if not running:
            self.eprint("scada_to_elastic.py is not running!")
            sys.exit(1)

        logger.log('INFO', f'Started user component: {self.name}')

    def stop(self):
        logger.log('INFO', f'Stopping user component: {self.name}')

        host = self.metadata['opc_hostname']  # type: str

        # Stop dirty elastic
        # TODO: find a better way to do this that doesn't kill all pythons
        self.print(f"Killing all 'python.exe' processes (host={host})")
        utils.mm_kill_process(self.mm, cc_filter=f"name={host}", process="python.exe", os_type="windows")

        # save log file
        self.print("Collecting log file for scada_to_elastic.py")
        self.recv_file(host, "/opcexport/scada_to_elastic.log")
        self.print("Deleting log file")
        utils.mm_delete_file(self.mm, f"name={host}", "/opcexport/scada_to_elastic.log")

        # TODO: validate that data made it into Elasticsearch

        logger.log('INFO', f'Stopped user component: {self.name}')

    def cleanup(self):
        logger.log('INFO', f'Cleaning up user component: {self.name}')

        host = self.metadata['opc_hostname']  # type: str
        elastic_ip = self.metadata.get('elastic_ip', '172.16.0.254')
        elastic_port = self.metadata.get('elastic_port', '9200')

        # delete data from elastic
        self.print(f"Running delete_scada_to_elastic.py (host={host}, elastic_ip={elastic_ip}, elastic_port={elastic_port})")
        utils.mm_exec_wait(self.mm, host, f"C:/Progra~1/Python38/python.exe C:/opcexport/delete_scada_to_elastic.py -e {elastic_ip}:{elastic_port}")

        logger.log('INFO', f'Cleaned up user component: {self.name}')

    def create_opc_variables(self, opc_config_file: str) -> dict:
        self.print(f"Generating OPC variables from: {opc_config_file}")
        opc_json = {}

        # TODO: support for other OPC servers

        #parse opc xml config file to get channel, device and tag names
        opc_xml_tree = ET.parse(opc_config_file)
        root = opc_xml_tree.getroot()
        for elem in root.iter('{http://www.kepware.com/schemas/servermain}Channel'):
            channel_name = elem.find('{http://www.kepware.com/schemas/servermain}Name').text
            device_list = elem.find('{http://www.kepware.com/schemas/servermain}DeviceList').findall('{http://www.kepware.com/schemas/servermain}Device')
            for device in device_list:
                device_name = device.find('{http://www.kepware.com/schemas/servermain}Name').text
                device_tag_list = []
                tag_list = device.find('{http://www.kepware.com/schemas/servermain}TagList').findall('{http://www.kepware.com/schemas/servermain}Tag')
                for tag in tag_list:
                    tag_name = tag.find('{http://www.kepware.com/schemas/servermain}Name').text
                    device_tag_list.append(f'2:{tag_name}')
                opc_json[f'2:{channel_name}.{device_name}'] = device_tag_list

        return opc_json


def main():
    OPCExport()


if __name__ == '__main__':
    main()
