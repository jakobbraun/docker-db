#! /usr/bin/env python3

import re, base64, string, random, os, subprocess, time, shutil, hashlib, uuid, crypt, tempfile
from subprocess import Popen, PIPE
from typing import Optional
from types import ModuleType

# pwd is only available on UNIX systems
try:
    import pwd, grp
except ImportError:
    import getpass

# Valid prefixes for encoded /etc/shadow passwords    
shadow_prefixes = ['$1$', '$2a$', '$2y$', '$5$', '$6$']
 
class atomic_file_writer(object): #{{{
    def __init__(self, path, mode = 0o644, uid = None, gid = None):
        self._path = os.path.abspath(path)
        self._is_duplicate = False
        self._temp = tempfile.NamedTemporaryFile(mode = 'w',
                                                 prefix = '.%s.' % os.path.basename(self._path),
                                                 dir = os.path.dirname(self._path),
                                                 delete = False)
        os.fchmod(self._temp.fileno(), mode)
        if uid is None: uid = os.getuid()
        if gid is None: gid = os.getgid()
        os.fchown(self._temp.fileno(), uid, gid)

    def __getattr__(self, name):
        return getattr(self._temp, name)

    def close(self):
        self._temp.close()
        self._is_duplicate = False
        if os.path.exists(self._path):
            prev_cont = open(self._path).read()
            new_cont = open(self._temp.name).read()
            if prev_cont == new_cont:
                self._is_duplicate = True
        if not self._is_duplicate:
            os.rename(self._temp.name, self._path)
        else: os.unlink(self._temp.name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def ignored(self):
        return self._is_duplicate    
# }}}

def read_exaconf(filename, ro = False, initialized = False): #{{{
    """
    Checks and reads the given EXAConf file.
    """
    try:
        from EXAConf import EXAConf, EXAConfError
        EXAConf, EXAConfError #silence pyflakes
    except ImportError:
        from libconfd.EXAConf import EXAConf, EXAConfError

    if not os.path.exists(filename):
        raise EXAConfError("EXAConf file '%s' does not exist!" % filename)
    if ro and not os.access(filename, os.R_OK):
        raise EXAConfError("EXAConf file '%s' is not readable by the current user!" % filename)
    if not ro and not os.access(filename, os.W_OK):
        raise EXAConfError("EXAConf file '%s' is not writable by the current user!" % filename)
    exaconf = EXAConf(os.path.dirname(filename), False, filename=os.path.basename(filename))
    if initialized and not exaconf.initialized():
        raise EXAConfError("EXAConf in '%s' is not inizalized!" % filename)
    return exaconf
#}}}
 
def units2bytes(data): #{{{
    ma_units = units2bytes.re_parse.match(str(data))
    if not ma_units: raise RuntimeError('Could not parse %s as number with units.' % repr(data))
    num1, num2, unit, two = ma_units.groups()
    num1 = num1.strip().replace(' ', '')
    if unit is not None: unit = unit.lower()
    if num2 is None: num = int(num1)
    else: num = float("%s.%s" % (num1, num2.strip()))
    if two is None:
        return num * units2bytes.convd[unit]
    return num * units2bytes.convb[unit]
# There's no good way to annotate these right now. See https://github.com/python/mypy/issues/2087
units2bytes.re_parse = re.compile(r'^\s*([0-9]+)(?:[.]([0-9]+))?\s*(?:([KkMmGgTtPpEeZzYy])(i)?)?[Bb]?\s*$')  # type: ignore[attr-defined]
units2bytes.convf = lambda x: {'k': x ** 1, 'm': x ** 2, 'g': x ** 3, 't': x ** 4, 'p': x ** 5, 'e': x ** 6, 'z': x ** 7, 'y': x ** 8, None: 1}  # type: ignore[attr-defined]
units2bytes.convd = units2bytes.convf(1000)  # type: ignore[attr-defined]
units2bytes.convb = units2bytes.convf(1024)  # type: ignore[attr-defined]
#}}}

def bytes2units(num): #{{{
    num = float(num)
    for x in ('B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB', 'ZiB', 'YiB'):
        if num < 1024.0:
            return "%s %s" % (("%3.4f" % num).rstrip('0').rstrip('.'), x)
        num /= 1024.0
    return "%s YiB" % ("%-3.8f" % num).rstrip('0').rstrip('.')
#}}}
 
# {{{ str_to_seconds
seconds_in_minute = 60
seconds_in_hour = seconds_in_minute * 60
seconds_in_day = seconds_in_hour * 24
seconds_in_week = seconds_in_day * 7
def str2sec(data):
    if data == None:
        return 0
    # check if it's already an integer
    try:
        seconds = int(data)
        return seconds
    except ValueError:
        pass
    # convert if not
    seconds = 0
    ma_weeks = re.match(r'^(([0-9]+)w\s*)', data)
    if ma_weeks:
        seconds += int(ma_weeks.group(2)) * seconds_in_week
        data = data[len(ma_weeks.group(1)):]
    ma_days = re.match(r'^(([0-9]+)d\s*)', data)
    if ma_days:
        seconds += int(ma_days.group(2)) * seconds_in_day
        data = data[len(ma_days.group(1)):]
    ma_hours = re.match(r'^(([0-9]+)h\s*)', data)
    if ma_hours:
        seconds += int(ma_hours.group(2)) * seconds_in_hour
        data = data[len(ma_hours.group(1)):]
    ma_minutes = re.match(r'^(([0-9]+)m\s*)', data)
    if ma_minutes:
        seconds += int(ma_minutes.group(2)) * seconds_in_minute
        data = data[len(ma_minutes.group(1)):]
    ma_seconds = re.match(r'^(([0-9]+)s\s*)', data)
    if ma_seconds:
        seconds += int(ma_seconds.group(2))
        data = data[len(ma_seconds.group(1)):]
    if len(data) > 0:
        try: seconds += int(data); data = ''
        except: pass
    if len(data) != 0:
        raise Exception('Date time format must be: <num>w <num>d <num>h <num>m <num>s')
    return seconds
# }}}

def sec2str(seconds): # {{{
     seconds = int(seconds)
     weeks   = seconds // seconds_in_week   ; seconds = seconds % seconds_in_week
     days    = seconds // seconds_in_day    ; seconds = seconds % seconds_in_day
     hours   = seconds // seconds_in_hour   ; seconds = seconds % seconds_in_hour
     minutes = seconds // seconds_in_minute ; seconds = seconds % seconds_in_minute
     data = []
     if weeks   > 0: data.append("%dw" % weeks)
     if days    > 0: data.append("%dd" % days)
     if hours   > 0: data.append("%dh" % hours)
     if minutes > 0: data.append("%dm" % minutes)
     if seconds > 0: data.append("%ds" % seconds)
     if len(data) == 0: return "0s"
     return " ".join(data)
# }}}

def gen_passwd(length): #{{{
    """
    Generates a new password with given length.
    """
    key = ''.join(random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(length))
    return key
#}}}
 
def gen_base64_passwd(length):#{{{
    """
    Generates a base64 encoded password with given length.
    """
    return base64.b64encode(gen_passwd(length).encode()).decode()
#}}}

def get_euid(): #{{{
    """
    Returns the effective user ID on UNIX systems and a default value on Windows.
    """
    if "geteuid" in dir(os):
        return os.geteuid()
    else:
        return 500
#}}}
 
def get_egid(): #{{{
    """
    Returns the effective group ID on UNIX systems and a default value on Windows.
    """
    if "getegid" in dir(os):
        return os.getegid()
    else:
        return 500
#}}}

def get_username(): #{{{
    """
    Returns the (effective) username on UNIX and Windows.
    """
    if "geteuid" in dir(os):
        return pwd.getpwuid(os.geteuid()).pw_name
    else:
        return getpass.getuser()

#}}}

def to_uid(uname): #{{{
    """
    Returns the user ID of the given username. If it's already an ID, it either returns it directly 
    or converts it to an int if it's a string.
    """
    uid = None
    # is it a string?
    if isinstance(uname, str):
        # does the string contain a UID?
        # YES -> convert to int
        try:
            uid = int(uname)
        # NO -> convert to UID
        except ValueError:
            uid = pwd.getpwnam(uname).pw_uid
    # NO -> it's already a valid uid, do nothing
    else:
        uid = uname
    return uid
#}}}
 
def to_uname(uid): #{{{
    """
    Returns the username of the given user ID. ID can be an int or a string. If ID is already a username, returns it unmodified.
    """
    uname = None
    # is it a string?
    if isinstance(uid, str):
        # does the string contain a UID?
        # YES -> convert to int and then to username
        try:
            uid = int(uid)
            uname = pwd.getpwuid(uid).pw_name
        # NO -> it's already a valid username, do nothing
        except ValueError:
            uname = uid
    # NO -> convert uid to username
    else:
        uname = pwd.getpwuid(uid).pw_name
    return uname
#}}}
 
def to_gid(gname): #{{{
    """
    Returns the group ID of the given groupname. If it's already an ID, it either returns it directly 
    or converts it to an int if it's a string.
    """
    gid = None
    # is it a string?
    if isinstance(gname, str):
        # does the string contain a gid?
        # YES -> convert to int
        try:
            gid = int(gname)
        # NO -> convert to UID
        except ValueError:
            gid = grp.getgrnam(gname).gr_gid
    # NO -> it's already a valid gid, do nothing
    else:
        gid = gname
    return gid
#}}}
  
def to_gname(gid): #{{{
    """
    Returns the groupname of the given group ID. ID can be an int or a string. If ID is already a groupname, returns it unmodified.
    """
    gname = None
    # is it a string?
    if isinstance(gid, str):
        # does the string contain a gig?
        # YES -> convert to int and then to groupname
        try:
            gid = int(gid)
            gname = grp.getgrgid(gid).gr_name
        # NO -> it's already a valid groupname, do nothing
        except ValueError:
            gname = gid
    # NO -> convert gid to groupname
    else:
        gname = grp.getgrgid(gid).gr_name
    return gname
#}}}
 
def get_user_gnames(user): #{{{
    """
    Returns a list of all local group names that the given user belongs to (primary group is first element).
    'user' may be a name or an ID.
    """
    uname = to_uname(user)
    gnames = [ g.gr_name for g in grp.getgrall() if uname in g.gr_mem ]
    #insert primary group (in front)
    gid = pwd.getpwnam(uname).pw_gid  
    gnames.insert(0, grp.getgrgid(gid).gr_name)
    return gnames
#}}}
  
def get_user_gids(user): #{{{
    """
    Returns a list of all local group IDs that the given user belongs to (primary group is first element).
    'user' may be a name or an ID.
    """
    uname = to_uname(user)
    gids = [ g.gr_gid for g in grp.getgrall() if uname in g.gr_mem ]
    #insert primary group (in front)
    gids.insert(0, pwd.getpwnam(uname).pw_gid)
    return gids
#}}}
 
def get_first_interface(timeout=1): #{{{
    """
    Returns the name and network address of the first interface that is in state UP. 
    Retries until an interface is found or the given time (in seconds) has elapsed.
    """
    iface = 'N/A'
    address = 'N/A'
    found_if_up = False
    time_elapsed = 0
    while found_if_up == False and time_elapsed < timeout:       
        output = subprocess.check_output(['/usr/bin/env', 'ip', 'addr'], encoding='utf-8')
        for line in output.splitlines():
            line = line.strip()
            # found an interface that is UP
            if 'state UP' in line:
                found_if_up = True
                iface = line.split(':')[1].strip()
            # get its inet address (usually 3 lines down)
            if 'inet' in line and found_if_up == True:
                address = line.split(' ')[1].strip()
                return (iface, address)
        # no interface is UP yet
        time.sleep(1)
        time_elapsed += 1
#}}}

def get_all_interfaces(timeout=1, up_only=True): #{{{
    """
    Returns a list of tuples of all interfaces in state UP (if 'up_only' is True).
    Retries until at least one interface is found or the given time (in seconds) has elapsed.
    """

    interfaces = []
    valid_if = False
    time_elapsed = 0
    while len(interfaces) == 0 and time_elapsed < timeout:
        iface = 'N/A'
        address = 'N/A'
        state = 'N/A'
        output = subprocess.check_output(['/usr/bin/env', 'ip', 'addr'], encoding='utf-8')
        for line in output.splitlines():
            line = line.strip()
            # found a new interface 
            # -> reset local values until iface has been checked
            if 'state' in line:
                valid_if = False
                state = 'N/A'
                iface = 'N/A'
            # check state and remember iface name
            if 'state UP' in line:
                valid_if = True
                state = 'UP'
                iface = line.split(':')[1].strip()
            elif up_only is False and 'state DOWN' in line:
                valid_if = True
                state = 'DOWN'
                iface = line.split(':')[1].strip()
            # extract and remember inet address 
            # --> each interface can have multiple addresses
            if 'inet' in line and valid_if is True:
                address = line.split(' ')[1].strip()   
                interfaces.append((iface, address, state))
                address = 'N/A'
        # no interface found yet
        if len(interfaces) == 0:
            time.sleep(1)
            time_elapsed += 1             

    return interfaces
#}}}
 
def rotate_file(current, max_copies): #{{{
    previous = current + r'.%d'
    for fnum in range(max_copies - 1, -1, -1):
        if os.path.exists(previous % fnum):
            try:
                os.rename(previous % fnum, previous % (fnum + 1))
                # Windows-workaround if "previous" exists
            except OSError:
                os.remove(previous % (fnum + 1))
                os.rename(previous % fnum, previous % (fnum + 1))
    if os.path.exists(current):
        shutil.copy(current, previous % 0)
#}}}

def md5(filename): #{{{
    """
    Returns the MD5 sum of the given file.
    """

    md5sum = hashlib.md5()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b''):
            md5sum.update(chunk)
    return md5sum.hexdigest()
#}}}

def gen_node_uuid(): #{{{
    """
    Generates a UUID for EXASOL cluster nodes (40 chars long). 
    """
    return (uuid.uuid4().hex + uuid.uuid4().hex)[:40].upper()
#}}}

def encode_shadow_passwd(passwd): #{{{
    """
    Encodes the given passwd into an /etc/shadow compatible SHA512 hash.
    """
    return crypt.crypt(passwd, "$6$"+base64.b64encode(os.urandom(16)).decode()+"$")
#}}}

def is_shadow_encoded(passwd): #{{{
    """
    Checks if the given password is encoded in an '/etc/shadow' compatible format 
    (by comparing the prefixes to known supported types).
    """
    for p in shadow_prefixes:
        if passwd.startswith(p):
            return True
    return False
#}}}

# {{{ utility to convert a string to seconds, currently support till weeks
# it's easy to scale on demand; basically it gets numbers from different scale strings like 'w',
# 'd', etc and the multiplies as 2 one-dimension matrixs (vectors)
# using constaints here to make it quicker
TimeScaleSeconds = [7 * 24 * 60 * 60, 24 * 60 * 60, 60 * 60, 60, 1]

TimeScaleChars = ['w', 'd', 'h', 'm', 's']

class TimeScale(object): #{{{
    WEEK = 0
    DAY = 1
    HOUR = 2
    MINUTE = 3
    SECOND = 4
    NUM = 5
# }}}

def string_to_seconds (data): #{{{
    """
    @data, Date time format is: <num>w <num>d <num>h <num>m <num>s
        or <num> only in seconds
    @return, seconds for the input string or -1 if the string is invalid
    """
    intervals = [0] * TimeScale.NUM
    for s in range (TimeScale.NUM):
        regex_str = r'^(([0-9]+)%s\s*)' % TimeScaleChars[s]
        ma_scale = re.match(regex_str, data)
        if ma_scale:
            intervals[s] = int (ma_scale.group (2))
            data = data[len (ma_scale.group(1)):]
    if len (data) > 0:
        try:
            intervals[TimeScale.SECOND] = int (data)
            data = ''
        except:
            pass
    seconds = 0
    for idx, val in enumerate (TimeScaleSeconds):
        seconds = seconds + val * intervals[idx]
    return seconds if len (data) == 0 else -1
# }}}

def timed_run(cmd, timeout = 60): #{{{
    """
    @arguments:
        @cmd, a list which includes commands and their arguments
        @timeout, timeout value for commands to be run
    @return, (return_code, streamed_data)
        @return_code, if it's a standard command, 0 means success; otherwise, self explained
        @streamed_data, streamed output for both stdout and stderr, a list
    """
    p = Popen(cmd, stdout = PIPE, stderr = PIPE)
    start_time = time.monotonic()
    while (time.monotonic() - start_time) < timeout:
        if p.poll() is not None:
            x = tuple([s.decode() for s in p.communicate()])
            return (p.returncode, x)
        else:
            time.sleep(0.1)
    try:
        p.kill ()
    except:
        pass
    return (-1, None)
# }}}
#}}}

