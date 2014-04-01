from chutney import TorNet

network = getNetworkByConfigFile('networks/basic')
network.restart() # clean up previous network

cli = network.getNodeByTag('c')[0]
ctrl = cli.getController()

print "waiting for client to bootstrap..."
def check_bs_done(ev):
    return ev.action == 'BOOTSTRAP' and ev.keyword_args['PROGRESS'] == '100'
if ctrl.waitForEvent('STATUS_CLIENT', check_bs_done, timeout=20):
    print "client bootstrap done!"
    network.verify()
else:
    print "client bootstrap failed!"

network.stop() # cleanup
