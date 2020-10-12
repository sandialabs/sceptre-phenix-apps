import pkg_resources, random

from socket import inet_ntoa
from struct import pack

import mako


def mako_render(script_path, **kwargs):
    """Generate a mako template from a file and render it using provided args.

    Args:
        script_path (str): Full path to mako template script.
        kwargs: Arbitrary keyword arguments.

    Returns:
        str: Rendered string from mako template.
    """

    template = mako.template.Template(filename=script_path)

    return template.render(**kwargs)


def mako_serve_template(template_name, templates_dir, filename, **kwargs):
    """Serve Mako template.

    This function is based on Mako-style functionality of searching for the template in
    in the template directory and rendering it.

    Args:
        template_name (str): name of the template.
        filename (str): name of the file.
        kwargs: Arbitrary keyword arguments.
    """

    mylookup   = mako.lookup.TemplateLookup(directories=[templates_dir])
    mytemplate = mylookup.get_template(template_name)

    print(mytemplate.render(**kwargs), file=filename)


def generate_mac_addr():
    """Generates a random MAC address.

    Returns:
        string: The MAC address as a string.
    """

    return ':'.join(map(lambda x: f'{x:02x}', [0x00, 0x16, 0x3E,
                                               random.randint(0x00, 0x7F),
                                               random.randint(0x00, 0xFF),
                                               random.randint(0x00, 0xFF)]))


def validate_mac_addr(macs):
    """Check if MAC address is valid.

    Simple check to see if the MAC looks right.

    Args:
        macs (list): List of MAC addresses in format "xx:xx:xx:xx:xx:xx".

    Returns:
        bool: True if all MACs are valid, otherwise False.
    """

    for mac in macs:
        if len(mac.strip()) != 17 or mac.count(':') != 5:
            return False

    return True


def pkg_path(relative_path):
    """Return package resource path.

    Args:
        relative_path (str): Relative path of resource.

    Returns:
        str: Full path to package resource.
    """

    return pkg_resources.resource_filename('phenix', relative_path)


def cidr_to_netmask(cidr):
    """Convert CIDR notation (24) to a subnet mask (255.255.255.0)
    """

    cidr = int(cidr)
    bits = 0xffffffff ^ (1 << 32 - cidr) - 1

    return inet_ntoa(pack('>I', bits))


def netmask_to_cidr(netmask):
    """Convert netmask (255.255.255.0) to CIDR notation (24)
    """

    return sum([bin(int(x)).count('1') for x in netmask.split('.')])
