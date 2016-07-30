#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division, unicode_literals
##
##  This file is part of MoaT, the Master of all Things.
##
##  MoaT is Copyright © 2007-2016 by Matthias Urlichs <matthias@urlichs.de>,
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

from moat import patch; patch()
from qbroker import setup; setup(gevent=True)
import os
import sys
import gevent
import qbroker
import aiogevent

### this import must not happen before settings are completely loaded
from hamlish_jinja import Hamlish
Hamlish._self_closing_jinja_tags.add('csrf_token')

import django
django.setup()

if __name__ == "__main__":
    from django.core.management import execute_from_command_line

    g = gevent.spawn(execute_from_command_line,sys.argv)
    t = aiogevent.wrap_greenlet(g,loop=qbroker.loop)
    qbroker.loop.run_until_complete(t)
