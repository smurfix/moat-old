# -*- coding: utf-8 -*-

##
##  Copyright © 2007-2012, Matthias Urlichs <matthias@urlichs.de>
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

"""\
This code does basic configurable event mangling.

on switch *state livingroom *switch:
	send change $state lights livingroom $switch

on switch * * *:
	if neq $2 outside
	if state on alarm internal
	trigger alarm $2

Given the event "switch on livingroom main", this would cause a
"change on lights livingroom main" event if the internal alarm is off.
Otherwise a "alarm livingroom" would be triggered.

"""

from __future__ import division,absolute_import

from homevent.logging import log, TRACE
from homevent.run import register_worker,unregister_worker,MIN_PRIO,MAX_PRIO
from homevent.worker import Worker
from homevent.base import Name
from homevent.collect import Collection,Collected

onHandlers = {}
onHandlers2 = {}

class _OnHandlers(Collection):
	name = "on"

	def iteritems(self):
		def priosort(a,b):
			a=self[a]
			b=self[b]
			return cmp(a.prio,b.prio) or cmp(a.name,b.name)
		for i in sorted(self.iterkeys(), cmp=priosort):
			yield i,self[i]

	def __getitem__(self,key):
		try:
			return super(_OnHandlers,self).__getitem__(key)
		except KeyError:
			if key in onHandlers:
				return onHandlers[key]
			if key in onHandlers2:
				return onHandlers2[key][0]
			if hasattr(key,"__len__") and len(key) == 1:
				if key[0] in onHandlers:
					return onHandlers[key[0]]
				if key[0] in onHandlers2:
					return onHandlers2[key[0]][0]
			raise

	def __setitem__(self,key,val):
		assert val.name==key, repr(val.name)+" != "+repr(key)
		onHandlers[val.id] = val
		try:
			onHandlers2[val.args].append(val)
		except KeyError:
			onHandlers2[val.args] = [val]
		super(_OnHandlers,self).__setitem__(key,val)
		register_worker(val)

	def __delitem__(self,key):
		val = self[key]
		unregister_worker(val)
		del onHandlers[val.id]
		onHandlers2[val.args].remove(val)
		if not onHandlers2[val.args]:
			del onHandlers2[val.args]
		super(_OnHandlers,self).__delitem__(val.name)

	def pop(self,key):
		val = self[key] if key else self.keys()[0]
		unregister_worker(val)
		del OnHandlers[val.id]
		try:
			del OnHandlers2[val.args]
		except KeyError:
			pass
		return val
OnHandlers = _OnHandlers()
OnHandlers.does("del")

class iWorker(Worker):
	"""This is a helper class, to pass the event name to Worker.__init__()"""
	def __init__(self):
		super(iWorker,self).__init__(self.name)

class OnEventBase(Collected,iWorker):
	storage = OnHandlers.storage
	"""Link an event to executing a HomEvenT block"""

	def __init__(self, parent, args, name=None, prio=(MIN_PRIO+MAX_PRIO)//2+1):
		self.prio = prio
		self.displayname = name
		self.args = args
		self.parent = parent

		if name is None:
			name = Name("_on",self._get_id())
		super(OnEventBase,self).__init__(*name)

#		self.name = unicode(self.args)
#		if self.displayname is not None:
#			self.name += u" ‹"+" ".join(unicode(x) for x in self.displayname)+u"›"

		
		log(TRACE,"NewHandler",self.id)

	def does_event(self,event):
		ie = iter(event)
		ia = iter(self.args)
		ctx = {}
		pos = 0
		while True:
			try: e = ie.next()
			except StopIteration: e = StopIteration
			try: a = ia.next()
			except StopIteration: a = StopIteration
			if e is StopIteration and a is StopIteration:
				return True
			if e is StopIteration or a is StopIteration:
				return False
			if hasattr(a,"startswith") and a.startswith('*'):
				if a == '*':
					pos += 1
					a = str(pos)
				else:
					a = a[1:]
				ctx[a] = e
			elif str(a) != str(e):
				return False

#	def process(self, **k):
#		raise NotImplementedError("You need to implement 'process()' in %s" % (self.__class__.__name__,))

	def report(self, verbose=False):
		if not verbose:
			for r in super(OnEventBase,self).report(verbose):
				yield r
		else:
			for r in self.parent.report(verbose):
				yield r

	def info(self):
		return u"%s (%d)" % (unicode(self.args),self.prio)

	def list(self):
		for r in super(OnEventBase,self).list():
			yield r
		yield("id",self.id)
		yield("prio",self.prio)
		if self.displayname is not None:
			yield("pname"," ".join(unicode(x) for x in self.displayname))
		yield("args",self.args)
		if hasattr(self.parent,"displaydoc"):
			yield("doc",self.parent.displaydoc)

