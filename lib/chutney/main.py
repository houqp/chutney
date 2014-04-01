#!/usr/bin/env python
# -*- coding:utf-8 -*-

import sys
import os

from chutney import TorNet


def usage(network):
    return "\n".join(["Usage: chutney {command} {networkfile}",
       "Known commands are: %s" % (
        " ".join(x for x in dir(network) if not x.startswith("_")))])

def exit_on_error(err_msg):
    print "Error: {0}\n".format(err_msg)
    print usage(TorNet.Network(TorNet.BaseEnviron))
    sys.exit(1)

def getNetworkByConfigFile(cfgf):
    cfg = open(cfgf)
    nw = TorNet.getNetworkByConfig(cfg)
    cfg.close()
    return nw

def runConfigFile(verb, cfg):
    network = getNetworkByConfigFile(cfg)
    if not hasattr(network, verb):
        print usage(network)
        print "Error: I don't know how to %s." % verb
        return

    return getattr(network, verb)()

def parseArgs():
    if len(sys.argv) < 3:
        exit_on_error("Not enough arguments given.")
    if not os.path.isfile(sys.argv[2]):
        exit_on_error("Cannot find config file: {0}.".format(sys.argv[2]))
    return {'network_cfg': sys.argv[2], 'action': sys.argv[1]}

def main():
    args = parseArgs()
    if args['action'] == 'test':
        exec open(args['network_cfg'])
    else:
        result = runConfigFile(args['action'], args['network_cfg'])
        if result is False:
            return -1
    return 0



if __name__ == '__main__':
    sys.exit(main())
