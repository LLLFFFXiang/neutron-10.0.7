# Copyright (c) 2015 Cloudbase Solutions.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os

import eventlet
from oslo_utils import importutils


def monkey_patch():
    if os.name == 'nt':
        # eventlet monkey patching the os and thread modules causes
        # subprocess.Popen to fail on Windows when using pipes due
        # to missing non-blocking IO support.
        #
        # bug report on eventlet:
        # https://bitbucket.org/eventlet/eventlet/issue/132/
        #       eventletmonkey_patch-breaks
        eventlet.monkey_patch(os=False, thread=False)
    else:
        # NOTE(slaweq): to workaround issue with import cycles in
        # eventlet < 0.22.0;
        # This issue is fixed in eventlet with patch
        # https://github.com/eventlet/eventlet/commit/b756447bab51046dfc6f1e0e299cc997ab343701
        # For details please check
        # https://bugs.launchpad.net/neutron/+bug/1745013
        eventlet.hubs.get_hub()
        eventlet.monkey_patch()
        p_c_e = importutils.import_module('pyroute2.config.eventlet')
        p_c_e.eventlet_config()
