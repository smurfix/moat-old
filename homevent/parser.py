#!/usr/bin/python
# -*- coding: utf-8 -*-

"""\
This code parses a config file.

By itself, it understands nothing whatsoever. This package includes a
"help" command:

	help [word...]
		- show what "word" does

See the homevent.config module and the test/parser.py script
for typical usage.

"""

from tokenize import generate_tokens
import Queue
import sys
from twisted.internet import reactor,threads,defer
from twisted.internet.interfaces import IPushProducer,IPullProducer
from twisted.python import failure
from twisted.protocols.basic import LineReceiver
from threading import Lock

from homevent.context import Context
from homevent.io import Outputter
from homevent.run import process_failure
from homevent.event import Event
from homevent.statement import SimpleStatement,ComplexStatement

# We need to hack tokenize
import tokenize as t
import re
t.Operator = re.sub(r"\(",r"(\$[0-9]+|[$*]([a-z][a-z0-9]*)?|",t.Operator,count=1)
t.Funny = t.group(t.Operator, t.Bracket, t.Special)
t.PlainToken = t.group(t.Number, t.Funny, t.String, t.Name)
t.Token = t.Ignore + t.PlainToken
t.tokenprog = re.compile(t.Token)
t.PseudoToken = t.Whitespace + t.group(t.PseudoExtras, t.Number, t.Funny, t.ContStr, t.Name)
t.pseudoprog = re.compile(t.PseudoToken)

del t
del re

class InputEvent(Event):
	"""An event that's just a line from the interpreter"""
	def __str__(self):
		try:
			return "⌁."+"¦".join(self.names)
		except Exception:
			return "⌁ REPORT_ERROR: "+repr(self.names)

	def report(self, verbose=False):
		try:
			yield "IEVENT: "+"¦".join(self.names)
		except Exception:
			yield "IEVENT: REPORT_ERROR: "+repr(self.names)


class Processor(object):
	"""Base class: Process input lines and do something with them."""
	def __init__(self, parent=None, ctx=None):
		self.ctx = ctx or Context()
		self.parent = parent
	
	def simple_statement(self,args):
		"""\
			A simple statement is a sequence of words. Analyze them.
			"""
		raise NotImplementedError("I cannot understand simple statements.",args)

	def complex_statement(self,args):
		"""\
			A complex statement is a sequence of words followed by a
			colon and at least one sub-statement. This procedure needs
			to reply with a new translator which will (one hopes) accept
			all the sub-statements.

			Needs to return a processor for the sub-statements.
			"""
		raise NotImplementedError("I cannot understand complex statements.",args)
	
	def done(self):
		"""\
			Called on a sub-translator to note that there will be no
			more statements.
			"""
		pass

class CollectProcessorBase(Processor):
	"""\
		A processor which simply stores all (sub-)statements, recursively.
		You need to override .store() in order to specify _where_.
		"""

	verify = False
	def __init__(self, parent=None, ctx=None, args=None, verify=None):
		super(CollectProcessorBase,self).__init__(parent=self, ctx=ctx)
		self.args = args
		self.statements = []
		if verify is not None:
			self.verify = verify
		self.ctx = ctx

	def simple_statement(self,args):
		if self.verify:
			self.ctx.words.lookup(args) # discard the result
		self.store(args)

	def complex_statement(self,args):
		"""\
			Note that this code uses a standard CollectProcessor for
			sub-blocks. That is intentional.
			"""
		if verify:
			subdict,args = self.ctx.words.lookup(args)
			ctx = self.ctx(words=subdict)
		else:
			ctx = self.ctx
		subc = CollectProcessor(parent=self.parent, ctx=ctx, args=args)
		self.store(subc)
		return subc

class CollectProcessor(CollectProcessorBase):
	"""A processor which adds all statements to its parent."""
	def store(self,proc):
		self.parent.add(proc)

	def done(self):
		self.parent.done()

class ImmediateCollectProcessor(CollectProcessor):
	"""\
		A processor which stores all (sub-)statements, recursively --
		except those that are marked as Immediate, which get executed.
		"""

	def __init__(self, parent=None, ctx=None, args=None, verify=False):
		super(CollectProcessorBase,self).__init__(parent=parent, ctx=ctx)

	def simple_statement(self,args):
		me = self.ctx.words

		event=InputEvent(self.ctx, *args)
		fn = me.lookup(event)
		fn =  fn(parent=me, ctx=self.ctx)
		fn.called(event)
		if fn.immediate:
			return fn.run(self.ctx)
		self.store(fn)

	def complex_statement(self,args):
		me = self.ctx.words
		fn = me.lookup(args)
		fn = fn(parent=me, ctx=self.ctx)
		fn.called(args)
		if fn.immediate:
			try:
				fn.input_complex()
			except AttributeError,e:
				return self.ctx._error(e)
			else:
				return fn.processor(parent=fn,ctx=self.ctx(words=fn))
		else:
			subc = ImmediateCollectProcessor(parent=fn, ctx=ctx, args=args)
			self.store(subc)
			return subc

class Parser(Outputter,LineReceiver):
	"""The input parser object. It serves as a LineReceiver and a 
	   normal (but non-throttle-able) producer."""
	delimiter="\n"

	def __init__(self, proc, ctx=None, delimiter=None):
		"""Parse an input stream and pass the commands to the processor
		@proc."""
		super(Parser,self).__init__()

		self.line_queue = Queue.Queue(10)
		self.symbol_queue = Queue.Queue()
		self.result = defer.Deferred()
		self.more_parsing = None
		self.ending = False

		if ctx is None:
			self.ctx = Context()
			self.ctx.out=self
		else:
			if "out" not in ctx:
				ctx.out=self
			self.ctx = ctx()

		if "filename" not in self.ctx:
			self.ctx.filename="<stdin?>"
		if delimiter:
			self.delimiter=delimiter
		self.proc = proc
		self.p_wait = []
		self.p_wait_lock = Lock()
		self.restart_producer = False

		def ex(_):
			self.loseConnection()
			return _
		self.result.addBoth(ex)
		self.addDropCallback(self.endConnection)

	def endConnection(self, res=None):
		"""Called to stop"""
		d = defer.Deferred()
		#reactor.callLater(0,self._endConnection,d,res)
		self._endConnection(d,res)
		return d

	def _endConnection(self,d,r):
		def ex(_):
			d.callback(r)
			return _
		if self.ending:
			self.result.addBoth(ex)
			return

		self.ending = True
		q = self.line_queue
		if q is not None:
			try:
				q.put(None, block=(self.transport is None))
			except Queue.Full:
				reactor.callInThread(q.put,None,block=True)
		self.result.addBoth(ex)
		if self.transport:
			self.transport.loseConnection()

	def connectionLost(self,reason):
		super(Parser,self).connectionLost(reason)
		self.endConnection()

	def run(self, producer, *a,**k):
		"""Parse this producer's stream."""
		s = producer(self,*a,**k)
		self.startParsing()
		return self.result

	def lineReceived(self, data):
		"""Standard LineReceiver method"""
		if data is not None:
			self.p_wait.append(data)

		if not self.p_wait_lock.acquire(False):
			return

		try:
			while self.p_wait:
				item = self.p_wait.pop(0)
				self.line_queue.put(item, block=(self.transport is None))
		except Queue.Full:
			self.p_wait.insert(0,item)
			self._pauseProducing()

		self.p_wait_lock.release()

	def _pauseProducing(self):
		if self.transport:
			self.pauseProducing()

	def _resumeProducing(self):
		self.lineReceived(None)
		if self.transport:
			self.resumeProducing()

	def readline(self):
		"""Queued ReadLine, to be called from the _sym_parse thread ONLY"""
		q = self.line_queue
		if q is None:
			return ""
		try:
			l = q.get(block=False)
		except Queue.Empty:
			reactor.callFromThread(self._resumeProducing)
			l = q.get(block=True)
		if l is None:
			self.line_queue = None
			return ""
		return l+"\n"

	def startParsing(self):
		self._parse() # goes to a different thread
		if not self.transport:
			self.connectionMade()

	def _parse(self):
		"""\
			Iterator. It gets fed tokens, assembles them into
			statements, and calls the processor with them.
			"""
		self.p_state=0
		self.p_pop_after=False
		self.p_stack = []
		self.p_args = []
		self.p_gen = generate_tokens(self.readline)
		reactor.callInThread(self._sym_parse)
		self._do_parse()

	def _sym_parse(self):
		"""Thread transferring input lines to symbols."""
		from token import ENDMARKER

		while True:
			t = self.p_gen.next()
			try:
				self.symbol_queue.put(t, block=False)
			except Queue.Full:
				reactor.callFromThread(self._pauseProducing)
				self.symbol_queue.put(t, block=True)
				reactor.callFromThread(self._resumeProducing)
			q = self.more_parsing
			if q is not None:
				self.more_parsing = None
				def cb(q):
					try: q.callback(None)
					except defer.AlreadyCalledError: pass
				reactor.callFromThread(cb,q)
			if t[0] == ENDMARKER:
				return

	def _do_parse(self):
		# States: 0 newline, 1 after first word, 2 OK to extend word
		#         3+4 need newline+indent after sub-level start, 5 extending word
		# TODO: write a nice .dot file for this stuff

		if self.more_parsing is not None:
			return
		while True:
			try:
				t,txt,beg,end,line = self.symbol_queue.get(block=False)
			except Queue.Empty:
				# possible race condition: new 
				self.more_parsing = d = defer.Deferred()
				if not self.symbol_queue.empty():
					try: d.callback(None)
					except defer.AlreadyCalledError: pass
				d.addCallback(lambda _: self._do_parse())
				return
			try:
				res = self._parseStep(t,txt,beg,end,line)
				if isinstance(res,defer.Deferred):
					def in_main():
						res.addCallback(lambda _: self._do_parse())
						res.addErrback(process_failure)
					reactor.callLater(0,in_main)
					return

			except StopIteration:
				try: self.result.callback(None)
				except defer.AlreadyCalledError: pass
				return
			except Exception:
				try: self.result.errback(failure.Failure())
				except defer.AlreadyCalledError: pass

	def _parseStep(self, t,txt,beg,end,line):
		from token import NUMBER,NAME,DEDENT,INDENT,OP,NEWLINE,ENDMARKER, \
			STRING
		from tokenize import COMMENT,NL

		if "logger" in self.ctx: self.ctx.logger("T",self.p_state,t,txt,beg,end,line)
		if t == COMMENT:
			return
		if self.p_state == 0: # begin of statement
			if t == NAME:
				self.p_args = [txt]
				self.p_state=1
				return
			elif t == DEDENT:
				self.proc.done()
				if self.p_stack:
					self.proc = self.p_stack.pop()
					return
				else:
					raise StopIteration
			elif t == ENDMARKER:
				self.proc.done()
				while self.p_stack:
					self.proc = self.p_stack.pop()
					self.proc.done()
				raise StopIteration
			elif t in(NL,NEWLINE):
				return
			elif t == OP and txt == ".":
				return # "I am done"
		elif self.p_state in (1,2): # after first word
			if t == NAME:
				self.p_args.append(txt)
				self.p_state = 2
				return
			elif t == OP and txt in ("*","+","-"):
				self.p_args.append(txt)
				self.p_state = 1
				return
			elif t == NUMBER:
				self.p_args.append(eval(txt,{},{}))
				self.p_state = 1
				return
			elif t == STRING:
				self.p_args.append(eval(txt,{},{}))
				self.p_state = 1
				return
			elif t == OP and txt[0] in ("$","*"):
				self.p_args.append(txt)
				self.p_state = 1
				return
			elif t == OP and txt == "." and self.p_state == 2:
				self.p_state = 5
				return
			elif t == OP and txt == ":":
				try:
					p = self.proc.complex_statement(self.p_args)
				except Exception,e:
					p = self.ctx._error(e)

				def have_p(_):
					self.p_stack.append(self.proc)
					self.proc = _
					self.p_state = 3
				if isinstance(p,defer.Deferred):
					p.addBoth(have_p)
				else:
					have_p(p)
					
				return p
			elif t == NEWLINE:
				try:
					r = self.proc.simple_statement(self.p_args)
				except Exception,e:
					#r = self.ctx._error(e)
					raise
					
				if self.p_pop_after:
					self.proc.done()
					self.proc = self.p_stack.pop()
					self.p_pop_after=False
				self.p_state=0
				return r
		elif self.p_state == 3:
			if t == NEWLINE:
				self.p_state = 4
				return
			elif t == NAME:
				self.p_args = [txt]
				self.p_state = 1
				self.p_pop_after = True
				return
			else:
				self.proc = self.p_stack.pop()
		elif self.p_state == 4:
			if t == INDENT:
				self.p_state = 0
				return
			elif t == NEWLINE:
				# ignore
				return
			else:
				self.proc = self.p_stack.pop()
		elif self.p_state == 5:
			if t == NAME:
				self.p_args[-1] += "."+txt
				self.p_state = 2
				return

		if self.p_pop_after:
			self.proc = self.p_stack.pop()
			self.p_pop_after = False

		self.ctx._error(SyntaxError("Unknown token %s (%d, state %d) in %s:%d" % (repr(txt),t,self.p_state,self.ctx.filename,beg[0])))
		self.p_state=0


class Help(SimpleStatement):
	name=("help",)
	doc="show doc texts"
	long_doc="""\
The "help" command shows which words are recognized at each level.
"help foo" also shows the sub-commands, i.e. what would be allowed
in place of the "XXX" in the following statement:

	foo:
		XXX

Statements may be multi-word and follow generic Python syntax.
"""

	def run(self,ctx,**k):
		event = self.params(ctx)
		words = self.parent

		wl = event[len(self.name):]
		while wl:
			try:
				wlist = words._get_wordlist()
			except AttributeError:
				break

			n = len(wl)
			while n >= 0:
				try:
					words = wlist[tuple(wl[:n])]
				except KeyError:
					pass
				else:
					wl = wl[n:]
					break
				n = n-1
			if n < 0:
				break

		if wl:
			print >>self.ctx.out,"Not a command:"," ".join(wl)

		try:
			doc = ":\n"+words.long_doc.rstrip("\n")
		except AttributeError:
			doc = " : "+words.doc
		print >>self.ctx.out," ".join(words.name)+doc

		try:
			wlist = words._get_wordlist()
		except AttributeError:
			pass
		else:
			if words is not self.parent:
				print >>self.ctx.out,"Known words:"
			maxlen=0
			for h in words.iterkeys():
				hlen = len(" ".join(h))
				if hlen > maxlen: maxlen = hlen
			def nam(a,b):
				return cmp(a.name,b.name)
			for h in sorted(words.itervalues(),nam):
				hname = " ".join(h.name)
				print >>self.ctx.out,hname+(" "*(maxlen+1-len(hname)))+": "+h.doc

class main_words(ComplexStatement):
	name = ("Main",)
	doc = "word list:"

class Interpreter(Processor):
	"""\
		A basic interpreter for the main loop, which runs every
		statement immediately.
		"""
	def __init__(self, ctx=None):
		super(Interpreter,self).__init__(ctx)
		if "words" not in ctx:
			self.ctx = ctx(words=main_words(ctx=ctx))
		else:
			self.ctx = ctx

	def simple_statement(self,args):
		me = self.ctx.words
		fn = me.lookup(args)
		fn = fn(parent=me, ctx=self.ctx)
		fn.called(InputEvent(self.ctx, *args).clone())
		return fn.run(self.ctx)

	def complex_statement(self,args):
		me = self.ctx.words
		fn = me.lookup(args)
		try:
			fn = fn(parent=me, ctx=self.ctx)
		except TypeError,e:
			print >>sys.stderr,"For",repr(fn),"::"
			raise
		fn.called(args)
		try:
			fn.input_complex()
		except AttributeError,e:
			return self.ctx._error(e)
		else:
			return fn.processor ## (parent=fn,ctx=self.ctx(words=fn))
	
	def done(self):
		#print >>self.ctx.out,"Exiting"
		pass

def _parse(g,input):
	"""Internal code for parse() which reads the input in a separate thread"""
	g.startParsing()
	while True:
		l = input.readline()
		if not l:
			break
		g.lineReceived(l)
	reactor.callFromThread(g.endConnection)
	g.loseConnection()

def parse(input, proc=None, ctx=None):
	"""\
		Read input (which must be something with a readline() method),
		run through the tokenizer, pass to @cmd's add().
		"""
	if not ctx: ctx=Context
	ctx = ctx(fname="<stdin>")
	if proc is None: proc = main_words(ctx)
	g = Parser(proc, ctx=ctx)
	d = threads.deferToThread(_parse,g,input) # read the input
	d.addCallback(lambda _: g.result)         # analyze the result
	return d

if __name__ == "__main__":
	main_words.register_statement(Help)

	def logger(*x):
		print " ".join((str(d) for d in x))

	import sys
	d = parse(sys.stdin, logger=logger)
	def die(_):
		from homevent.reactor import stop_mainloop
		stop_mainloop()
	d.addBoth(die)

	reactor.run()

