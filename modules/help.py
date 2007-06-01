# -*- coding: utf-8 -*-

"""\
This code implements the Help command.

"""

from homevent.module import Module
from homevent.logging import log
from homevent.statement import Statement, global_words

class Help(Statement):
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
			words._get_wordlist()
		except AttributeError: # it's empty
			pass
		else:
			maxlen=0
			for h in words.iterkeys():
				hlen = len(" ".join(h))
				if hlen > maxlen: maxlen = hlen
			if maxlen:
				print >>self.ctx.out,"Known words:"
				def nam(a,b):
					return cmp(a.name,b.name)
				for h in sorted(words.itervalues(),nam):
					hname = " ".join(h.name)
					print >>self.ctx.out,hname+(" "*(maxlen+1-len(hname)))+": "+h.doc


class HelpModule(Module):
	"""\
		This module implements the Help command.
		"""

	info = "implements the 'help' statement"

	def load(self):
		global_words.register_statement(Help)
	
	def unload(self):
		global_words.unregister_statement(Help)
	
init = HelpModule