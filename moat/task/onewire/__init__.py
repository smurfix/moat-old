# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division, unicode_literals
##
##  This file is part of MoaT, the Master of all Things.
##
##  MoaT is Copyright © 2007-2015 by Matthias Urlichs <matthias@urlichs.de>,
##  it is licensed under the GPLv3. See the file `README.rst` for details,
##  including optimistic statements by the author.
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
##  This header is auto-generated and may self-destruct at any time,
##  courtesy of "make update". The original is in ‘scripts/_boilerplate.py’.
##  Thus, do not remove the next line, or insert any blank lines above.
##BP

import asyncio
import pytest
from time import time

from moat.proto.onewire import OnewireServer
from moat.dev.onewire import OnewireDevice
from moat.dev import DEV_DIR,DEV
from moat.script.task import Task
from moat.script.util import objects

from etcd_tree import EtcTypes, EtcFloat,EtcInteger,EtcValue,EtcDir
from aio_etcd import StopWatching
from time import time
from weakref import WeakValueDictionary
from contextlib import suppress

import logging
logger = logging.getLogger(__name__)

import re
dev_re = re.compile(r'([0-9a-f]{2})\.([0-9a-f]{12})$', re.I)

# This is here for overriding by tests.
async def Timer(loop,dly,proc):
	return loop.call_later(dly, proc._timeout)

BUS_TTL=30 # presumed max time required to scan a bus
BUS_COUNT=5 # times to not find a whole bus before it's declared dead
DEV_COUNT=5 # times to not find a single device on a bus before it is declared dead

async def scanner(self, name):
	proc = getattr(self,'_scan_'+name)
	while True:
		warned = await proc()

tasks = {} # filled later

class ScanTask(Task):
	"""\
		Common class for 1wire bus scanners.

		Subclasses override the `typ` class variable with some name, and
		the `task_()` method with the periodic activity they want to
		perform. Whenever a device's `scan_for(typ)` returns a number, a
		ScanTask instance with that type will be created for the bus the
		device is on, which will run the task at least that often (in
		seconds).

		
		"""
	typ = None
	_trigger = None

	def __init__(self,parent):
		self.parent = parent
		self.env = parent.env
		self.bus = parent.bus
		self.bus_cached = parent.bus_cached
		super().__init__(parent.env.cmd,('onewire','scan',self.typ,self.env.srv_name)+self.bus.path)

	async def task(self):
		"""\
			run task_() periodically.
			
			Do not override this; override .task_ instead.
			"""
		ts = time()
		long_warned = 0
		while True:
			if self._trigger is None or self._trigger.done():
				self._trigger = asyncio.Future(loop=self.loop)
			warned = await self.task_()
			t = self.parent.timers[self.typ]
			if t is None:
				return
			# subtract the time spent during the task
			if warned and t < 10:
				t = 10
			ts += t
			nts = time()
			delay = ts - nts
			if delay < 0:
				if not long_warned:
					long_warned = int(100/t)+1
					# thus we get at most one warning every two minutes, more or less
					logger.warning("Task %s took %s seconds, should run every %s",self.name,t-delay,t)
					# TODO: write that warning to etcd instead
				ts = nts
				continue
			elif long_warned:
				long_warned -= 1
			with suppress(asyncio.TimeoutError):
				await asyncio.wait_for(self._trigger,delay, loop=self.loop)

	def trigger(self):
		"""Call to cause an immediate re-scan"""
		if self._trigger is not None and not self._trigger.done():
			self._trigger.set_result(None)

	async def task_(self):
		"""Override this to actually implement the periodic activity."""
		raise RuntimeError("You need to override '%s.task_'" % (self.__class__.__name__,))

class EtcOnewireBus(EtcDir):
	tasks = None
	_set_up = False

	def __init__(self,*a,**k):
		super().__init__(*a,**k)
		self.tasks = WeakValueDictionary()
		self.timers = {}
		self.bus = self.env.srv.at('uncached').at(*(self.name.split(' ')))
		self.bus_cached = self.env.srv.at(*(self.name.split(' ')))

	@property
	def devices(self):
		d = self.env.devices
		for f1,v in self['devices'].items():
			for f2,b in v.items():
				if b > 0:
					continue
				try:
					dev = d[f1][f2][DEV]
				except KeyError:
					continue
				if not isinstance(dev,OnewireDevice):
					# This should not happen. Otherwise we'd need to
					# convert .setup_tasks() into a task.
					raise RuntimeError("XXX: bus lookup incomplete")
				yield dev

	def has_update(self):
		super().has_update()
		if self._seq is None:
			logger.debug("Stopping tasks %s %s %s",self,self.bus_cached.path,list(self.tasks.keys()))
			if self.tasks:
				t,self.tasks = self.tasks,WeakValueDictionary()
				for v in t.values():
					logger.info('CANCEL 16 %s',t)
					t.cancel()
		elif self._set_up:
			self.setup_tasks()

	def setup_tasks(self):
		if not tasks:
			for t in objects(__name__,ScanTask):
				tasks[t.typ] = t
		for name,task in tasks.items():
			t = None
			for dev in self.devices:
				f = dev.scan_for(name)
				if f is None:
					pass
				elif t is None or t > f:
					t = f

			self.timers[name] = t
			if t is not None and name not in self.tasks:
				logger.debug("Starting task %s %s %s",self,self.bus_cached.path,name)
				self.tasks[name] = self.env.add_task(task(self))
		self._set_up = True
		
EtcOnewireBus.register('broken', cls=EtcInteger)
EtcOnewireBus.register('devices','*','*', cls=EtcInteger)

class BusScan(Task):
	"""This task periodically scans all buses of a 1wire server."""
	name="onewire/scan"
	summary="Scan the buses of a 1wire server"
	_delay = None
	_delay_timer = None

	@classmethod
	def types(cls,tree):
		super().types(tree)
		tree.register("delay",cls=EtcFloat)
		tree.register("update_delay",cls=EtcFloat)
		tree.register("ttl",cls=EtcInteger)
		
	async def _scan_one(self, *bus):
		"""Scan a single bus"""
		b = " ".join(bus)
		bb = self.srv_name+" "+b

		old_devices = set()
		try:
			k = self.old_buses.remove(b)
		except KeyError:
			# The bus is new
			logger.info("New 1wire bus: %s",bb)

			await self.tree['bus'].set(b,{'broken':0,'devices':{}})
			dev_counter = self.tree['bus'][b]['devices']
		else:
			# The bus is known. Remember which devices we think are on it
			dev_counter = self.tree['bus'][b]['devices']
			for d,v in dev_counter.items():
				for e in v.keys():
					old_devices.add((d,e))

		for f in await self.srv.dir('uncached',*bus):
			m = dev_re.match(f)
			if m is None:
				continue
			f1 = m.group(1).lower()
			f2 = m.group(2).lower()
			if (f1,f2) in old_devices:
				old_devices.remove((f1,f2))
			if f1 == '1f':
				await self._scan_one(*(bus+(f,'main')))
				await self._scan_one(*(bus+(f,'aux')))

			if f1 not in self.devices:
				await self.devices.set(f1,{})
			d = await self.devices[f1]
			if f2 not in d:
				await self.devices[f1].set(f2,{DEV:{'path':bb}})
			fd = await d[f2][DEV]
			await fd.setup()
			op = fd.get('path','')
			if op != bb:
				if ' ' in op:
					self.drop_device(fd,delete=False)
				await fd.set('path',bb)

			if f1 not in dev_counter:
				await dev_counter.set(f1,{})
			if f2 not in dev_counter[f1]:
				await dev_counter[f1].set(f2,0)

		# Now mark devices which we didn't see as down.
		# Protect against intermittent failures.
		for f1,f2 in old_devices:
			try:
				v = dev_counter[f1][f2]
			except KeyError: # pragma: no cover
				# possible race condition
				continue
			if v >= DEV_COUNT:
				# kill it.
				try:
					dev = self.devices[f1][f2][DEV]
				except KeyError:
					pass
				else:
					await self.drop_device(dev)
			else:
				# wait a bit
				await dev_counter[f1].set(f2,v+1)

		# Mark this bus as "scanning OK".
		bus = self.tree['bus'][b]
		bus.setup_tasks()
		try:
			v = bus['broken']
		except KeyError:
			v = 99
		if v > 0:
			await bus.set('broken',0)

	async def drop_device(self,dev, delete=True):
		"""When a device vanishes, remove it from the bus it has been at"""
		try:
			p = dev['path']
		except KeyError:
			return
		try:
			s,b = p.split(' ',1)
		except ValueError:
			pass
		else:
			if s == self.srv_name:
				dt = self.tree['bus'][b]['devices']
				drop = False
			else:
				dt = await self.etcd.tree('/bus/onewire/'+s+'/bus/'+b+'/devices',env=self)
				drop = True
			try:
				f1 = dev.parent.parent.name
				f2 = dev.parent.name
			except AttributeError:
				pass # parent==None: node gone, don't bother
			else:
				try:
					await dt[f1].delete(f2)
				except KeyError as exc:
					logger.exception("Bus node gone? %s.%s on %s %s",f1,f2,s,b)
			finally:
				if drop:
					await dt.close()
		if delete:
			await dev.delete('path')

	async def drop_bus(self,bus):
		"""Somebody unplugged a whole bus"""
		logger.warning("Bus '%s %s' has vanished", self.srv_name,bus.name)
		for f1,v in bus.items():
			for f2 in bus.keys():
				try:
					dev = self.devices[f1][f2][DEV]
				except KeyError:
					pass
				else:
					await self.drop_device(dev, delete=False)
			await self.tree['bus'].delete(bus.name)

	def add_task(self, t):
		t = asyncio.ensure_future(t, loop=self.loop)
		self.new_tasks.add(t)
		if not self._trigger.done():
			self._trigger.set_result(None)
		return t

	async def task(self):
		self.srv = None
		self.tree = None
		self.srv_name = None
		self.new_cfg = asyncio.Future(loop=self.loop)

		types=EtcTypes()
		types.register('server','port', cls=EtcInteger)
		types.register('scanning', cls=EtcFloat)
		types.register('bus','*', cls=EtcOnewireBus)
		
		server = self.config['server']
		self.srv_name = server
		update_delay = self.config.get('update_delay',None)

		# Reading the tree requires accessing self.srv.
		# Initializing self.srv requires reading the …/server directory.
		# Thus, first we get that, initialize self.srv with the data …
		tree,srv = await self.etcd.tree("/bus/onewire/"+server,sub=('server',), types=types,env=self,static=True)
		self.srv = OnewireServer(srv['host'],srv.get('port',None), loop=self.loop)

		# and then throw it away in favor of the real thing.
		self.tree = await self.etcd.tree("/bus/onewire/"+server, types=types,env=self,update_delay=update_delay)
		nsrv = self.tree['server']
		if srv != nsrv:
			import pdb;pdb.set_trace()
			new_cfg.set_result("duh")
		nsrv.add_monitor(self.cfg_changed)
		del tree

		devtypes=EtcTypes()
		for t in OnewireDevice.dev_paths():
			devtypes.step(t[:-1]).register(DEV,cls=t[-1])
		tree = await self.cmd.root._get_tree()
		self.devices = await tree.subdir(DEV_DIR+(OnewireDevice.prefix,))
		self.devices.env = self
		self.devices._types = devtypes
		self._trigger = None

		main_task = asyncio.ensure_future(self.task_busscan(), loop=self.loop)
		self.tasks = {main_task}
		self.new_tasks = set()
		try:
			while not main_task.done() and not self.new_cfg.done():
				if self._trigger is None or self._trigger.done():
					self._trigger = asyncio.Future(loop=self.loop)
					self.tasks.add(self._trigger)
				d,p = await asyncio.wait(self.tasks, loop=self.loop, return_when=asyncio.FIRST_COMPLETED)
				if self.new_tasks:
					p |= self.new_tasks
					self.new_tasks = set()
				for t in d:
					try:
						t.result()
					except asyncio.CancelledError as exc:
						logger.info("Cancelled: %s", t)
				self.tasks = p

		except BaseException as exc:
			logger.exception("interrupted?")
			p = self.tasks
			raise
		finally:
			for t in p:
				if not t.done():
					logger.info('CANCEL 17 %s',t)
					t.cancel()
			await asyncio.wait(p, loop=self.loop, return_when=asyncio.ALL_COMPLETED)
			logger.debug("OWT 9x")
		logger.debug("OWT 9")
		for t in d:
			t.result()
			# this will re-raise whatever exception triggered the first wait, if any
		logger.debug("OWT X")

	async def task_busscan(self):
		"""\
			This is the main bus scanning sub-task. It's responsible for
			finding all (sub) buses, scanning them for devices, and for firing
			off any other task which these may require.

			TODO: trigger a bus scan manually instead of / in addition to periodically
			"""

		while True:
			#logger.debug("SCAN ALL")
			if self.config['delay']:
				#logger.debug("SCAN ALL A %s",self.config['delay'])
				self._delay = asyncio.Future(loop=self.loop)
				self._delay_timer = await Timer(self.loop,self.config['delay'], self)

			#logger.debug("SCAN ALL B")
			if 'scanning' in self.tree:
				# somebody else is processing this bus. Grumble.
				logger.info("Server '%s' locked.",self.srv_name)
				tree._get('scanning').add_monitor(self._unlock)
				continue
			#logger.debug("SCAN ALL C")
			await self.tree.set('scanning',value=time(),ttl=BUS_TTL)
			#logger.debug("SCAN ALL D")
			try:
				self.old_buses = set()
				if 'bus' in self.tree:
					for k in self.tree['bus'].keys():
						self.old_buses.add(k)
				else:
					await self.tree.set('bus',{})
				for bus in await self.srv.dir('uncached'):
					if bus.startswith('bus.'):
						await self._scan_one(bus)

				#logger.debug("SCAN ALL E %s",self.old_buses)
				# Delete buses which haven't been seen for some time
				# (to protect against intermittent failures)
				for bus in self.old_buses:
					bus = self.tree['bus'][bus]
					v = bus['broken']
					if v < BUS_COUNT:
						logger.info("Bus '%s' not seen",bus)
						await bus.set('broken',v+1)
					else:
						await self.drop_bus(bus)
				#logger.debug("SCAN ALL F")

			finally:
				if not self.tree.stopped.done():
					#logger.debug("SCAN ALL G")
					await self.tree.delete('scanning')
				#logger.debug("SCAN ALL H")

			if self._delay is None:
				#logger.debug("SCAN EX")
				break
			#logger.debug("SCAN WAIT")
			try:
				await self._delay
				self._delay.result()
				#logger.debug("SCAN HAS %s", self._delay.result())
			except StopWatching:
				#logger.debug("SCAN STOP")
				break
			except Exception as e:
				#logger.exception("SCAN OUCH")
				raise
			if self.tree.stopped.done():
				#logger.debug("SCAN DONE")
				return self.tree.stopped.result()
			#logger.debug("SCAN REDO")
	
	def _timeout(self,exc=None):
		"""Called from timer"""
		if self._delay is not None and not self._delay.done():
			if exc is None:
				self._delay.set_result("timeout")
			else:
				# This is for the benefit of testing
				self._delay.set_exception(exc)

	def trigger(self):
		"""Tell all tasks to run now. Used mainly for testing."""
		#logger.debug("SCAN TRIGGER")
		if self._delay is not None and not self._delay.done():
			self._delay.set_result("trigger")
			logger.info('CANCEL 17 %s',self._delay_timer)
			self._delay_timer.cancel()
		for t in self.tasks:
			if hasattr(t,'trigger'):
				t.trigger()

	def cfg_changed(self, d=None):
		"""\
			Called from task machinery when my basic configuration changes.
			Rather than trying to fix it all up, this stops (and thus
			restarts) the whole thing.
			"""
		if d is None:
			d = self.config
		if not d.notify_seq:
			# Initial call. Not an update. Ignore.
			return
		logger.warn("Config changed %s %s", self,d)
		if not self.new_cfg.done():
			self.new_cfg.set_result(None)

	def _unlock(self,node): # pragma: no cover
		"""Called when the 'other' scanner exits"""
		if node._seq is not None:
			return
		if self._delay is not None and not self._delay.done():
			self._delay.set_result("unlocked")
			logger.info('CANCEL 17 %s',self._delay_timer)
			self._delay_timer.cancel()

