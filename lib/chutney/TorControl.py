#!/usr/bin/env python
# -*- coding:utf-8 -*-
#
# Copyright 2013 Qingping Hou
# Copyright 2011 Nick Mathewson, Michael Stone
# Copyright 2013 The Tor Project
#
#  You may do anything with this work that copyright law would normally
#  restrict, so long as you retain the above notice(s) and this license
#  in all redistributed copies and derived works.  There is no warranty.


from stem.control import Controller


class TorControl():
    """
    Tor Control Abstraction.
    Currently, it's a wrapper around stem controller module
    """
    def __init__(self, address='127.0.0.1', port=9051, password=None):
        self.stemtc = Controller.from_port(address=address, port=port)
        if password:
            self.stemtc.authenticate(password='chutneytest')

    def get(self, info):
        return getattr(self.stemtc, 'get_{0}'.format(info))()

    def add_event_listener(self, handler, *evs):
        return self.stemtc.add_event_listener(handler, *evs)

    def remove_event_listener(self, handler):
        return self.stemtc.remove_event_listener(handler)

def connect(**kwargs):
    return TorControl(**kwargs)
