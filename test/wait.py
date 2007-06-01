#!/usr/bin/python
# -*- coding: utf-8 -*-

import homevent as h
import homevent.parser as hp
import homevent.interpreter as hi
from homevent.context import Context
from homevent.reactor import ShutdownHandler
from homevent.module import load_module
from StringIO import StringIO
from test import run_logger, logger,logwrite

log = run_logger("misc",dot=False).log

input = StringIO("""\
async:
	wait 10:
		name FooBar
	trigger FooBar
wait 0.1:
	name FooBar
	update
trigger DoNow
wait 0.2
async:
	wait 0.2:
		name FooBaz
	trigger Heya
wait 0.1
drop wait FooBaz
wait 0.2
# observe no HeYa event
shutdown
""")

h.main_words.register_statement(ShutdownHandler)
load_module("trigger")
load_module("wait")
load_module("block")

def main():
	d = hp.parse(input, hi.Interpreter(Context(out=logwrite(log))), Context(logger=logger)) # , out=log)
	d.addErrback(lambda _: _.printTraceback())
	d.addBoth(lambda _: h.shut_down())

h.mainloop(main)
