#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from getpass import getpass
from argparse import ArgumentParser
import concurrent.futures

import os
import uuid
import datetime
import asyncio
import slixmpp
import pyinotify

class EventHandler(pyinotify.ProcessEvent):
    def my_init(self, xmppclient, linkto, baseurl, loop=None):
        self.loop = loop if loop else asyncio.get_event_loop()
        self.xmppclient = xmppclient
        self.linkto = linkto
        self.baseurl = baseurl

    def process_IN_MOVED_TO(self, event):
        datestr = datetime.datetime.now().strftime("%Y%m%d_%H.%M.%S")
        uuidstr = uuid.uuid4().hex[:8]
        extstr = os.path.splitext(event.pathname)[1]
        filename = "%s%s%s" % (datestr, uuidstr, extstr)
        os.symlink(event.pathname, "%s/%s" % (linkto, filename))
        self.xmppclient.send_message(mto=self.xmppclient.recipient,
                                     mbody="%s/%s" % (baseurl, filename),
                                     mtype='chat')


class SendMsgBot(slixmpp.ClientXMPP):
    def __init__(self, jid, password, recipient):
        slixmpp.ClientXMPP.__init__(self, jid, password)

        # Currently, "recipient' is only used by the
        # pyinotify event handler
        self.recipient = recipient

        # The session_start event will be triggered when
        # the bot establishes its connection with the server
        # and the XML streams are ready for use. We want to
        # listen for this event so that we we can initialize
        # our roster.
        self.add_event_handler("session_start", self.start)
        self.add_event_handler("message", self.echo)

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

    def echo(self, msg):
        if msg['type'] in ('chat', 'normal'):
            msg.reply("Thanks for sending\n%(body)s" % msg).send()


if __name__ == '__main__':
    # Setup the command line arguments.
    parser = ArgumentParser(description=SendMsgBot.__doc__)

    # Output verbosity options.
    parser.add_argument("-q", "--quiet", help="set logging to ERROR",
                        action="store_const", dest="loglevel",
                        const=logging.ERROR, default=logging.INFO)
    parser.add_argument("-d", "--debug", help="set logging to DEBUG",
                        action="store_const", dest="loglevel",
                        const=logging.DEBUG, default=logging.INFO)

    # JID and password options.
    parser.add_argument("-j", "--jid", dest="jid",
                        help="JID to use")
    parser.add_argument("-p", "--password", dest="password",
                        help="password to use")
    parser.add_argument("-t", "--to", dest="to",
                        help="JID to notify")
    parser.add_argument("-w", "--watch", dest="directory",
                        help="directory to watch", default=".")
    parser.add_argument("-l", "--linkto", dest="linkto",
                        help="directory to place symlinks in", default=".")
    parser.add_argument("-b", "--baseurl", dest="baseurl",
                        help="URL base to use in messages", default="http://example.com/")

    args = parser.parse_args()

    # Setup logging.
    logging.basicConfig(level=args.loglevel,
                        format='%(levelname)-8s %(message)s')

    if args.jid is None:
        args.jid = input("Username: ")
    if args.password is None:
        args.password = getpass("Password: ")
    if args.to is None:
        args.to = input("Send To: ")

    # Initialize our XMPP bot and register plugins
    xmpp = SendMsgBot(args.jid, args.password, args.to)
    xmpp.register_plugin('xep_0030') # Service Discovery
    xmpp.register_plugin('xep_0199') # XMPP Ping

    # Set a "breakpoint" in the event loop when we're ready to run messages
    loop = asyncio.get_event_loop()
    xmpp.connected_event_one = asyncio.Event()
    callback_one = lambda _: xmpp.connected_event_one.set()
    xmpp.add_event_handler('session_start', callback_one)

    # Connect to the XMPP server and run until we're ready to send messages.
    xmpp.connect(address=('talk.google.com', 5222))
    loop.run_until_complete(xmpp.connected_event_one.wait())

    # set up pyinotify stuff
    wm = pyinotify.WatchManager()
    mask = pyinotify.IN_MOVED_TO  # watched events
    wm.add_watch(args.directory, mask)
    handler = EventHandler(xmppclient=xmpp, linkto=args.linkto, baseurl=args.baseurl, loop=loop)
    notifier = pyinotify.AsyncioNotifier(wm, loop, default_proc_fun=handler)

    # Start turning the event crank
    loop.run_forever()

