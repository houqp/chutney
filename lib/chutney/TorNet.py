#!/usr/bin/python
#
# Copyright 2011 Nick Mathewson, Michael Stone
# Copyright 2013 The Tor Project
#
#  You may do anything with this work that copyright law would normally
#  restrict, so long as you retain the above notice(s) and this license
#  in all redistributed copies and derived works.  There is no warranty.

from __future__ import with_statement

# Get verbose tracebacks, so we can diagnose better.
import cgitb
cgitb.enable(format="plain")

import os
import signal
import subprocess
import sys
import re
import errno
import time

import chutney.Templating
import chutney.Traffic

def mkdir_p(d, mode=0777):
    """Create directory 'd' and all of its parents as needed.  Unlike
       os.makedirs, does not give an error if d already exists.
    """
    try:
        os.makedirs(d,mode=mode)
    except OSError, e:
        if e.errno == errno.EEXIST:
            return
        raise

class Node(object):
    """A Node represents a Tor node or a set of Tor nodes.  It's created
       in a network configuration file.

       This class is responsible for holding the user's selected node
       configuration, and figuring out how the node needs to be
       configured and launched.
    """
    ## Fields:
    # _parent
    # _env
    # _builder
    # _controller

    ########
    # Users are expected to call these:
    def __init__(self, parent=None, **kwargs):
        self._parent = parent
        self._env = self._createEnviron(parent, kwargs)
        self._builder = None
        self._controller = None

    def getN(self, N):
        return [ Node(self) for _ in xrange(N) ]

    def specialize(self, **kwargs):
        return Node(parent=self, **kwargs)

    ######
    # Chutney uses these:

    def getBuilder(self):
        """Return a NodeBuilder instance to set up this node (that is, to
           write all the files that need to be in place so that this
           node can be run by a NodeController).
        """
        if self._builder is None:
            self._builder = LocalNodeBuilder(self._env)
        return self._builder

    def getController(self):
        """Return a NodeController instance to control this node (that is,
           to start it, stop it, see if it's running, etc.)
        """
        if self._controller is None:
            self._controller = LocalNodeController(self._env)
        return self._controller

    def setNodenum(self, num):
        """Assign a value to the 'nodenum' element of this node.  Each node
           in a network gets its own nodenum.
        """
        self._env['nodenum'] = num

    #####
    # These are internal:

    def _createEnviron(self, parent, argdict):
        """Return an Environ that delegates to the parent node's Environ (if
           there is a parent node), or to the default environment.
        """
        if parent:
            parentenv = parent._env
        else:
            parentenv = self._getDefaultEnviron()
        return TorEnviron(parentenv, **argdict)

    def _getDefaultEnviron(self):
        """Return the default environment.  Any variables that we can't find
           set for any particular node, we look for here.
        """
        return _BASE_ENVIRON

class _NodeCommon(object):
    """Internal helper class for functionality shared by some NodeBuilders
       and some NodeControllers."""
    # XXXX maybe this should turn into a mixin.
    def __init__(self, env):
        self._env = env

    def expand(self, pat, includePath=(".",)):
        return chutney.Templating.Template(pat, includePath).format(self._env)

    def _getTorrcFname(self):
        """Return the name of the file where we'll be writing torrc"""
        return self.expand("${torrc_fname}")

class NodeBuilder(_NodeCommon):
    """Abstract base class.  A NodeBuilder is responsible for doing all the
       one-time prep needed to set up a node in a network.
    """
    def __init__(self, env):
        _NodeCommon.__init__(self, env)

    def checkConfig(self, net):
        """Try to format our torrc; raise an exception if we can't.
        """

    def preConfig(self, net):
        """Called on all nodes before any nodes configure: generates keys as
           needed.
        """

    def config(self, net):
        """Called to configure a node: creates a torrc file for it."""

    def postConfig(self, net):
        """Called on each nodes after all nodes configure."""


class NodeController(_NodeCommon):
    """Abstract base class.  A NodeController is responsible for running a
       node on the network.
    """
    def __init__(self, env):
        _NodeCommon.__init__(self, env)

    def check(self, listRunning=True, listNonRunning=False):
        """See if this node is running, stopped, or crashed.  If it's running
           and listRunning is set, print a short statement.  If it's
           stopped and listNonRunning is set, then print a short statement.
           If it's crashed, print a statement.  Return True if the
           node is running, false otherwise.
        """

    def start(self):
        """Try to start this node; return True if we succeeded or it was
           already running, False if we failed."""

    def stop(self, sig=signal.SIGINT):
        """Try to stop this node by sending it the signal 'sig'."""

class LocalNodeBuilder(NodeBuilder):

    ## Environment members used:
    # torrc -- which torrc file to use
    # torrc_template_path -- path to search for torrc files and include files
    # authority -- bool -- are we an authority?
    # bridgeauthority -- bool -- are we a bridge authority?
    # relay -- bool -- are we a relay?
    # bridge -- bool -- are we a bridge?
    # nodenum -- int -- set by chutney -- which unique node index is this?
    # dir -- path -- set by chutney -- data directory for this tor
    # tor_gencert -- path to tor_gencert binary
    # tor -- path to tor binary
    # auth_cert_lifetime -- lifetime of authority certs, in months.
    # ip -- IP to listen on (used only if authority or bridge)
    # ipv6_addr -- IPv6 address to listen on (used only if ipv6 bridge)
    # orport, dirport -- (used only if authority)
    # fingerprint -- used only if authority
    # dirserver_flags -- used only if authority
    # nick -- nickname of this router

    ## Environment members set
    # fingerprint -- hex router key fingerprint
    # nodenum -- int -- set by chutney -- which unique node index is this?

    def __init__(self, env):
        NodeBuilder.__init__(self, env)
        self._env = env

    def _createTorrcFile(self, checkOnly=False):
        """Write the torrc file for this node.  If checkOnly, just make sure
           that the formatting is indeed possible.
        """
        fn_out = self._getTorrcFname()
        torrc_template = self._getTorrcTemplate()
        output = torrc_template.format(self._env)
        if checkOnly:
            # XXXX Is it time-cosuming to format? If so, cache here.
            return
        with open(fn_out, 'w') as f:
            f.write(output)

    def _getTorrcTemplate(self):
        """Return the template used to write the torrc for this node."""
        template_path = self._env['torrc_template_path']
        return chutney.Templating.Template("$${include:$torrc}",
            includePath=template_path)

    def _getFreeVars(self):
        """Return a set of the free variables in the torrc template for this
           node.
        """
        template = self._getTorrcTemplate()
        return template.freevars(self._env)

    def checkConfig(self, net):
        """Try to format our torrc; raise an exception if we can't.
        """
        self._createTorrcFile(checkOnly=True)

    def preConfig(self, net):
        """Called on all nodes before any nodes configure: generates keys as
           needed.
        """
        self._makeDataDir()
        if self._env['authority']:
            self._genAuthorityKey()
        if self._env['relay']:
            self._genRouterKey()

    def config(self, net):
        """Called to configure a node: creates a torrc file for it."""
        self._createTorrcFile()
        #self._createScripts()

    def postConfig(self, net):
        """Called on each nodes after all nodes configure."""
        #self.net.addNode(self)
        pass

    def _makeDataDir(self):
        """Create the data directory (with keys subdirectory) for this node.
        """
        datadir = self._env['dir']
        mkdir_p(os.path.join(datadir, 'keys'))

    def _genAuthorityKey(self):
        """Generate an authority identity and signing key for this authority,
           if they do not already exist."""
        datadir = self._env['dir']
        tor_gencert = self._env['tor_gencert']
        lifetime = self._env['auth_cert_lifetime']
        idfile   = os.path.join(datadir,'keys',"authority_identity_key")
        skfile   = os.path.join(datadir,'keys',"authority_signing_key")
        certfile = os.path.join(datadir,'keys',"authority_certificate")
        addr = self.expand("${ip}:${dirport}")
        passphrase = self._env['auth_passphrase']
        if all(os.path.exists(f) for f in [idfile, skfile, certfile]):
            return
        cmdline = [
            tor_gencert,
            '--create-identity-key',
            '--passphrase-fd', '0',
            '-i', idfile,
            '-s', skfile,
            '-c', certfile,
            '-m', str(lifetime),
            '-a', addr]
        print "Creating identity key %s for %s with %s"%(
            idfile,self._env['nick']," ".join(cmdline))
        p = subprocess.Popen(cmdline, stdin=subprocess.PIPE)
        p.communicate(passphrase+"\n")
        assert p.returncode == 0 #XXXX BAD!

    def _genRouterKey(self):
        """Generate an identity key for this router, unless we already have,
           and set up the 'fingerprint' entry in the Environ.
        """
        datadir = self._env['dir']
        tor = self._env['tor']
        idfile = os.path.join(datadir,'keys',"identity_key")
        cmdline = [
            tor,
            "--quiet",
            "--list-fingerprint",
            "--orport", "1",
            "--dirserver",
                 "xyzzy 127.0.0.1:1 ffffffffffffffffffffffffffffffffffffffff",
            "--datadirectory", datadir ]
        p = subprocess.Popen(cmdline, stdout=subprocess.PIPE)
        stdout, stderr = p.communicate()
        fingerprint = "".join(stdout.split()[1:])
        assert re.match(r'^[A-F0-9]{40}$', fingerprint)
        self._env['fingerprint'] = fingerprint

    def _getAltAuthLines(self, hasbridgeauth=False):
        """Return a combination of AlternateDirAuthority,
        AlternateHSAuthority and AlternateBridgeAuthority lines for
        this Node, appropriately.  Non-authorities return ""."""
        if not self._env['authority']:
            return ""

        datadir = self._env['dir']
        certfile = os.path.join(datadir,'keys',"authority_certificate")
        v3id = None
        with open(certfile, 'r') as f:
            for line in f:
                if line.startswith("fingerprint"):
                    v3id = line.split()[1].strip()
                    break

        assert v3id is not None

        if self._env['bridgeauthority']:
            # Bridge authorities return AlternateBridgeAuthority with
            # the 'bridge' flag set.
            options = ("AlternateBridgeAuthority",)
            self._env['dirserver_flags'] += " bridge"
        else:
            # Directory authorities return AlternateDirAuthority with
            # the 'hs' and 'v3ident' flags set.
            # XXXX This next line is needed for 'bridges' but breaks
            # 'basic'
            if hasbridgeauth:
                options = ("AlternateDirAuthority",)
	    else:
                options = ("DirAuthority",)
            self._env['dirserver_flags'] += " hs v3ident=%s" % v3id

        authlines = ""
        for authopt in options:
            authlines += "%s %s orport=%s %s %s:%s %s\n" %(
                authopt, self._env['nick'], self._env['orport'],
                self._env['dirserver_flags'], self._env['ip'],
                self._env['dirport'], self._env['fingerprint'])
        return authlines

    def _getBridgeLines(self):
        """Return potential Bridge line for this Node. Non-bridge
        relays return "".
        """
        if not self._env['bridge']:
            return ""

        bridgelines = "Bridge %s:%s\n" % (self._env['ip'],
                                          self._env['orport'])
        if self._env['ipv6_addr'] is not None:
            bridgelines += "Bridge %s:%s\n" % (self._env['ipv6_addr'],
                                               self._env['orport'])
        return bridgelines

class LocalNodeController(NodeController):
    def __init__(self, env):
        NodeController.__init__(self, env)
        self._env = env

    def getPid(self):
        """Assuming that this node has its pidfile in ${dir}/pid, return
           the pid of the running process, or None if there is no pid in the
           file.
        """
        pidfile = os.path.join(self._env['dir'], 'pid')
        if not os.path.exists(pidfile):
            return None

        with open(pidfile, 'r') as f:
            return int(f.read())

    def isRunning(self, pid=None):
        """Return true iff this node is running.  (If 'pid' is provided, we
           assume that the pid provided is the one of this node.  Otherwise
           we call getPid().
        """
        if pid is None:
            pid = self.getPid()
        if pid is None:
            return False

        try:
            os.kill(pid, 0) # "kill 0" == "are you there?"
        except OSError, e:
            if e.errno == errno.ESRCH:
                return False
            raise

        # okay, so the process exists.  Say "True" for now.
        # XXXX check if this is really tor!
        return True

    def check(self, listRunning=True, listNonRunning=False):
        """See if this node is running, stopped, or crashed.  If it's running
           and listRunning is set, print a short statement.  If it's
           stopped and listNonRunning is set, then print a short statement.
           If it's crashed, print a statement.  Return True if the
           node is running, false otherwise.
        """
        # XXX Split this into "check" and "print" parts.
        pid = self.getPid()
        running = self.isRunning(pid)
        nick = self._env['nick']
        dir = self._env['dir']
        print "+++ " + self._env['fingerprint']
        if running:
            if listRunning:
                print "%s is running with PID %s"%(nick,pid)
            return True
        elif os.path.exists(os.path.join(dir, "core.%s"%pid)):
            if listNonRunning:
                print "%s seems to have crashed, and left core file core.%s"%(
                   nick,pid)
            return False
        else:
            if listNonRunning:
                print "%s is stopped"%nick
            return False

    def hup(self):
        """Send a SIGHUP to this node, if it's running."""
        pid = self.getPid()
        running = self.isRunning()
        nick = self._env['nick']
        if self.isRunning():
            print "Sending sighup to %s"%nick
            os.kill(pid, signal.SIGHUP)
            return True
        else:
            print "%s is not running"%nick
            return False

    def start(self):
        """Try to start this node; return True if we succeeded or it was
           already running, False if we failed."""

        if self.isRunning():
            print "%s is already running"%self._env['nick']
            return True
        torrc = self._getTorrcFname()
        cmdline = [
            self._env['tor'],
            "--quiet",
            "-f", torrc,
            ]
        p = subprocess.Popen(cmdline)
        # XXXX this requires that RunAsDaemon is set.
        p.wait()
        if p.returncode != 0:
            print "Couldn't launch %s (%s): %s"%(self._env['nick'],
                                                 " ".join(cmdline),
                                                 p.returncode)
            return False
        return True

    def stop(self, sig=signal.SIGINT):
        """Try to stop this node by sending it the signal 'sig'."""
        pid = self.getPid()
        if not self.isRunning(pid):
            print "%s is not running"%self._env['nick']
            return
        os.kill(pid, sig)




DEFAULTS = {
    'authority' : False,
    'bridgeauthority' : False,
    'hasbridgeauth' : False,
    'relay' : False,
    'bridge' : False,
    'connlimit' : 60,
    'net_base_dir' : 'net',
    'tor' : 'tor',
    'auth_cert_lifetime' : 12,
    'ip' : '127.0.0.1',
    'ipv6_addr' : None,
    'dirserver_flags' : 'no-v2',
    'chutney_dir' : '.',
    'torrc_fname' : '${dir}/torrc',
    'orport_base' : 5000,
    'dirport_base' : 7000,
    'controlport_base' : 8000,
    'socksport_base' : 9000,
    'authorities' : "AlternateDirAuthority bleargh bad torrc file!",
    'bridges' : "Bridge bleargh bad torrc file!",
    'core' : True,
}

ENV_DEF_MAP = {
    'tor' : 'CHUTNEY_TOR',
    'tor-gencert': 'CHUTNEY_TOR_GENCERT',
}

class TorEnviron(chutney.Templating.Environ):
    """Subclass of chutney.Templating.Environ to implement commonly-used
       substitutions.

       Environment fields provided:

          orport, controlport, socksport, dirport:
          dir:
          nick:
          tor_gencert:
          auth_passphrase:
          torrc_template_path:

       Environment fields used:
          nodenum
          tag
          orport_base, controlport_base, socksport_base, dirport_base
          chutney_dir
          tor

       XXXX document the above.  Or document all fields in one place?
    """
    def __init__(self,parent=None,**kwargs):
        chutney.Templating.Environ.__init__(self, parent=parent, **kwargs)

    def _get_orport(self, my):
        return my['orport_base']+my['nodenum']

    def _get_controlport(self, my):
        return my['controlport_base']+my['nodenum']

    def _get_socksport(self, my):
        return my['socksport_base']+my['nodenum']

    def _get_dirport(self, my):
        return my['dirport_base']+my['nodenum']

    def _get_dir(self, my):
        return os.path.abspath(os.path.join(my['net_base_dir'],
                                            "nodes",
                                         "%03d%s"%(my['nodenum'], my['tag'])))

    def _get_nick(self, my):
        return "test%03d%s"%(my['nodenum'], my['tag'])

    def _get_tor_gencert(self, my):
        if my['tor-gencert']:
            return my['tor-gencert']
        else:
            return my['tor']+"-gencert"

    def _get_auth_passphrase(self, my):
        return self['nick'] # OMG TEH SECURE!

    def _get_torrc_template_path(self, my):
        return [ os.path.join(my['chutney_dir'], 'torrc_templates') ]

    def _get_fingerprint(self, my):
        fpf = os.path.join(self['dir'], 'fingerprint')
        if os.path.exists(fpf):
            return open(fpf).read().strip('\n')
        else:
            return 'Na'

    def _get_lockfile(self, my):
        """Return the name of the lock file"""
        return os.path.join(self['dir'], 'lock')


class Network(object):
    """A network of Tor nodes, plus functions to manipulate them
    """
    def __init__(self,defaultEnviron):
        self._nodes = []
        self._dfltEnv = defaultEnviron
        self._nextnodenum = 0

    def _addNode(self, n):
        n.setNodenum(self._nextnodenum)
        self._nextnodenum += 1
        self._nodes.append(n)

    def _checkConfig(self):
        for n in self._nodes:
            n.getBuilder().checkConfig(self)

    def configure(self):
        network = self
        altauthlines = []
        bridgelines = []
        builders = [ n.getBuilder() for n in self._nodes ]

        self._checkConfig()

        # XXX don't change node names or types or count if anything is
        # XXX running!

        for b in builders:
            b.preConfig(network)
            altauthlines.append(b._getAltAuthLines(
                                    self._dfltEnv['hasbridgeauth']))
            bridgelines.append(b._getBridgeLines())

        self._dfltEnv['authorities'] = "".join(altauthlines)
        self._dfltEnv['bridges'] = "".join(bridgelines)

        for b in builders:
            b.config(network)

        for b in builders:
            b.postConfig(network)

    def status(self):
        statuses = [ n.getController().check() for n in self._nodes]
        n_ok = len([x for x in statuses if x])
        print "%d/%d nodes are running"%(n_ok,len(self._nodes))
        if n_ok != len(self._nodes):
            return False
        return True

    def restart(self):
        self.stop()
        self.start()

    def start(self):
        print "Starting nodes"
        return all([n.getController().start() for n in self._nodes])

    def hup(self):
        print "Sending SIGHUP to nodes"
        return all([n.getController().hup() for n in self._nodes])

    def stop(self):
        controllers = [ n.getController() for n in self._nodes ]
        for sig, desc in [(signal.SIGINT, "SIGINT"),
                          (signal.SIGINT, "another SIGINT"),
                          (signal.SIGKILL, "SIGKILL")]:
            print "Sending %s to nodes"%desc
            for c in controllers:
                if c.isRunning():
                    c.stop(sig=sig)
                elif os.path.exists(c._env['lockfile']):
                    # check lock file for cleanup
                    print "Left over stale lock file, cleaning up"
                    os.remove(c._env['lockfile'])
            print "Waiting for nodes to finish."
            for n in xrange(15):
                time.sleep(1)
                if all(not c.isRunning() for c in controllers):
                    return
                sys.stdout.write(".")
                sys.stdout.flush()
            for c in controllers:
                c.check(listNonRunning=False)

    def verify(self):
        sys.stdout.write("Verifying data transmission: ")
        sys.stdout.flush()
        status = self._verify_traffic()
        if status:
            print("Success")
        else:
            print("Failure")
        return status

    def _verify_traffic(self):
        """Verify (parts of) the network by sending traffic through it
        and verify what is received."""
        LISTEN_PORT = 4747 # FIXME: Do better! Note the default exit policy.
        DATALEN = 10*1024               # Octets.
        TIMEOUT = 3                     # Seconds.
        with open('/dev/urandom', 'r') as randfp:
            tmpdata = randfp.read(DATALEN)
        bind_to = ('127.0.0.1', LISTEN_PORT)
        tt = chutney.Traffic.TrafficTester(bind_to, tmpdata, TIMEOUT)
        for op in filter(lambda n: n._env['tag'] == 'c', self._nodes):
            tt.add(chutney.Traffic.Source(tt, bind_to, tmpdata,
                                     ('localhost', int(op._env['socksport']))))
        return tt.run()

def ConfigureNodes(nodelist):
    network = _THE_NETWORK

    for n in nodelist:
        network._addNode(n)
        if n._env['bridgeauthority']:
            network._dfltEnv['hasbridgeauth'] = True

def usage(network):
    return "\n".join(["Usage: chutney {command} {networkfile}",
       "Known commands are: %s" % (
        " ".join(x for x in dir(network) if not x.startswith("_")))])

def runConfigFile(verb, f):
    _GLOBALS = dict(_BASE_ENVIRON= _BASE_ENVIRON,
                    Node=Node,
                    ConfigureNodes=ConfigureNodes,
                    _THE_NETWORK=_THE_NETWORK)

    exec f in _GLOBALS
    network = _GLOBALS['_THE_NETWORK']

    if not hasattr(network, verb):
        print usage(network)
        print "Error: I don't know how to %s." % verb
        return

    return getattr(network,verb)()

def main():
    global _BASE_ENVIRON
    global _THE_NETWORK

    for k in ENV_DEF_MAP:
        if os.environ.get(ENV_DEF_MAP[k]):
            DEFAULTS[k] = os.environ[ENV_DEF_MAP[k]]

    _BASE_ENVIRON = TorEnviron(chutney.Templating.Environ(**DEFAULTS))
    _THE_NETWORK = Network(_BASE_ENVIRON)

    if len(sys.argv) < 3:
        print usage(_THE_NETWORK)
        print "Error: Not enough arguments given."
        sys.exit(1)

    f = open(sys.argv[2])
    result = runConfigFile(sys.argv[1], f)
    if result is False:
        return -1
    return 0

if __name__ == '__main__':
    sys.exit(main())
