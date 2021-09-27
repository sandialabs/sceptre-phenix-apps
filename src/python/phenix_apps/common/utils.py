import datetime, math, os, pathlib, random, re, shutil, tempfile, time

from socket import inet_ntoa
from struct import pack

import phenix_apps.common.settings as s

import mako.lookup, mako.template


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


def abs_path(file_, relative_path=None):

    """Return absolute path to file_ with optional relative resource.

    Args:
        file_ (str): Name of file.
        relative_path (str): Optional relative path of resource.

    Returns:
        str: Full path to file_ (and optional relative resource).
    """

    base_path = pathlib.Path(file_).parent.absolute()
    return f"{base_path}/{relative_path}" if relative_path else base_path


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


def hms_to_timedelta(uptime):
    """Convert XXhXXmXXs string to a time delta.

    Args:
        uptime (str): string delta time in hms format.

    Returns:
        str: time delta as a pretty string.
    """
    timedelta = None
    if 'ms' in uptime:
        temp = uptime.split('ms')
        ms = math.floor(float(temp[0]))
        timedelta = datetime.timedelta(milliseconds=ms)
    elif 'h' in uptime:
        temp = uptime.split('h')
        hrs = int(temp[0])
        temp = temp[1].split('m')
        minutes = int(temp[0])
        temp = temp[1].split('s')
        sec = math.floor(float(temp[0]))
        timedelta = datetime.timedelta(hours=hrs, minutes=minutes, seconds=sec)
    elif 'm' in uptime:
        temp = uptime.split('m')
        minutes = int(temp[0])
        temp = temp[1].split('s')
        sec = math.floor(float(temp[0]))
        timedelta = datetime.timedelta(minutes=minutes, seconds=sec)
    elif 's' in uptime:
        temp = uptime.split('s')
        sec = math.floor(float(temp[0]))
        timedelta = datetime.timedelta(seconds=sec)
    return str(timedelta)


SECONDS_PER_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

def convert_to_seconds(time):
    """Convert time string to seconds (e.g. 30s, 24h).
    
    Args:
        time (str): time string.

    Returns:
        str: time in seconds.
    """
    return str(int(time[:-1]) * SECONDS_PER_UNIT[time[-1]])


def expand_shorthand(short):
    """Expand shorthand naming notation.

    An example would be foo[1-3] = [foo1, foo2, foo3]

    Args:
        short (str): shorthand notation.

    Returns:
        array: expanded names.
    """

    match = re.match(r"(.+)\[(\d+)\-(\d+)\]", short)

    if match:
        expanded = []

        base  = match.group(1)
        start = int(match.group(2))
        end   = int(match.group(3)) + 1

        for i in range(start, end):
            expanded.append(f'{base}{i}')

        return expanded

    return [short]


def mm_send(mm, vm, src, dst):
    # Use PHENIX_DIR as base directory to ensure minimega has access to it. This
    # assumes PHENIX_DIR is mounted into the containers if containers are being
    # used.
    with tempfile.TemporaryDirectory(dir=s.PHENIX_DIR) as tmp:
        vm_dst  = os.path.join(tmp, dst.strip('/'))
        dst_dir = os.path.dirname(vm_dst)

        try:
            mm.cc_mount(vm, tmp)

            if not os.path.exists(dst_dir):
                os.makedirs(dst_dir)

            if os.path.isdir(src):
                shutil.copytree(src, vm_dst)
            else:
                shutil.copyfile(src, vm_dst)
        finally:
            mm.clear_cc_mount(vm)


def mm_recv(mm, vm, src, dst):
    # Use PHENIX_DIR as base directory to ensure minimega has access to it. This
    # assumes PHENIX_DIR is mounted into the containers if containers are being
    # used.
    with tempfile.TemporaryDirectory(dir=s.PHENIX_DIR) as tmp:
        vm_src  = os.path.join(tmp, src.strip('/'))
        dst_dir = os.path.dirname(dst)

        if not os.path.exists(dst_dir):
            os.makedirs(dst_dir)

        try:
            mm.cc_mount(vm, tmp)

            tries = 0
            while not os.path.exists(vm_src):
                tries += 1

                if tries >= 5:
                    # finally block will still get called
                    raise ValueError(f'{src} not found in VM {vm}')
                else:
                    time.sleep(0.5)

            if os.path.isdir(vm_src):
                shutil.copytree(vm_src, dst)
            else:
                shutil.copyfile(vm_src, dst)
        finally:
            mm.clear_cc_mount(vm)


def mm_exec_wait(mm, vm, cmd):
    mm.cc_filter(f'name={vm}')
    mm.cc_exec(cmd)

    commands = mm.cc_commands()
    last_cmd_id = commands[0]['Tabular'][-1][0]

    mm_wait_for_cmd(mm, last_cmd_id)


def mm_wait_for_cmd(mm, id):
    last_test = lambda c: c[0] == id
    done_test = lambda c: c[3] == '1'

    waiting = True

    while waiting:
        time.sleep(1)

        commands = mm.cc_commands()

        for host in commands:
            last = list(filter(last_test, host['Tabular']))
            done = list(filter(done_test, last))

            if len(done) > 0:
                waiting = False
                break
