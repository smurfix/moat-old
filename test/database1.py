#!/usr/bin/python
# -*- coding: utf-8 -*-

##
##  Copyright © 2008, Matthias Urlichs <matthias@urlichs.de>
##
##  This program is free software: you can redistribute it and/or modify
##  it under the terms of the GNU General Public License as published by
##  the Free Software Foundation, either version 3 of the License, or
##  (at your option) any later version.
##
##  This program is distributed in the hope that it will be useful,
##  but WITHOUT ANY WARRANTY; without even the implied warranty of
##  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##  GNU General Public License (included; see the file LICENSE)
##  for more details.
##

import homevent as h
from homevent.database import DbStore
from homevent.base import Name

s = DbStore(Name(("Foo","bar")))
def main():
	d = s.start()
	d.addCallback(lambda _: s.set("one",2))
	d.addCallback(lambda _: s.set(3,(4,5,6)))

	def getter(_):
		e = s.get(3)
		def chk(_):
			assert _ == (4,5,6), "Check CallBack %r" % (_,)
		e.addCallback(chk)
		return e
	d.addCallback(getter)

	def err(_):
		#_.printDetailedTraceback()
		_.printTraceback()
	d.addErrback(err)
	d.addCallback(lambda _: h.shut_down())

h.mainloop(main)

