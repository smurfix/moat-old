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

"""List of known devices"""

import os
from ..script.util import objects

import logging
logger = logging.getLogger(__name__)

from etcd_tree import EtcString,EtcDir,EtcFloat,EtcInteger,EtcValue, ReloadRecursive
import aio_etcd as etcd
from time import time
from weakref import ref

from moat.util import do_async
from moat.types import TYPEDEF_DIR,TYPEDEF
from dabroker.unit.rpc import CC_DATA
from . import devices, DEV

import logging
logger = logging.getLogger(__name__)

class BaseModule(recEtcDir):
	"""\
		This is the parent class for MoaT modules.

		A Module is a subsystem that extends MoaT with new devices and
		buses.

		"""

	#prefix = None
	description = "Base class for modules"

def modules():
	# we want all objects with a distinctive prefix
	return objects(__name__, BaseModule, filter=lambda x:x.__dict__.get('prefix',None) is not None)
