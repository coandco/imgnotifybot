#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from getpass import getpass
from argparse import ArgumentParser
from configparser import SafeConfigParser
import concurrent.futures

import os
import uuid
import datetime
import asyncio
from urllib.parse import urljoin
import slixmpp
import pyinotify

class EventHandler(pyinotify.ProcessEvent):
    def my_init(self, xmppclient, linkto, baseurl, recipient, loop=None):
        self.loop = loop if loop else asyncio.get_event_loop()
        self.xmppclient = xmppclient
        self.linkto = linkto
        self.baseurl = baseurl
        self.recipient = recipient

    def process_IN_MOVED_TO(self, event):
        datestr = datetime.datetime.now().strftime("%Y%m%d_%H.%M.%S")
        uuidstr = uuid.uuid4().hex[:8]
        extstr = os.path.splitext(event.pathname)[1]
        filename = "%s%s%s" % (datestr, uuidstr, extstr)
        os.symlink(event.pathname, os.path.join(self.linkto, filename))
        self.xmppclient.send_message(mto=self.recipient,
                                     mbody=urljoin(self.baseurl, filename),
                                     mtype='chat')


class SendMsgBot(slixmpp.ClientXMPP):
    """
    XMPP bot that will hold a connection open while watching for pyinotify events.
    """
    def __init__(self, jid, password, auto_reconnect=False):
        slixmpp.ClientXMPP.__init__(self, jid, password)

        # The session_start event will be triggered when
        # the bot establishes its connection with the server
        # and the XML streams are ready for use. We want to
        # listen for this event so that we we can initialize
        # our roster.
        self.add_event_handler("session_start", self.start)
        self.add_event_handler("message", self.echo)
        self.add_event_handler("disconnected", self.end)
        self.end_session_on_disconnect = not auto_reconnect

    def start(self, event):
        """
        Process the session_start event.

        Typical actions for the session_start event are
        requesting the roster and broadcasting an initial
        presence stanza.

        Arguments:
            event -- An empty dictionary. The session_start
                     event does not provide any additional
                     data.
        """
        self.send_presence()
        self.get_roster()

    def end(self, event):
        """
        Process the session_end event.  In this case, reconnect unless
        we were specifically told to "die".
        """
        if not self.end_session_on_disconnect:
            self.connect(address=('talk.google.com', 5222))

    @asyncio.coroutine
    def echo(self, msg):
        if msg['type'] in ('chat', 'normal'):
            if msg['body'] == 'forget on':
                ret = yield from self.plugin['google']['nosave'].enable(jid=msg['from'].bare)
                msg.reply("%s recording disabled" % msg['from']).send()
            elif msg['body'] == 'forget off':
                msg.reply("%s recording enabled" % msg['from']).send()
                ret = yield from self.plugin['google']['nosave'].disable(jid=msg['from'].bare)
            elif msg['body'] == 'die':
                self.end_session_on_disconnect = True
                self.disconnect()
            else:
                msg.reply("%s sent %s" % (msg["from"], msg["body"])).send()


if __name__ == '__main__':
    # Setup the command line arguments.
    parser = ArgumentParser(description=SendMsgBot.__doc__)

    # Config file location
    parser.add_argument('-c', '--conf', help='location of config file',
                        dest="conf", default='imgnotifybot.conf', metavar='FILE')

    # Output verbosity options.
    parser.add_argument("-q", "--quiet", help="set logging to ERROR",
                        action="store_const", dest="loglevel",
                        const=logging.ERROR, default=logging.INFO)
    parser.add_argument("-d", "--debug", help="set logging to DEBUG",
                        action="store_const", dest="loglevel",
                        const=logging.DEBUG, default=logging.INFO)

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=args.loglevel,
                        format='%(levelname)-8s %(message)s')

    # Load config
    config = SafeConfigParser()
    config.read(args.conf)

    # Initialize our XMPP bot and register plugins
    xmpp = SendMsgBot(config['credentials']['jid'], config['credentials']['password'],
                      auto_reconnect=True)
    xmpp.register_plugin('xep_0030') # Service Discovery
    xmpp.register_plugin('xep_0199') # XMPP Ping
    xmpp.register_plugin('google')

    # Set a "breakpoint" in the event loop when we're ready to run messages
    loop = asyncio.get_event_loop()
    xmpp.connected_event_one = asyncio.Event()
    callback_one = lambda _: xmpp.connected_event_one.set()
    xmpp.add_event_handler('session_start', callback_one)

    xmpp.add_event_handler('session_end', lambda _: loop.stop())

    # Connect to the XMPP server and run until we're ready to send messages.
    xmpp.connect(address=('talk.google.com', 5222))
    loop.run_until_complete(xmpp.connected_event_one.wait())

    # For each [watch.*] section in the config, register a pyinotify listener
    for watcher in [dict(config[x]) for x in config.sections() if x.startswith("watch")]:
        wm = pyinotify.WatchManager()
        mask = pyinotify.IN_MOVED_TO  # watched events
        wm.add_watch(watcher["watchdir"], mask)
        handler = EventHandler(xmppclient=xmpp, linkto=watcher["linkto"],
                               baseurl=watcher["baseurl"], recipient=watcher["msgto"],
                               loop=loop)
        notifier = pyinotify.AsyncioNotifier(wm, loop, default_proc_fun=handler)

    # Start turning the event crank
    loop.run_forever()

